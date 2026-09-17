// Contract generation from confirmed DB values into the production XLSM template.
// Ported from supabase/functions/keiyaku-api generate(); formula cells are never overwritten.
import fs from 'node:fs';
import path from 'node:path';
import JSZip from 'jszip';
import { Failure, UUID, authenticate, db, reply } from '../lib/common.mjs';

const TEMPLATE = 'supabase/functions/keiyaku-api/contract-template.xlsm';

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

export async function fill(template, unit, building, realCase) {
  const zip = await JSZip.loadAsync(template, { createFolders: false });
  const workbook = await zip.file('xl/workbook.xml').async('string');
  const rels = await zip.file('xl/_rels/workbook.xml.rels').async('string');
  const sheetMatch = workbook.match(/<sheet\b[^>]*name="基本入力"[^>]*r:id="([^"]+)"/);
  if (!sheetMatch) throw new Error('TEMPLATE');
  const relMatch = rels.match(new RegExp(`<Relationship\\b[^>]*Id="${sheetMatch[1]}"[^>]*Target="([^"]+)"`));
  if (!relMatch) throw new Error('TEMPLATE');
  const sheetPath = relMatch[1].startsWith('/') ? relMatch[1].slice(1) : `xl/${relMatch[1].replace(/^\.\//, '')}`;
  let xml = await zip.file(sheetPath).async('string');
  const written = [];
  for (const [coordinate, value] of Object.entries(plan(unit, building, realCase))) xml = patchCell(xml, coordinate, value, written);
  zip.file(sheetPath, xml, { createFolders: false });
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
  const [units, documents] = await Promise.all([
    db(`units?unit_id=eq.${unitId}&select=*&limit=1`),
    db(`documents?unit_id=eq.${unitId}&select=document_id`),
  ]);
  const ids = documents.map(d => d.document_id);
  const open = ids.length ? await db(`value_diffs?document_id=in.(${ids.join(',')})&review_status=eq.unreviewed&select=diff_id`) : [];
  if (open.length) throw new Failure(409, `あと${open.length}件確認すると契約書を生成できます。`);
  const unit = units[0];
  if (!unit) throw new Failure(404, '案件・住戸が見つかりません。');
  const building = (await db(`buildings?building_id=eq.${unit.building_id}&select=*&limit=1`))[0] || {};
  if (!realCase) realCase = (await db(`cases?unit_id=eq.${unitId}&select=*&order=updated_at.desc&limit=1`))[0] || {};
  return fill(templateBytes(), unit, building, realCase);
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
