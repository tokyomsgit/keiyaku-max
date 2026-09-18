// Contract generation from confirmed DB values into the production XLSM template.
// Ported from supabase/functions/keiyaku-api generate(); formula cells are never overwritten.
import fs from 'node:fs';
import path from 'node:path';
import JSZip from 'jszip';
import { Failure, UUID, authenticate, db, reply } from '../lib/common.mjs';
import * as ZMAP from '../lib/zoning_excel_map.mjs';

const TEMPLATE = 'supabase/functions/keiyaku-api/contract-template.xlsm';
// For now only 謄本 is read (see ACTIVE_KINDS in cloud_worker.py). Set true to write zoning again.
const READ_ZONING = false;

function templateBytes() {
  const roots = [process.env.LAMBDA_TASK_ROOT, process.cwd(), path.resolve('.')].filter(Boolean);
  for (const root of roots) {
    const file = path.join(root, TEMPLATE);
    if (fs.existsSync(file)) return fs.readFileSync(file);
  }
  throw new Error('TEMPLATE_MISSING');
}

function escapeXml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

export function patchCell(xml, coordinate, value, written) {
  if (value === null || value === undefined) return xml;
  const pattern = new RegExp(`<c\\b(?=[^>]*\\br="${coordinate}")[^>]*?(?:\\/>|>[\\s\\S]*?<\\/c>)`);
  const match = xml.match(pattern);
  if (!match) throw new Error(`CELL:${coordinate}`);
  if (/<f[\s>/]/.test(match[0])) return xml;
  let attrs = match[0].match(/^<c\b([^>]*?)(?:\/?>)/)?.[1] || ` r="${coordinate}"`;
  attrs = attrs.replace(/\s+t="[^"]*"/g, '');
  if (value === '') return xml.replace(pattern, `<c${attrs}/>`);
  let body;
  if (typeof value === 'number') body = `<v>${value}</v>`;
  else {
    attrs += ' t="inlineStr"';
    body = `<is><t xml:space="preserve">${escapeXml(value)}</t></is>`;
  }
  written.push(coordinate);
  return xml.replace(pattern, `<c${attrs}>${body}</c>`);
}

