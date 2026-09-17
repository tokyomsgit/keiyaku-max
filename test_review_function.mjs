// Read-only check of the review bundle against the live DB, plus a mocked-auth request test.
// Usage: node test_review_function.mjs <case_id>
import assert from 'node:assert/strict';

const [caseId] = process.argv.slice(2);
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, options = {}) => {
  if (String(url).startsWith('https://afdtohxuzuwlqmjbrpar.supabase.co/auth/v1/user')) return new Response(JSON.stringify({ id: 'test-user' }), { status: 200 });
  return realFetch(url, options);
};
const handler = (await import('./netlify/functions/review.mjs')).default;
const call = async (action, method, body, extraQuery = '') => {
  const request = new Request(`https://keiyaku-max.netlify.app/.netlify/functions/review?action=${action}${extraQuery}`, { method, headers: { authorization: 'Bearer test' }, body: body ? JSON.stringify(body) : undefined });
  const response = await handler(request);
  return { status: response.status, body: await response.json() };
};

assert.equal((await call('list', 'GET', null, '&case_id=not-a-uuid')).status, 400);
assert.equal((await call('confirm', 'POST', { case_id: caseId, selections: [{ field_code: 'current_owner_name', diff_id: 'bogus' }] })).status, 409);

const list = await call('list', 'GET', null, `&case_id=${caseId}`);
assert.equal(list.status, 200, JSON.stringify(list.body));
for (const group of list.body.groups) {
  assert.ok(group.field_code && group.label);
  assert.ok(Array.isArray(group.candidates) && group.candidates.length);
  for (const c of group.candidates) {
    assert.ok('diff_id' in c && 'value' in c && 'filename' in c && 'as_of_date' in c && 'page_no' in c && 'source_text' in c && 'selectable' in c);
    if (group.recommended_diff_id === c.diff_id) assert.equal(c.selectable, true, 'recommended must be selectable');
  }
}
console.log('PASS review:list', list.body.groups.length, 'group(s)');
console.log(JSON.stringify(list.body.groups, null, 2).slice(0, 4000));
