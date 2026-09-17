// Read-only: surfaces the building's zoning reference (documents.document_type='zoning',
// extracted_values.field_code='zoning_info') for the case detail screen. Nothing is written
// here; the actual read/OCR/AI happens in cloud_worker.py during ingest.
import { Failure, UUID, authenticate, db, reply } from '../lib/common.mjs';

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

export default async (request) => {
  try {
    await authenticate(request);
    const url = new URL(request.url);
    if (request.method !== 'GET' || (url.searchParams.get('action') || 'get') !== 'get') throw new Failure(404, '操作がありません。');
    const buildingId = await resolveBuildingId(url.searchParams.get('case_id'));
    if (!buildingId) return reply(200, { zoning: null });
    const documents = await db(`documents?document_type=eq.zoning&building_id=eq.${buildingId}&select=document_id`);
    if (!documents.length) return reply(200, { zoning: null });
    const versions = await db(`document_versions?document_id=eq.${documents[0].document_id}&select=document_version_id,original_filename,as_of_date&order=version_no.desc&limit=1`);
    if (!versions.length) return reply(200, { zoning: null });
    const values = await db(`extracted_values?document_version_id=eq.${versions[0].document_version_id}&field_code=eq.zoning_info&select=value,reviewed`);
    if (!values.length) return reply(200, { zoning: null });
    return reply(200, { zoning: { filename: versions[0].original_filename, as_of_date: versions[0].as_of_date, reviewed: Boolean(values[0].reviewed), zones: values[0].value || [] } });
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    console.error('zoning failure', error instanceof Error ? error.message.slice(0, 60) : 'unknown');
    return reply(500, { error: '用途地域情報を取得できませんでした。' });
  }
};