function dateParts(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00+09:00`);
  if (Number.isNaN(date.valueOf())) return null;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Tokyo', year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(date).map(p => [p.type, Number(p.value)]));
  const key = parts.year * 10000 + parts.month * 100 + parts.day;
  const [era, base] = key >= 20190501 ? ['令和', 2018] : key >= 19890108 ? ['平成', 1988] : key >= 19261225 ? ['昭和', 1925] : [null, 0];
  return era ? { era, year: parts.year - base, month: parts.month, day: parts.day } : null;
}

const compact = value => String(value ?? '').normalize('NFKC').replace(/\s+/g, '');
const REVIEW = '要確認';

// Mirrors practical_contract.plan(): clear every registry input, then write only values that
// fit the template's composed fields. Mismatches are marked 要確認 instead of guessed.
export function plan(unit, building, realCase) {
  const cells = {};
  const put = (cell, value) => { cells[cell] = value ?? ''; };
  const editable = ['AB13','AS13','F15','J15','N15','X15','AJ15','AS15','AB24','AG24','AJ24','AB26','J28','AF28','X30','AF30','J32','Q32','AH32','J34','U34','X34','AB34','AF34','F37','AB37','R54','V54','AR54'];
  for (let row = 23; row < 40; row++) editable.push(`AY${row}`, `BA${row}`);
  for (let row = 42; row < 54; row += 2) for (const col of ['F','U','Y','AB','AG','AL','AT']) editable.push(`${col}${row}`);
  for (const cell of editable) put(cell, '');
  put('AB13', building.building_name || REVIEW);
  put('AS13', unit.unit_name ? compact(unit.unit_name).replace(/号(?:室)?$/, '') : REVIEW);
  put('J28', building.building_structure); put('AF30', unit.unit_name); put('J32', unit.unit_type);
  put('Q32', unit.unit_structure); put('J34', unit.registered_area); put('F37', unit.current_owner_name);
  put('AB37', unit.current_owner_address);
  const floor = compact(unit.unit_floor).match(/^(地下)?(\d+)階(?:部分)?$/);
  if (floor) put('AH32', (floor[1] || '') + floor[2]);
  const built = dateParts(unit.built_date);
  if (built) Object.assign(cells, { U34: built.era, X34: built.year, AB34: built.month, AF34: built.day });
  const lots = Array.isArray(building.land_lots) ? building.land_lots : [];
  const locations = compact(building.registry_location).split(/[・、,]/).map(v => v.replace(/\d+番(?:地)?\d*$/, '')).filter(Boolean);
  const house = compact(unit.house_number).match(/^(.+?)(\d+)番(\d+)の(.+)$/);
  const firstLot = lots[0] ? compact(lots[0].lot_number).match(/^(\d+)番(?:地)?(\d+)$/) : null;
  if (locations.length && firstLot && compact(lots[0].location) === locations[0]) {
    let prefix = house && locations[0].endsWith(house[1]) ? house[1] : '';
    if (!prefix) prefix = locations[0].match(/^.*?[市区町村](.+)$/)?.[1] || '';
    put('J15', prefix ? locations[0].slice(0, -prefix.length) : locations[0]); put('N15', prefix);
    put('AB24', firstLot[1]); put('AG24', firstLot[2]);
    if (lots.length > 1) put('AJ24', lots.length === locations.length ? lots.slice(1).map(l => compact(l.location) + compact(l.lot_number)).join('　') : REVIEW);
    put('X30', house && house[1] === prefix && house[2] === firstLot[1] && house[3] === firstLot[2] ? house[4] : REVIEW);
  } else {
    for (const cell of ['J15', 'AB24', 'X30']) put(cell, REVIEW);
    if (building.registry_location) put('AJ24', building.registry_location);
  }
  put('X15', building.display_address || '要確認（住居表示）');
  (Array.isArray(building.floor_areas) ? building.floor_areas.slice(0, 17) : []).forEach((item, index) => {
    if (item?.floor != null && item?.area != null) { put(`AY${23 + index}`, item.floor); put(`BA${23 + index}`, Number(item.area)); }
  });
  const share = Number(unit.land_right_denominator) > 0 && Number(unit.land_right_numerator) > 0 && Number(unit.land_right_numerator) <= Number(unit.land_right_denominator);
  lots.slice(0, 6).forEach((lot, index) => {
    const row = 42 + index * 2;
    if (index) { put(`F${row}`, lot.location); put(`U${row}`, lot.lot_number); }
    put(`Y${row}`, lot.land_category); put(`AB${row}`, lot.area == null ? '' : Number(lot.area));
    if (unit.land_right_type) put(`AG${row}`, unit.land_right_type);
    if (share) { put(`AL${row}`, Number(unit.land_right_denominator)); put(`AT${row}`, Number(unit.land_right_numerator)); }
  });
  if (unit.has_land_right === true) Object.assign(cells, { R54: '■', V54: '□' });
  else if (unit.has_land_right === false) Object.assign(cells, { R54: '□', V54: '■' });
  else Object.assign(cells, { R54: '□', V54: '□' });
  if (realCase.sale_price != null) put('AA70', Number(realCase.sale_price));
  if (realCase.earnest_money != null) put('AA72', Number(realCase.earnest_money));
  const handover = dateParts(realCase.handover_date);
  if (handover) Object.assign(cells, { O119: handover.era, R119: handover.year, V119: handover.month, Z119: handover.day });
  return cells;
}

async function sheetPathFor(zip, workbook, rels, sheetName) {
  const sheetMatch = workbook.match(new RegExp(`<sheet\\b[^>]*name="${sheetName}"[^>]*r:id="([^"]+)"`));
  if (!sheetMatch) throw new Error('TEMPLATE');
  const relMatch = rels.match(new RegExp(`<Relationship\\b[^>]*Id="${sheetMatch[1]}"[^>]*Target="([^"]+)"`));
  if (!relMatch) throw new Error('TEMPLATE');
  return relMatch[1].startsWith('/') ? relMatch[1].slice(1) : `xl/${relMatch[1].replace(/^\.\//, '')}`;
}

