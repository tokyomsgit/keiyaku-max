// Case list and manual case creation, ported from supabase/functions/keiyaku-api (state, create)
// so that they sit behind the same ALLOWED_EMAILS check as every other Netlify function.
import { Failure, authenticate, db, reply } from '../lib/common.mjs';

const enc = encodeURIComponent;

async function insert(table, payload) {
  return db(table, { method: 'POST', headers: { Prefer: 'return=representation' }, body: JSON.stringify(payload) });
}

async function getState() {
  const [units, buildings, cases, documents, diffs, fields] = await Promise.all([
    db('units?select=*&order=updated_at.desc'),
    db('buildings?select=*&order=updated_at.desc'),
    db('cases?select=*&order=updated_at.desc'),
    db('documents?select=document_id,unit_id'),
    db('value_diffs?select=diff_id,field_code,old_value,new_value,review_status,document_id&review_status=eq.unreviewed'),
    db('field_master?select=field_code,label_ja'),
  ]);
  const buildingById = new Map(buildings.map(item => [item.building_id, item]));
  const documentUnit = new Map(documents.map(item => [item.document_id, item.unit_id]));
  const labels = new Map(fields.map(item => [item.field_code, item.label_ja]));
  const casesByUnit = new Map();
  for (const item of cases) casesByUnit.set(item.unit_id, [...(casesByUnit.get(item.unit_id) || []), item]);
  return {
    mode: 'live',
    cases: units.map(unit => {
      const building = buildingById.get(unit.building_id) || {};
      const realCase = (casesByUnit.get(unit.unit_id) || [])[0];
      const reviews = diffs.filter(item => documentUnit.get(item.document_id) === unit.unit_id).map(item => ({ ...item, label: labels.get(item.field_code) || item.field_code }));
      return {
        id: realCase?.case_id || `unit-${unit.unit_id}`,
        unit_id: unit.unit_id,
        building_name: building.building_name || '物件名未取得',
        unit_name: unit.unit_name || '号室未取得',
        address: building.display_address || building.registry_location || '所在地未取得',
        owner: unit.current_owner_name || '所有者未取得',
        area: unit.registered_area,
        updated_at: realCase?.updated_at || unit.updated_at,
        unresolved: reviews.length,
        reviews,
        fields: [
          ['建物名', building.building_name], ['号室', unit.unit_name], ['登記所在', building.registry_location],
          ['家屋番号', unit.house_number], ['所有者', unit.current_owner_name], ['登記面積', unit.registered_area],
          ['管理費', unit.management_fee], ['修繕積立金', unit.repair_reserve_fee],
        ].map(([label, value]) => ({ label, value })),
      };
    }),
  };
}

async function createCase(body) {
  const buildingName = String(body.building_name || '').trim();
  const unitName = String(body.unit_name || '').trim();
  const registryLocation = String(body.registry_location || '').trim();
  const houseNumber = String(body.house_number || '').trim();
  if (!buildingName || !unitName || !registryLocation || !houseNumber) throw new Failure(400, '物件名・号室・登記所在・家屋番号を入力してください。');
  const ambiguous = new Failure(409, '同じ識別情報の物件候補があります。既存案件から選択してください。');
  let building = await db(`buildings?registry_location=eq.${enc(registryLocation)}&select=*&limit=2`);
  if (building.length > 1) throw ambiguous;
  if (!building.length) building = await insert('buildings', { building_name: buildingName, registry_location: registryLocation, display_address: String(body.display_address || '').trim() || null });
  const buildingId = building[0].building_id;
  let units = await db(`units?house_number=eq.${enc(houseNumber)}&select=*&limit=2`);
  if (units.length && units[0].building_id !== buildingId) throw ambiguous;
  if (!units.length) units = await insert('units', { building_id: buildingId, unit_name: unitName, house_number: houseNumber });
  const unitId = units[0].unit_id;
  let cases = await db(`cases?unit_id=eq.${enc(unitId)}&case_status=neq.completed&select=*&order=updated_at.desc&limit=1`);
  if (!cases.length) cases = await insert('cases', { unit_id: unitId, case_status: 'draft' });
  return { state: await getState(), case_id: cases[0].case_id };
}

export default async (request) => {
  try {
    await authenticate(request);
    const action = new URL(request.url).searchParams.get('action') || 'state';
    if (request.method === 'GET' && action === 'state') return reply(200, await getState());
    if (request.method === 'POST' && action === 'create') {
      const text = await request.text();
      if (text.length > 4000) throw new Failure(413, '入力が大きすぎます。');
      return reply(201, await createCase(JSON.parse(text || '{}')));
    }
    throw new Failure(404, '操作がありません。');
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    if (error instanceof SyntaxError) return reply(400, { error: '入力内容を確認してください。' });
    console.error(error);
    return reply(500, { error: '処理に失敗しました。管理者へ連絡してください。' });
  }
};
