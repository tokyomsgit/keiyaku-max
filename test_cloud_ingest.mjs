// Integration check for the intake function against the real private bucket.
// Auth and GitHub dispatch are mocked; storage and DB calls are real.
// Usage: [CASE_ID=...] node test_cloud_ingest.mjs <pdf>...  -> prints job id for cloud_worker.py
import fs from 'node:fs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const pdfs = process.argv.slice(2);
const caseId = process.env.CASE_ID || null;
const realFetch = globalThis.fetch;
const dispatched = [];
globalThis.fetch = async (url, options = {}) => {
  if (String(url).startsWith('https://afdtohxuzuwlqmjbrpar.supabase.co/auth/v1/user')) return new Response(JSON.stringify({ id: 'test-user', email: 'tester@example.com' }), { status: 200 });
  if (String(url).startsWith('https://api.github.com/')) { dispatched.push(JSON.parse(options.body)); return new Response(null, { status: 204 }); }
  return realFetch(url, options);
};
process.env.GITHUB_DISPATCH_TOKEN = 'mock';
process.env.ALLOWED_EMAILS = 'tester@example.com';
const handler = (await import('./netlify/functions/ingest.mjs')).default;
const call = async (action, body, method = 'POST', query = '') => {
  const request = new Request(`https://keiyaku-max.netlify.app/.netlify/functions/ingest?action=${action}${query}`, { method, headers: { authorization: 'Bearer test' }, body: body ? JSON.stringify(body) : undefined });
  const response = await handler(request);
  return { status: response.status, body: await response.json() };
};

assert.equal((await call('start', { files: [{ name: 'x.txt', size: 1, hash: 'a'.repeat(64) }] })).status, 400);
assert.equal((await call('status', null, 'GET', '&job_id=not-a-uuid')).status, 400);
const items = pdfs.map(pdf => { const content = fs.readFileSync(pdf); return { name: pdf.split(/[\\/]/).pop(), size: content.length, hash: crypto.createHash('sha256').update(content).digest('hex'), content }; });
const started = await call('start', { files: items.map(({ content, ...rest }) => rest), case_id: caseId });
assert.equal(started.status, 200, JSON.stringify(started.body));
if (started.body.cached) { console.log('CACHED case', started.body.case_id); process.exit(0); }
for (const upload of started.body.uploads) {
  if (upload.skip) continue;
  const form = new FormData(); form.append('cacheControl', '3600'); form.append('', new Blob([items.find(i => i.hash === upload.hash).content], { type: 'application/pdf' }), 'file.pdf');
  const response = await realFetch(upload.url, { method: 'PUT', headers: { 'x-upsert': 'false' }, body: form });
  assert.ok(response.ok, 'signed upload ' + response.status);
}
const other = globalThis.fetch;
globalThis.fetch = async (url, options) => String(url).includes('/auth/v1/user') ? new Response(JSON.stringify({ id: 'someone-else' }), { status: 200 }) : other(url, options);
assert.equal((await call('status', null, 'GET', `&job_id=${started.body.job_id}`)).status, 403);
globalThis.fetch = other;
const run = await call('run', { job_id: started.body.job_id });
assert.equal(run.status, 200, JSON.stringify(run.body));
assert.equal(run.body.status, 'queued');
assert.equal(dispatched.at(-1).inputs.job_id, started.body.job_id);
console.log('PASS intake: validation, private signed upload, owner check, queue + dispatch');
console.log('JOB', started.body.job_id);
