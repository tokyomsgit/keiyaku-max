// Batch value-conflict review. Nothing is written to units/buildings/extracted_values
// until action=confirm runs, and only through the existing per-diff RPCs (which re-verify
// evidence and the current master value themselves). This function only reads and groups.
import { Failure, UUID, authenticate, db, reply } from '../lib/common.mjs';

async function resolveCase(caseId) {
  const raw = String(caseId || '');
  if (raw.startsWith('unit-') && UUID.test(raw.slice(5))) {
    const units = await db(`units?unit_id=eq.${raw.slice(5)}&select=unit_id,building_id&limit=1`);
    if (!units.length) throw new Failure(404, '案件・住戸が見つかりません。');
    return { unitId: units[0].unit_id, buildingId: units[0].building_id };
  }
  if (!UUID.test(raw)) throw new Failure(400, '案件が不正です。');
  const rows = await db(`cases?case_id=eq.${raw}&select=case_id,unit_id,units(building_id)&limit=1`);
  if (!rows.length || !rows[0].unit_id) throw new Failure(404, '案件・住戸が見つかりません。');
  return { unitId: rows[0].unit_id, buildingId: rows[0].units.building_id };
}

const EVIDENT = e => e && e.value !== null && e.value !== undefined && String(e.value) !== 'null'
  && e.confidence != null && e.confidence >= 0.85 && e.page_no > 0 && String(e.source_text || '').trim() !== '';

function needsReviewFlag(version, fieldCode) {
  const raw = version.important_raw_json || version.management_rules_raw_json;
  return Boolean(raw?.fields?.[fieldCode]?.needs_review);
}

async function bundle(unitId, buildingId) {
  const documents = await db(`documents?or=(unit_id.eq.${unitId},and(building_id.eq.${buildingId},document_type.eq.management_rules))&select=document_id,document_type,unit_id,building_id`);
  const documentIds = documents.map(d => d.document_id);
  if (!documentIds.length) return [];
  const diffs = await db(`value_diffs?document_id=in.(${documentIds.join(',')})&review_status=eq.unreviewed&select=diff_id,document_id,old_version_id,new_version_id,field_code,old_value,new_value,affected_field`);
  if (!diffs.length) return [];
  const documentById = new Map(documents.map(d => [d.document_id, d]));
  const versionIds = [...new Set(diffs.flatMap(d => [d.old_version_id, d.new_version_id]).filter(Boolean))];
  const versions = await db(`document_versions?document_version_id=in.(${versionIds.join(',')})&select=document_version_id,original_filename,as_of_date,uploaded_at,version_no,important_raw_json,management_rules_raw_json`);
  const versionById = new Map(versions.map(v => [v.document_version_id, v]));
  const fieldCodes = [...new Set(diffs.map(d => d.field_code))];
  const values = await db(`extracted_values?document_version_id=in.(${versionIds.join(',')})&field_code=in.(${fieldCodes.map(f => `"${f}"`).join(',')})&select=document_version_id,field_code,value,confidence,source_text,page_no,value_as_of_date,registry_provenance`);
  const valueByKey = new Map(values.map(v => [`${v.document_version_id}:${v.field_code}`, v]));
  const labels = new Map((await db(`field_master?field_code=in.(${fieldCodes.map(f => `"${f}"`).join(',')})&select=field_code,label_ja`)).map(f => [f.field_code, f.label_ja]));

  const side = (versionId, fieldCode) => {
    const version = versionById.get(versionId);
    const value = valueByKey.get(`${versionId}:${fieldCode}`);
    if (!version) return { document_version_id: versionId || null, filename: null, as_of_date: null, page_no: null, source_text: null, trusted: false };
    const evident = EVIDENT(value) && !value.registry_provenance?.needs_review && !needsReviewFlag(version, fieldCode);
    return {
      document_version_id: versionId, filename: version.original_filename, as_of_date: value?.value_as_of_date || version.as_of_date || version.uploaded_at,
      page_no: value?.page_no ?? null, source_text: value?.source_text || null, trusted: evident,
    };
  };

  const groups = new Map();
  for (const diff of diffs) {
    const document = documentById.get(diff.document_id);
    const key = diff.field_code + '|' + JSON.stringify(diff.old_value) + '|' + (diff.old_version_id || '');
    if (!groups.has(key)) {
      groups.set(key, {
        field_code: diff.field_code, label: labels.get(diff.field_code) || diff.field_code,
        baseline: { value: diff.old_value, ...side(diff.old_version_id, diff.field_code) },
        candidates: [],
      });
    }
    const info = side(diff.new_version_id, diff.field_code);
    groups.get(key).candidates.push({
      diff_id: diff.diff_id, value: diff.new_value, document_type: document?.document_type || null,
      affected_field: diff.affected_field, selectable: info.trusted, ...info,
    });
  }
  const result = [...groups.values()].filter(g => g.candidates.length);
  for (const group of result) {
    // Only a selectable (trusted) candidate can ever be recommended: the adopt RPCs always
    // reject an unselectable one (registry_provenance.needs_review etc.), so defaulting the
    // radio to one just guarantees a failed confirm — and since confirm() below submits every
    // group in one batch, one bad default used to break every OTHER field's confirm too.
    const dated = c => c.as_of_date || '';
    const ranked = [...group.candidates].filter(c => c.selectable).sort((a, b) => dated(b).localeCompare(dated(a)));
    const best = ranked[0];
    group.recommended_diff_id = best && dated(best) > dated(group.baseline) ? best.diff_id : null;
  }
  return result;
}

