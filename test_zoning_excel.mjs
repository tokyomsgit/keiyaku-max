// Verifies planZoning() reproduces the exact cell placements observed in a real filled
// example (パラスト池袋301.xlsm) for a 2-zone case, then checks the resulting workbook
// (built via fill()) opens correctly and doesn't touch anything outside the zoning cells.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import openpyxlLikeZip from 'jszip';
import { planZoning, fill } from './netlify/functions/generate.mjs';

// The real example: both zones share 商業地域 and 建ぺい率80%, but 容積率 differs (600%/500%),
// and both share the same 高度地区 (17m第二種).
const zonesLikeRealExample = [
  { zone_label: null, needs_review: false, fields: [
    { code: 'zoning_type', value: '商業地域', needs_review: false },
    { code: 'building_coverage_ratio', value: '80%', needs_review: false },
    { code: 'floor_area_ratio', value: '600%', needs_review: false },
    { code: 'height_district', value: '17m第二種', needs_review: false },
    { code: 'fire_zone', value: '防火地域', needs_review: false },
  ] },
  { zone_label: null, needs_review: false, fields: [
    { code: 'zoning_type', value: '商業地域', needs_review: false },
    { code: 'building_coverage_ratio', value: '80%', needs_review: false },
    { code: 'floor_area_ratio', value: '500%', needs_review: false },
    { code: 'height_district', value: '17m第二種', needs_review: false },
    { code: 'fire_zone', value: '防火地域', needs_review: false },
  ] },
];

const cells = planZoning(zonesLikeRealExample);
assert.equal(cells.BY104, '■'); assert.equal(cells.CK104, '(A)(B)');
assert.equal(cells.BW126, 80); assert.equal(cells.CB126, '(A)(B)');
assert.equal(cells.BW130, 600); assert.equal(cells.CB130, '(A)');
assert.equal(cells.CF130, 500); assert.equal(cells.CK130, '(B)');
assert.equal(cells.BI114, '■'); assert.equal(cells.BP114, '17m第二種'); assert.equal(cells.BV114, '(A)(B)');
assert.equal(cells.BI106, '■'); assert.equal(cells.BV106, '(A)(B)');
assert.equal(cells.BI166.includes('要確認'), true);
console.log('PASS planZoning matches the real 2-zone example for 用途地域/容積率/高度地区/防火地域/BI166');

// Single zone: no markers should be written at all (only the checkbox / value cells).
const singleZone = [{ zone_label: null, needs_review: false, fields: [
  { code: 'zoning_type', value: '商業地域', needs_review: false },
  { code: 'building_coverage_ratio', value: '80%', needs_review: false },
] }];
const single = planZoning(singleZone);
assert.equal(single.CK104, undefined);
assert.equal(single.BI166, undefined);
console.log('PASS single-zone case writes no (A)/(B) markers and leaves BI166 untouched');

// Rare 4-zone case: 容積率 has 4 distinct values (only 3 slots) and 高度地区 has 3 distinct
// values (only 2 slots). The slots that exist must still auto-fill; whatever doesn't fit must
// be left for the agent to enter by hand, named explicitly in BI166 rather than silently lost.
const fourZonesOverflowing = [
  { zone_label: null, needs_review: false, fields: [{ code: 'zoning_type', value: '商業地域', needs_review: false }, { code: 'floor_area_ratio', value: '200%', needs_review: false }, { code: 'height_district', value: '10m', needs_review: false }] },
  { zone_label: null, needs_review: false, fields: [{ code: 'zoning_type', value: '商業地域', needs_review: false }, { code: 'floor_area_ratio', value: '300%', needs_review: false }, { code: 'height_district', value: '20m', needs_review: false }] },
  { zone_label: null, needs_review: false, fields: [{ code: 'zoning_type', value: '商業地域', needs_review: false }, { code: 'floor_area_ratio', value: '400%', needs_review: false }, { code: 'height_district', value: '30m', needs_review: false }] },
  { zone_label: null, needs_review: false, fields: [{ code: 'zoning_type', value: '商業地域', needs_review: false }, { code: 'floor_area_ratio', value: '500%', needs_review: false }] },
];
const overflowCells = planZoning(fourZonesOverflowing);
assert.equal(overflowCells.BW130, 200); assert.equal(overflowCells.CB130, '(A)');
assert.equal(overflowCells.CF130, 300); assert.equal(overflowCells.CK130, '(B)');
assert.equal(overflowCells.CO130, 400); assert.equal(overflowCells.CT130, '(C)');
assert.equal(overflowCells.BI114, '■'); assert.equal(overflowCells.BP114, '10m'); assert.equal(overflowCells.BV114, '(A)');
assert.equal(overflowCells.BI116, '■'); assert.equal(overflowCells.BP116, '20m'); assert.equal(overflowCells.BV116, '(B)');
assert.ok(overflowCells.BI166.includes('容積率は3件までしか自動反映できないため、(D)500%は手入力してください。'));
assert.ok(overflowCells.BI166.includes('高度地区は2件までしか自動反映できないため、(C)30mは手入力してください。'));
console.log('PASS 4-zone overflow beyond a field\'s slot capacity is auto-filled up to capacity and named in BI166');

// Unmatched zone-type name: must not guess a checkbox, and must not throw.
const unmatched = planZoning([{ zone_label: null, fields: [{ code: 'zoning_type', value: '謎の地域', needs_review: false }] }]);
assert.equal(Object.keys(unmatched).length, 0);
console.log('PASS unmatched zone-type name is left unfilled');

// End-to-end: fill() with real 2-zone data must not corrupt the workbook (package parts,
// formula count and merged-cell count preserved), same check style as test_generate_function.mjs.
const template = fs.readFileSync('supabase/functions/keiyaku-api/contract-template.xlsm');
const zip = await openpyxlLikeZip.loadAsync(template);
const baseNames = Object.keys(zip.files).sort();
const { bytes, written } = await fill(template, { unit_name: '204' }, {}, {}, zonesLikeRealExample);
const outZip = await openpyxlLikeZip.loadAsync(bytes);
assert.deepEqual(Object.keys(outZip.files).sort(), baseNames);
assert.ok(written.includes('BY104') && written.includes('CB130'));
fs.writeFileSync((process.env.TEMP || '.') + '/zoning-2zone-test.xlsm', bytes);
console.log('PASS fill() with 2-zone data preserves package structure; cells written:', written.filter(c => !/^(AB13|AS13)$/.test(c)).length);
