// Generates XLSM for live cases with the Netlify function code (DB read-only).
// Usage: node test_generate_function.mjs <case_id>...
import fs from 'node:fs';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import { fill } from './netlify/functions/generate.mjs';

const template = fs.readFileSync('supabase/functions/keiyaku-api/contract-template.xlsx');
const q = async path => (await fetch(`${process.env.SUPABASE_URL}/rest/v1/${path}`, { headers: { apikey: process.env.SUPABASE_SERVICE_ROLE_KEY, authorization: `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}` } })).json();
const formulas = async bytes => { const zip = await JSZip.loadAsync(bytes); const xml = await zip.file('xl/worksheets/sheet1.xml')?.async('string'); return { names: Object.keys(zip.files).sort(), f: (xml || '').match(/<f[\s>]/g)?.length || 0 }; };
const base = await formulas(template);
assert.equal((await fill(template, { unit_name: '1', built_date: '1989-01-07' }, {}, {})).written.includes('U34'), true);
for (const id of process.argv.slice(2)) {
  const realCase = (await q(`cases?case_id=eq.${id}&select=*`))[0];
  const unit = (await q(`units?unit_id=eq.${realCase.unit_id}&select=*`))[0];
  const building = (await q(`buildings?building_id=eq.${unit.building_id}&select=*`))[0];
  const { bytes, written } = await fill(template, unit, building, realCase);
  const out = await formulas(bytes);
  assert.deepEqual(out.names, base.names, 'package parts preserved');
  assert.equal(out.f, base.f, 'formula count preserved');
  fs.writeFileSync(`${process.env.TEMP || '.'}/generated-${id.slice(0, 8)}.xlsm`, bytes);
  console.log('PASS', id.slice(0, 8), 'cells', written.length, 'formulas', out.f);
}