const ZONE_LETTERS = ['A', 'B', 'C', 'D'];
const toHalfWidth = value => String(value ?? '').replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0));
const zoneKey = value => toHalfWidth(value).replace(/\s+/g, '');
const NOT_APPLICABLE = new Set(['', 'なし', '該当なし', '無', '不明', '-', '－', 'ー'].map(zoneKey));
const isApplicable = value => value != null && !NOT_APPLICABLE.has(zoneKey(value));
const markerFor = letters => letters.map(l => `(${l})`).join('');
// building_coverage_ratio/floor_area_ratio/height_district/minimum_height_district/
// minimum_lot_area each have a fixed number of (value, marker) cell slots in the template
// (see zoning_excel_map.mjs) — unlike the checkbox items, which just concatenate letters
// into one marker cell and so have no real capacity limit. A rare 3-4 zone property can have
// more distinct values than slots; those are left for the agent to fill in by hand rather
// than silently dropped, noted in the BI166 confirmation sentence alongside the boundary note.
const FIELD_LABELS = { building_coverage_ratio: '建ぺい率', floor_area_ratio: '容積率', height_district: '高度地区', minimum_height_district: '最低限高度地区', minimum_lot_area: '敷地面積の最低限度' };

function zoneValue(zone, code) {
  const item = (zone.fields || []).find(f => f.code === code);
  return item && !item.needs_review ? item.value : null;
}

// Collapses per-zone values into groups (equal values across zones share one write and a
// combined "(A)(B)" marker; different values get their own write, each with a single letter).
function groupZones(zones, code) {
  const groups = [];
  zones.forEach((zone, index) => {
    const value = zoneValue(zone, code);
    if (!isApplicable(value)) return;
    const key = zoneKey(value);
    const existing = groups.find(g => g.key === key);
    if (existing) existing.letters.push(ZONE_LETTERS[index]);
    else groups.push({ key, value, letters: [ZONE_LETTERS[index]] });
  });
  return groups;
}

// Mirrors the recorded convention from a real filled example (see zoning_excel_map.mjs):
// check the matching box, and when there is more than one zone, write which zone(s) it
// covers into the marker cell right after that item's label. Unmatched zone-type/district
// names are left unfilled rather than guessed.
function planZoningChecklist(put, zones, code, table, multi) {
  for (const group of groupZones(zones, code)) {
    const key = Object.keys(table).find(name => zoneKey(name) === group.key);
    if (!key) continue;
    const cell = table[key];
    put(cell.box, '■');
    if (multi) put(cell.marker, markerFor(group.letters));
  }
}

function planHeightDistrict(put, zones, multi, overflow) {
  const groups = groupZones(zones, 'height_district');
  groups.slice(0, ZMAP.HEIGHT_DISTRICT_SLOTS.length).forEach((group, index) => {
    const slot = ZMAP.HEIGHT_DISTRICT_SLOTS[index];
    put(slot.box, '■'); put(slot.value, group.value);
    if (multi) put(slot.marker, markerFor(group.letters));
  });
  if (groups.length > ZMAP.HEIGHT_DISTRICT_SLOTS.length)
    overflow.push({ label: FIELD_LABELS.height_district, capacity: ZMAP.HEIGHT_DISTRICT_SLOTS.length, groups: groups.slice(ZMAP.HEIGHT_DISTRICT_SLOTS.length) });
  const minGroups = groupZones(zones, 'minimum_height_district');
  if (minGroups.length) {
    put(ZMAP.MIN_HEIGHT_DISTRICT.box, '■'); put(ZMAP.MIN_HEIGHT_DISTRICT.value, minGroups[0].value);
    if (multi) put(ZMAP.MIN_HEIGHT_DISTRICT.marker, markerFor(minGroups[0].letters));
    if (minGroups.length > 1) overflow.push({ label: FIELD_LABELS.minimum_height_district, capacity: 1, groups: minGroups.slice(1) });
  }
}

function planRatio(put, zones, code, slots, overflow) {
  const groups = groupZones(zones, code);
  groups.slice(0, slots.length).forEach((group, index) => {
    const [valueCell, markerCell] = slots[index];
    const number = Number(String(group.value).replace(/[^\d.]/g, ''));
    if (Number.isFinite(number)) put(valueCell, number);
    if (zones.length > 1) put(markerCell, markerFor(group.letters));
  });
  if (groups.length > slots.length) overflow.push({ label: FIELD_LABELS[code], capacity: slots.length, groups: groups.slice(slots.length) });
}