async function confirm(caseId, unitId, buildingId, selections) {
  const groups = await bundle(unitId, buildingId);
  const byField = new Map(groups.map(g => [g.field_code, g]));
  const results = [];
  const failures = [];
  // Each group's RPC calls are independent of every other group's, so one group failing
  // (a stale candidate, or a candidate whose evidence turned out insufficient) must not
  // stop unrelated fields elsewhere in the same batch from being confirmed.
  for (const selection of selections || []) {
    const group = byField.get(String(selection.field_code || ''));
    if (!group) continue; // Already resolved or unknown; nothing to do.
    const chosenId = selection.diff_id ? String(selection.diff_id) : null;
    if (chosenId && !group.candidates.some(c => c.diff_id === chosenId)) {
      failures.push(`「${group.label}」の候補が変わりました。画面を再読込してください。`);
      continue;
    }
    for (const candidate of group.candidates) {
      const adopt = candidate.diff_id === chosenId;
      // Mirrors web_data.decide(): purchase-baseline diffs route first, regardless of the
      // underlying document's type, since save_management_rules/save reports can both feed it.
      const body = String(candidate.affected_field || '').startsWith('purchase:')
        ? { name: 'web_review_purchase_diff', p: { case_id: caseId, diff_id: candidate.diff_id, action: adopt ? 'adopt' : 'hold' } }
        : candidate.document_type === 'management_rules'
          ? { name: 'review_management_rules_diff', p: { case_id: caseId, diff_id: candidate.diff_id, action: adopt ? 'adopt' : 'hold' } }
          : { name: 'web_review_diff', p: { unit_id: unitId, diff_id: candidate.diff_id, action: adopt ? 'adopt' : 'hold' } };
      try {
        const response = await db(`rpc/${body.name}`, { method: 'POST', body: JSON.stringify({ p: body.p }) });
        results.push({ field_code: group.field_code, diff_id: candidate.diff_id, ...response });
      } catch (error) {
        failures.push(`「${group.label}」: ${error instanceof Failure ? error.message : '確定できませんでした。'}`);
      }
    }
  }
  if (failures.length) throw new Failure(409, failures.join(' '));
  return results;
}

export default async (request) => {
  try {
    await authenticate(request);
    const url = new URL(request.url);
    const action = url.searchParams.get('action') || 'list';
    if (request.method === 'GET' && action === 'list') {
      const { unitId, buildingId } = await resolveCase(url.searchParams.get('case_id'));
      return reply(200, { groups: await bundle(unitId, buildingId) });
    }
    if (request.method === 'POST' && action === 'confirm') {
      const text = await request.text();
      if (text.length > 20000) throw new Failure(413, '入力が大きすぎます。');
      const body = JSON.parse(text || '{}');
      const { unitId, buildingId } = await resolveCase(body.case_id);
      const results = await confirm(String(body.case_id), unitId, buildingId, Array.isArray(body.selections) ? body.selections : []);
      return reply(200, { applied: results.length });
    }
    throw new Failure(404, '操作がありません。');
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    if (error instanceof SyntaxError) return reply(400, { error: '入力内容を確認してください。' });
    console.error('review failure', error instanceof Error ? error.message.slice(0, 60) : 'unknown');
    return reply(500, { error: '確認内容を保存できませんでした。管理者へ連絡してください。' });
  }
};
