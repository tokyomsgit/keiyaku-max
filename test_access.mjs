// Who may use the web version: ALLOWED_EMAILS with "@domain" entries, closed when unset.
// Also checks the cases function (moved from the Supabase edge function) sits behind it.
// Offline: login and the database are mocked.  Usage: node test_access.mjs
import assert from 'node:assert/strict';
import { allowedEmail } from './netlify/lib/common.mjs';

const LIST = '@tokyoms.co.jp, owner@gmail.com';
assert.equal(allowedEmail('arai@tokyoms.co.jp', LIST), true);
assert.equal(allowedEmail('Sales.Person@TOKYOMS.CO.JP', LIST), true);
assert.equal(allowedEmail('owner@gmail.com', LIST), true);
assert.equal(allowedEmail('someone@gmail.com', LIST), false);
assert.equal(allowedEmail('x@evil-tokyoms.co.jp', LIST), false);
assert.equal(allowedEmail('x@tokyoms.co.jp.evil.com', LIST), false);
assert.equal(allowedEmail('arai@tokyoms.co.jp', ''), false, 'an unset list lets nobody in');
assert.equal(allowedEmail('', LIST), false);

let email = 'arai@tokyoms.co.jp';
const rows = {
  units: [{ unit_id: 'u1', building_id: 'b1', unit_name: '301', house_number: '架空一丁目12番3の301', updated_at: '2026-01-01' }],
  buildings: [{ building_id: 'b1', building_name: 'テストマンション', registry_location: '港区架空一丁目' }],
  cases: [{ case_id: 'c1', unit_id: 'u1', updated_at: '2026-01-02' }],
  documents: [{ document_id: 'd1', unit_id: 'u1' }],
  value_diffs: [{ diff_id: 'x', field_code: 'unit_name', document_id: 'd1', review_status: 'unreviewed' }],
  field_master: [{ field_code: 'unit_name', label_ja: '号室' }],
};
process.env.SUPABASE_URL = 'https://example.supabase.co';
process.env.SUPABASE_SERVICE_ROLE_KEY = 'test';
process.env.ALLOWED_EMAILS = LIST;
globalThis.fetch = async (url) => {
  url = String(url);
  if (url.includes('/auth/v1/user')) return new Response(JSON.stringify({ id: 'u', email }), { status: 200 });
  const table = url.split('/rest/v1/')[1].split('?')[0];
  return new Response(JSON.stringify(rows[table] || []), { status: 200 });
};
const handler = (await import('./netlify/functions/cases.mjs')).default;
const call = async () => {
  const response = await handler(new Request('https://keiyaku-max.netlify.app/.netlify/functions/cases?action=state', { headers: { authorization: 'Bearer t' } }));
  return { status: response.status, body: await response.json() };
};

const ok = await call();
assert.equal(ok.status, 200);
assert.deepEqual([ok.body.cases[0].id, ok.body.cases[0].building_name, ok.body.cases[0].unresolved], ['c1', 'テストマンション', 1]);

email = 'someone@gmail.com';
const denied = await call();
assert.equal(denied.status, 403);
assert.equal(denied.body.cases, undefined, 'no case data for an address outside the list');

console.log('PASS: domain and address allow-list, closed when unset, case list only for allowed users');