function planMinLotArea(put, zones, overflow) {
  const groups = groupZones(zones, 'minimum_lot_area');
  if (!groups.length) return;
  const number = Number(String(groups[0].value).replace(/[^\d.]/g, ''));
  if (Number.isFinite(number)) { put(ZMAP.MIN_LOT_AREA.yes, '■'); put(ZMAP.MIN_LOT_AREA.no, '□'); put(ZMAP.MIN_LOT_AREA.value, number); }
  if (groups.length > 1) overflow.push({ label: FIELD_LABELS.minimum_lot_area, capacity: 1, groups: groups.slice(1) });
}

// "建ぺい率は3件までしか自動反映できないため、(D)60%は手入力してください。" per overflowing field.
function overflowNote(overflow) {
  return overflow.map(({ label, capacity, groups }) =>
    `${label}は${capacity}件までしか自動反映できないため、${groups.map(g => `${markerFor(g.letters)}${g.value}`).join('、')}は手入力してください。`
  ).join(' ');
}

// Only touches the 重説 sheet's zoning section; everything else in the template is untouched.
// zones is the same [{zone_label, needs_review, fields:[{code,value,needs_review}]}] shape the
// case screen's zoning card reads (see web_zoning.zone_view / netlify/functions/zoning.mjs).
export function planZoning(zones) {
  const cells = {};
  const put = (cell, value) => { cells[cell] = value; };
  if (!Array.isArray(zones) || !zones.length) return cells;
  const multi = zones.length > 1;
  const overflow = [];
  planZoningChecklist(put, zones, 'zoning_type', ZMAP.ZONING_TYPES, multi);
  planZoningChecklist(put, zones, 'fire_zone', { '防火地域': ZMAP.DISTRICT_TYPES['防火地域'] }, multi);
  planZoningChecklist(put, zones, 'semi_fire_zone', { '準防火地域': ZMAP.DISTRICT_TYPES['準防火地域'] }, multi);
  planZoningChecklist(put, zones, 'special_use_district', { '特別用途地区': ZMAP.DISTRICT_TYPES['特別用途地区'] }, multi);
  planZoningChecklist(put, zones, 'height_use_district', { '高度利用地区': ZMAP.DISTRICT_TYPES['高度利用地区'] }, multi);
  planZoningChecklist(put, zones, 'district_plan', { '地区計画区域': ZMAP.DISTRICT_TYPES['地区計画区域'] }, multi);
  planRatio(put, zones, 'building_coverage_ratio', ZMAP.RATIO_SLOTS.building_coverage_ratio, overflow);
  planRatio(put, zones, 'floor_area_ratio', ZMAP.RATIO_SLOTS.floor_area_ratio, overflow);
  planHeightDistrict(put, zones, multi, overflow);
  planMinLotArea(put, zones, overflow);
  // The template's own BI166 sentence needs the road side/distance a human determines from
  // the site; multiple zones just means the boundary note applies and must be checked. Any
  // field that ran out of slots (see overflowNote) gets its own sentence appended here too,
  // since this is the only free-text confirmation cell available in the 重説 zoning section.
  if (multi) {
    const note = overflowNote(overflow);
    put(ZMAP.BI166, '【要確認】用途地域が複数のため、本物件の道路との位置関係を確認し、この文言を修正してください。' + (note ? ' ' + note : ''));
  }
  return cells;
}

