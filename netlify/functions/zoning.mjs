// Surfaces the building's zoning reference (documents.document_type='zoning',
// extracted_values.field_code='zoning_info') for the case detail screen. The actual
// read/OCR/AI happens in cloud_worker.py during ingest; this function only reads that
// result (action=get) and, for the multi-zone case, lets the user fix the (A)/(B)/(C)
// order (action=reorder) — the Excel writer letters purely by zones[] array position
// (see generate.mjs's ZONE_LETTERS/groupZones), and upload order across two separate
// single-zone certificates has no relation to which side is actually "A".
import { Failure, UUID, authenticate, db, reply } from '../lib/common.mjs';

const ZONE_LETTERS = ['A', 'B', 'C'];

async function resolveBuildingId(caseId) {
  const raw = String(caseId || '');
  if (raw.startsWith('unit-') && UUID.test(raw.slice(5))) {
    const units = await db(`units?unit_id=eq.${raw.slice(5)}&select=building_id&limit=1`);
    return units[0]?.building_id || null;
  }
  if (!UUID.test(raw)) throw new Failure(400, '案件が不正です。');
  const rows = await db(`cases?case_id=eq.${raw}&select=units(building_id)&limit=1`);
  return rows[0]?.units?.building_id || null;
}

async function latestVersion(buildingId) {
  const documents = await db(`documents?document_type=eq.zoning&building_id=eq.${buildingId}&select=document_id`);
  if (!documents.length) return null;
  const versions = await db(`document_versions?document_id=eq.${documents[0].document_id}&select=document_version_id,version_no,original_filename,as_of_date&order=version_no.desc&limit=1`);
  if (!versions.length) return null;
  const values = await db(`extracted_values?document_version_id=eq.${versions[0].document_version_id}&field_code=eq.zoning_info&select=value,reviewed`);
  if (!values.length) return null;
  return { documentId: documents[0].document_id, version: versions[0], reviewed: Boolean(values[0].reviewed), zones: values[0].value || [] };
}

async function reorder(buildingId, order) {
  const current = await latestVersion(buildingId);
  if (!current || !current.zones.length) throw new Failure(404, '用途地域資料がありません。');
  const zones = current.zones;
  const valid = Array.isArray(order) && order.length === zones.length && zones.map((_, i) => i).every(i => order.includes(i));
  if (!valid) throw new Failure(400, '並び替えの指定が不正です。');
  const reordered = order.map((sourceIndex, position) => ({ ...zones[sourceIndex], zone_label: ZONE_LETTERS[position] || null }));
  const versionPayload = { document_id: current.documentId, version_no: current.version.version_no + 1, source_type: 'seller_provided',
    status: 'provisional', original_filename: current.version.original_filename };
  if (current.version.as_of_date) versionPayload.as_of_date = current.version.as_of_date;
  const [version] = await db('document_versions', { method: 'POST', headers: { Prefer: 'return=representation' }, body: JSON.stringify(versionPayload) });
  await db('extracted_values', { method: 'POST', headers: { Prefer: 'return=representation' }, body: JSON.stringify({
    document_version_id: version.document_version_id, field_code: 'zoning_info', value: reordered,
    confidence: current.reviewed ? 1.0 : null, page_no: 1, source_text: current.version.original_filename,
    reviewed: current.reviewed, approved: current.reviewed }) });
  return { filename: version.original_filename, as_of_date: version.as_of_date, reviewed: current.reviewed, zones: reordered };
}

export default async (request) => {
  try {
    await authenticate(request);
    const url = new URL(request.url);
    const action = url.searchParams.get('action') || 'get';
    if (request.method === 'GET' && action === 'get') {
      const buildingId = await resolveBuildingId(url.searchParams.get('case_id'));
      if (!buildingId) return reply(200, { zoning: null });
      const current = await latestVersion(buildingId);
      if (!current) return reply(200, { zoning: null });
      return reply(200, { zoning: { filename: current.version.original_filename, as_of_date: current.version.as_of_date, reviewed: current.reviewed, zones: current.zones } });
    }
    if (request.method === 'POST' && action === 'reorder') {
      const body = await request.json().catch(() => ({}));
      const buildingId = await resolveBuildingId(body.case_id);
      if (!buildingId) throw new Failure(400, '案件が不正です。');
      const zoning = await reorder(buildingId, body.order);
      return reply(200, { zoning });
    }
    throw new Failure(404, '操作がありません。');
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    console.error('zoning failure', error instanceof Error ? error.message.slice(0, 60) : 'unknown');
    return reply(500, { error: '用途地域情報を取得できませんでした。' });
  }
};
