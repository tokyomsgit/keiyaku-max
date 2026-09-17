// Cloud PDF intake. Secrets stay in Netlify environment variables; PDFs go to a private bucket.
import { Failure, UUID, authenticate, config, db, reply } from '../lib/common.mjs';

const BUCKET = 'keiyaku-private';
const REPO = 'tokyomsgit/keiyaku-max';
const WORKFLOW = 'cloud-ingest.yml';
const HASH = /^[a-f0-9]{64}$/;
const STALE_MS = 25 * 60 * 1000;
const KINDS = ['purchase', 'registry', 'report', 'rules', 'skip'];
const PROPERTY_TYPES = ['condominium_land_right', 'condominium_no_land_right', 'leasehold_condominium', 'detached_house', 'unknown'];

async function storage(method, path, body, headers = {}) {
  const { url, key } = config();
  return fetch(`${url}/storage/v1/${path}`, { method, body, headers: { apikey: key, authorization: `Bearer ${key}`, ...headers } });
}

async function readJob(id) {
  if (!UUID.test(id || '')) throw new Failure(400, '処理番号が不正です。');
  const response = await storage('GET', `object/${BUCKET}/jobs/${id}.json`);
  if (!response.ok) throw new Failure(404, '処理が見つかりません。もう一度PDFを追加してください。');
  return response.json();
}

async function writeJob(job) {
  const response = await storage('POST', `object/${BUCKET}/jobs/${job.id}.json`, JSON.stringify(job), { 'Content-Type': 'application/json', 'x-upsert': 'true' });
  if (!response.ok) throw new Failure(502, '処理状態を保存できませんでした。');
}

async function exists(hash) {
  const response = await storage('HEAD', `object/${BUCKET}/uploads/${hash}.pdf`);
  return response.ok;
}

async function ownJob(id, user) {
  const job = await readJob(id);
  if (job.owner !== user.id) throw new Failure(403, 'この処理は操作できません。');
  return job;
}

async function caseForUnit(unitId) {
  let cases = await db(`cases?unit_id=eq.${encodeURIComponent(unitId)}&case_status=neq.completed&select=case_id&order=updated_at.desc&limit=1`);
  if (!cases.length) cases = await db('cases', { method: 'POST', headers: { Prefer: 'return=representation' }, body: JSON.stringify({ unit_id: unitId, case_status: 'draft' }) });
  return cases[0].case_id;
}

async function resolveCase(caseId) {
  if (!caseId) return { caseId: null, unitId: null };
  const raw = String(caseId);
  if (raw.startsWith('unit-') && UUID.test(raw.slice(5))) {
    const units = await db(`units?unit_id=eq.${raw.slice(5)}&select=unit_id&limit=1`);
    if (!units.length) throw new Failure(404, '案件・住戸が見つかりません。');
    return { caseId: await caseForUnit(units[0].unit_id), unitId: units[0].unit_id };
  }
  if (!UUID.test(raw)) throw new Failure(400, '案件が不正です。');
  const rows = await db(`cases?case_id=eq.${raw}&select=case_id,unit_id&limit=1`);
  if (!rows.length || !rows[0].unit_id) throw new Failure(404, '案件・住戸が見つかりません。');
  return { caseId: rows[0].case_id, unitId: rows[0].unit_id };
}

async function dispatch(job) {
  const token = process.env.GITHUB_DISPATCH_TOKEN || '';
  if (!token) throw new Failure(500, '読取サーバーの設定が完了していません。管理者へ連絡してください。');
  const response = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: 'POST',
    headers: { authorization: `Bearer ${token}`, accept: 'application/vnd.github+json', 'x-github-api-version': '2022-11-28', 'user-agent': 'keiyaku-max' },
    body: JSON.stringify({ ref: 'main', inputs: { job_id: job.id } }),
  });
  if (!response.ok) throw new Failure(502, '読取処理を開始できませんでした。時間をおいて再度お試しください。');
}

function publicJob(job) {
  let { status, message } = job;
  if (['queued', 'running'].includes(status) && Date.now() - Date.parse(job.updated_at) > STALE_MS) {
    status = 'failed'; message = '読取処理が時間内に終わりませんでした。もう一度お試しください。';
  }
  const view = { job_id: job.id, status, message, case_id: job.case_id || null, files: job.files.map(f => ({ name: f.name, hash: f.hash })) };
  for (const key of ['candidates', 'unknown', 'estimate_jpy', 'ai_files', 'warnings', 'fields', 'page_count', 'property_type_options']) if (job[key] !== undefined) view[key] = job[key];
  return view;
}