export async function fill(template, unit, building, realCase, zones = []) {
  const zip = await JSZip.loadAsync(template, { createFolders: false });
  const workbook = await zip.file('xl/workbook.xml').async('string');
  const rels = await zip.file('xl/_rels/workbook.xml.rels').async('string');
  const written = [];
  const sheetPath = await sheetPathFor(zip, workbook, rels, '基本入力');
  let xml = await zip.file(sheetPath).async('string');
  for (const [coordinate, value] of Object.entries(plan(unit, building, realCase))) xml = patchCell(xml, coordinate, value, written);
  zip.file(sheetPath, xml, { createFolders: false });
  const zoningCells = planZoning(zones);
  if (Object.keys(zoningCells).length) {
    const disclosurePath = await sheetPathFor(zip, workbook, rels, '重説');
    let disclosureXml = await zip.file(disclosurePath).async('string');
    for (const [coordinate, value] of Object.entries(zoningCells)) disclosureXml = patchCell(disclosureXml, coordinate, value, written);
    zip.file(disclosurePath, disclosureXml, { createFolders: false });
  }
  zip.file('xl/workbook.xml', workbook.replace(/<calcPr\b([^>]*)\/>/, (_m, attrs) => `<calcPr${attrs.replace(/\s+(fullCalcOnLoad|forceFullCalc|calcMode)="[^"]*"/g, '')} fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/>`), { createFolders: false });
  const bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' });
  return { bytes, written };
}

async function generate(caseId) {
  let realCase = null;
  let unitId = caseId.startsWith('unit-') ? caseId.slice(5) : '';
  if (unitId && !UUID.test(unitId)) throw new Failure(404, '案件・住戸が見つかりません。');
  if (!unitId) {
    if (!UUID.test(caseId)) throw new Failure(404, '案件・住戸が見つかりません。');
    realCase = (await db(`cases?case_id=eq.${caseId}&select=*&limit=1`))[0];
    unitId = realCase?.unit_id;
  }
  if (!unitId) throw new Failure(404, '案件・住戸が見つかりません。');
  const units = await db(`units?unit_id=eq.${unitId}&select=*&limit=1`);
  const unit = units[0];
  if (!unit) throw new Failure(404, '案件・住戸が見つかりません。');
  const building = (await db(`buildings?building_id=eq.${unit.building_id}&select=*&limit=1`))[0] || {};
  // Includes building-level management_rules documents (unit_id is null there), matching review.mjs.
  const documents = await db(`documents?or=(unit_id.eq.${unitId},and(building_id.eq.${unit.building_id},document_type.eq.management_rules))&select=document_id`);
  const ids = documents.map(d => d.document_id);
  const open = ids.length ? await db(`value_diffs?document_id=in.(${ids.join(',')})&review_status=eq.unreviewed&select=diff_id`) : [];
  if (open.length) throw new Failure(409, `あと${open.length}件確認すると契約書を生成できます。`);
  if (!realCase) realCase = (await db(`cases?unit_id=eq.${unitId}&select=*&order=updated_at.desc&limit=1`))[0] || {};
  // For now only 謄本 is read and the zoning card is hidden, so zoning already on file is not written either.
  const zoningDocs = READ_ZONING && unit.building_id ? await db(`documents?document_type=eq.zoning&building_id=eq.${unit.building_id}&select=document_id`) : [];
  let zones = [];
  if (zoningDocs.length) {
    const versions = await db(`document_versions?document_id=eq.${zoningDocs[0].document_id}&select=document_version_id&order=version_no.desc&limit=1`);
    if (versions.length) {
      const values = await db(`extracted_values?document_version_id=eq.${versions[0].document_version_id}&field_code=eq.zoning_info&select=value`);
      if (values.length) zones = values[0].value || [];
    }
  }
  return fill(templateBytes(), unit, building, realCase, zones);
}

export default async (request) => {
  try {
    await authenticate(request);
    if (request.method !== 'POST') throw new Failure(404, '操作がありません。');
    const text = await request.text();
    if (text.length > 2000) throw new Failure(413, '入力が大きすぎます。');
    const { bytes } = await generate(String(JSON.parse(text || '{}').case_id || ''));
    return new Response(bytes, { headers: { 'Content-Type': 'application/vnd.ms-excel.sheet.macroEnabled.12', 'Content-Disposition': "attachment; filename*=UTF-8''keiyaku-max.xlsm", 'Cache-Control': 'no-store' } });
  } catch (error) {
    if (error instanceof Failure) return reply(error.status, { error: error.message });
    if (error instanceof SyntaxError) return reply(400, { error: '入力内容を確認してください。' });
    console.error('generate failure', error instanceof Error ? error.message.slice(0, 40) : 'unknown');
    return reply(500, { error: '契約書を生成できませんでした。管理者へ連絡してください。' });
  }
};