async function start(body, user) {
  const files = Array.isArray(body.files) ? body.files : [];
  if (!files.length || files.length > 10) throw new Failure(400, 'PDFは1〜10件選択してください。');
  const seen = new Set();
  const clean = [];
  for (const item of files) {
    const hash = String(item.hash || '').toLowerCase();
    const name = String(item.name || '').replace(/^.*[\\/]/, '').slice(0, 200);
    const size = Number(item.size);
    if (!HASH.test(hash) || !name.toLowerCase().endsWith('.pdf') || !(size > 0 && size <= 50 * 1024 * 1024)) throw new Failure(400, 'PDF（50MB以内）を選択してください。');
    if (seen.has(hash)) continue;
    seen.add(hash); clean.push({ name, hash, size });
  }
  let { caseId, unitId } = await resolveCase(body.case_id);
  const versions = await db(`document_versions?file_hash=in.(${clean.map(f => f.hash).join(',')})&select=document_id,file_hash`);
  const cachedHashes = new Set();
  if (versions.length) {
    const ids = [...new Set(versions.map(v => v.document_id))];
    const documents = await db(`documents?document_id=in.(${ids.join(',')})&select=document_id,unit_id,building_id,document_type`);
    // Unlinked analyses are not a usable case; the worker links them through the normal match rules.
    const linked = new Map(documents.filter(d => d.unit_id).map(d => [d.document_id, d]));
    for (const v of versions) if (linked.has(v.document_id)) cachedHashes.add(v.file_hash);
    const units = [...new Set([...linked.values()].map(d => d.unit_id))];
    if (units.length > 1 || (unitId && units.length && units[0] !== unitId)) throw new Failure(409, '解析済みの資料が別の物件に登録されています。自動で紐付けせず停止しました。資料を分けて追加してください。');
    if (!unitId && units.length === 1) { unitId = units[0]; caseId = await caseForUnit(unitId); }
  }
  const missing = clean.filter(f => !cachedHashes.has(f.hash));
  if (!missing.length) {
    if (!caseId) throw new Failure(409, '解析済みの資料から物件を特定できませんでした。');
    return { cached: true, case_id: caseId };
  }
  const job = { id: crypto.randomUUID(), owner: user.id, status: 'awaiting_upload', message: 'PDFを送信しています。', case_id: caseId, files: missing, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
  const uploads = [];
  for (const file of missing) {
    if (await exists(file.hash)) { uploads.push({ hash: file.hash, skip: true }); continue; }
    const response = await storage('POST', `object/upload/sign/${BUCKET}/uploads/${file.hash}.pdf`, '{}', { 'Content-Type': 'application/json' });
    if (!response.ok) throw new Failure(502, 'PDFの送信準備ができませんでした。');
    const signed = await response.json();
    uploads.push({ hash: file.hash, url: `${config().url}/storage/v1${signed.url}` });
  }
  await writeJob(job);
  return { cached: false, job_id: job.id, uploads };
}

async function run(body, user) {
  const job = await ownJob(body.job_id, user);
  if (['queued', 'running'].includes(job.status) && Date.now() - Date.parse(job.updated_at) < STALE_MS) return publicJob(job);
  if (job.status === 'done') return publicJob(job);
  for (const file of job.files) if (!(await exists(file.hash))) throw new Failure(409, `「${file.name}」の送信が完了していません。もう一度追加してください。`);
  if (body.ai_confirmed === true) job.ai_confirmed = true;
  if (typeof body.candidate_id === 'string') {
    if (!UUID.test(body.candidate_id) || !(job.candidates || []).some(c => c.id === body.candidate_id)) throw new Failure(400, '表示された候補から選んでください。');
    job.candidate_id = body.candidate_id;
  }
  if (body.kinds && typeof body.kinds === 'object') {
    const kinds = { ...(job.kinds || {}) };
    for (const [hash, kind] of Object.entries(body.kinds)) {
      if (!job.files.some(f => f.hash === hash) || !KINDS.includes(kind)) throw new Failure(400, '資料の種類を選び直してください。');
      kinds[hash] = kind;
    }
    job.kinds = kinds;
  }
  if (body.purchase_entries !== undefined || body.property_type !== undefined) {
    // The worker (verify_fields) re-validates every entry against the staged read; this only
    // bounds size and shape so a malformed request fails fast instead of reaching Python.
    if (!PROPERTY_TYPES.includes(body.property_type)) throw new Failure(400, '物件種別を選んでください。');
    const known = new Set((job.fields || []).map(f => f.code));
    const entries = Array.isArray(body.purchase_entries) ? body.purchase_entries : [];
    if (!entries.length || entries.length > 80) throw new Failure(400, '確認した項目を選んでください。');
    for (const entry of entries) {
      if (!entry || typeof entry !== 'object' || !known.has(entry.code) || !Number.isInteger(entry.page_no) || entry.page_no < 1
        || typeof entry.source_text !== 'string' || !entry.source_text.trim() || entry.value === undefined) {
        throw new Failure(400, '確認内容を確認してください。');
      }
    }
    job.property_type = body.property_type;
    job.purchase_entries = entries.map(e => ({ ...e, verified: true }));
  }
  Object.assign(job, { status: 'queued', message: '読取の順番を待っています。', updated_at: new Date().toISOString() });
  await writeJob(job);
  await dispatch(job);
  return publicJob(job);
}

export default async (request) => {
  try {
    const user = await authenticate(request);
    const action = new URL(request.url).searchParams.get('action');
    if (request.method === 'GET' && action === 'status') return reply(200, publicJob(await ownJob(new URL(request.url).searchParams.get('job_id'), user)));
    if (request.method !== 'POST') throw new Failure(404, '操作がありません。');
    const text = await request.text();
    if (text.length > 20000) throw new Failure(413, '入力が大きすぎます。');
    const body = JSON.parse(text || '{}');
    if (action === 'start') return reply(200, await start(body, user));
    if (action === 'run') return reply(200, await run(body, user));
    throw new Failure(404, '操作がありません。');
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    if (error instanceof SyntaxError) return reply(400, { error: '入力内容を確認してください。' });
    console.error('ingest failure');
    return reply(500, { error: '処理を完了できませんでした。管理者へ連絡してください。' });
  }
};
