import JSZip from "npm:jszip@3.10.1";

const AUTH_URL = "https://afdtohxuzuwlqmjbrpar.supabase.co";
const AUTH_KEY = "sb_publishable_4I1EXj6iMy3J-_nxBrOasw_1CRPXyw4";
const cors = {
  "Access-Control-Allow-Origin": "https://keiyaku-max.netlify.app",
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Vary": "Origin",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

async function authenticate(req: Request) {
  const authorization = req.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) throw new Error("AUTH");
  const response = await fetch(`${AUTH_URL}/auth/v1/user`, { headers: { apikey: AUTH_KEY, authorization } });
  if (!response.ok) throw new Error("AUTH");
  return await response.json();
}

async function table(path: string) {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("CONFIG");
  const response = await fetch(`${url}/rest/v1/${path}`, { headers: { apikey: key, authorization: `Bearer ${key}` } });
  if (!response.ok) throw new Error(`DB:${response.status}`);
  return await response.json();
}

async function getState() {
  const [units, buildings, cases, documents, diffs] = await Promise.all([
    table("units?select=*&order=updated_at.desc"),
    table("buildings?select=*&order=updated_at.desc"),
    table("cases?select=*&order=updated_at.desc"),
    table("documents?select=document_id,unit_id"),
    table("value_diffs?select=diff_id,field_code,review_status,document_id&review_status=eq.unreviewed"),
  ]);
  const buildingById = new Map(buildings.map((item: any) => [item.building_id, item]));
  const documentUnit = new Map(documents.map((item: any) => [item.document_id, item.unit_id]));
  const casesByUnit = new Map<string, any[]>();
  for (const item of cases) casesByUnit.set(item.unit_id, [...(casesByUnit.get(item.unit_id) || []), item]);
  return {
    mode: "live",
    cases: units.map((unit: any) => {
      const building: any = buildingById.get(unit.building_id) || {};
      const realCase = (casesByUnit.get(unit.unit_id) || [])[0];
      return {
        id: realCase?.case_id || `unit-${unit.unit_id}`,
        unit_id: unit.unit_id,
        building_name: building.building_name || "物件名未取得",
        unit_name: unit.unit_name || "号室未取得",
        address: building.display_address || building.registry_location || "所在地未取得",
        owner: unit.current_owner_name || "所有者未取得",
        area: unit.registered_area,
        updated_at: realCase?.updated_at || unit.updated_at,
        unresolved: diffs.filter((item: any) => documentUnit.get(item.document_id) === unit.unit_id).length,
        fields: [
          ["建物名", building.building_name], ["号室", unit.unit_name], ["登記所在", building.registry_location],
          ["家屋番号", unit.house_number], ["所有者", unit.current_owner_name], ["登記面積", unit.registered_area],
          ["管理費", unit.management_fee], ["修繕積立金", unit.repair_reserve_fee],
        ].map(([label, value]) => ({ label, value })),
      };
    }),
  };
}

function escapeXml(value: unknown) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function patchCell(xml: string, coordinate: string, value: unknown) {
  if (value === null || value === undefined || value === "") return xml;
  const pattern = new RegExp(`<c\\b(?=[^>]*\\br="${coordinate}")[^>]*?(?:\\/>|>[\\s\\S]*?<\\/c>)`);
  const match = xml.match(pattern);
  if (!match) throw new Error(`CELL:${coordinate}`);
  let attrs = match[0].match(/^<c\b([^>]*?)(?:\/?>)/)?.[1] || ` r="${coordinate}"`;
  attrs = attrs.replace(/\s+t="[^"]*"/g, "");
  let body: string;
  if (typeof value === "number") body = `<v>${value}</v>`;
  else {
    attrs += ' t="inlineStr"';
    body = `<is><t xml:space="preserve">${escapeXml(value)}</t></is>`;
  }
  return xml.replace(pattern, `<c${attrs}>${body}</c>`);
}

function dateParts(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00+09:00`);
  if (Number.isNaN(date.valueOf())) return null;
  const year = date.getFullYear();
  return { era: year >= 2019 ? "令和" : "平成", year: year >= 2019 ? year - 2018 : year - 1988, month: date.getMonth() + 1, day: date.getDate() };
}

async function generate(caseId: string) {
  let realCase: any = null;
  let unitId = caseId.startsWith("unit-") ? caseId.slice(5) : "";
  if (!unitId) {
    const rows = await table(`cases?case_id=eq.${encodeURIComponent(caseId)}&select=*&limit=1`);
    realCase = rows[0]; unitId = realCase?.unit_id;
  }
  if (!unitId) throw new Error("CASE");
  const [units, documents] = await Promise.all([
    table(`units?unit_id=eq.${encodeURIComponent(unitId)}&select=*&limit=1`),
    table(`documents?unit_id=eq.${encodeURIComponent(unitId)}&select=document_id`),
  ]);
  const documentIds = documents.map((item: any) => item.document_id);
  const diffs = documentIds.length ? await table(`value_diffs?document_id=in.(${documentIds.join(",")})&review_status=eq.unreviewed&select=diff_id`) : [];
  if (diffs.length) throw new Error("REVIEW");
  const unit = units[0];
  if (!unit) throw new Error("CASE");
  const building = (await table(`buildings?building_id=eq.${encodeURIComponent(unit.building_id)}&select=*&limit=1`))[0] || {};
  if (!realCase) realCase = (await table(`cases?unit_id=eq.${encodeURIComponent(unitId)}&select=*&order=updated_at.desc&limit=1`))[0] || {};
  const encoded = await Deno.readTextFile(new URL("./contract-template.b64", import.meta.url));
  const template = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
  const zip = await JSZip.loadAsync(template);
  const workbook = await zip.file("xl/workbook.xml")!.async("string");
  const rels = await zip.file("xl/_rels/workbook.xml.rels")!.async("string");
  const sheetMatch = workbook.match(/<sheet\b[^>]*name="基本入力"[^>]*r:id="([^"]+)"/);
  if (!sheetMatch) throw new Error("TEMPLATE");
  const relMatch = rels.match(new RegExp(`<Relationship\\b[^>]*Id="${sheetMatch[1]}"[^>]*Target="([^"]+)"`));
  if (!relMatch) throw new Error("TEMPLATE");
  const sheetPath = relMatch[1].startsWith("/") ? relMatch[1].slice(1) : `xl/${relMatch[1].replace(/^\.\//, "")}`;
  let xml = await zip.file(sheetPath)!.async("string");
  const values: Record<string, unknown> = {
    AB13: building.building_name, AS13: unit.unit_name, J28: building.building_structure,
    X30: unit.house_number, AF30: building.building_name, J32: unit.unit_type,
    Q32: unit.unit_structure, AH32: unit.unit_floor, J34: unit.registered_area,
    F37: unit.current_owner_name, AB37: unit.current_owner_address,
    R54: unit.has_land_right === false ? "□" : "■", V54: unit.has_land_right === false ? "■" : "□",
    AA70: realCase.sale_price, AA72: realCase.earnest_money,
  };
  const built = dateParts(unit.built_date);
  if (built) Object.assign(values, { U34: built.era, X34: built.year, AB34: built.month, AF34: built.day });
  const handover = dateParts(realCase.handover_date);
  if (handover) Object.assign(values, { O119: handover.era, R119: handover.year, V119: handover.month, Z119: handover.day });
  for (const [coordinate, value] of Object.entries(values)) xml = patchCell(xml, coordinate, value);
  const lots = Array.isArray(building.land_lots) ? building.land_lots.slice(0, 6) : [];
  lots.forEach((lot: any, index: number) => {
    const row = 42 + index * 2;
    const entries: Record<string, unknown> = {
      [`F${row}`]: lot.location || lot["所在"], [`U${row}`]: lot.lot_number || lot["地番"],
      [`Y${row}`]: lot.land_category || lot["地目"], [`AB${row}`]: lot.area || lot["地積"],
      [`AG${row}`]: lot.right_type || lot["権利の種類"], [`AL${row}`]: lot.denominator || lot["持分_分母"],
      [`AT${row}`]: lot.numerator || lot["持分_分子"],
    };
    for (const [coordinate, value] of Object.entries(entries)) xml = patchCell(xml, coordinate, value);
  });
  zip.file(sheetPath, xml);
  const calc = workbook.replace(/<calcPr\b([^>]*)\/>/, (_m, attrs) => `<calcPr${attrs.replace(/\s+(fullCalcOnLoad|forceFullCalc|calcMode)="[^"]*"/g, "")} fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/>`);
  zip.file("xl/workbook.xml", calc);
  return await zip.generateAsync({ type: "uint8array", compression: "DEFLATE" });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  try {
    await authenticate(req);
    const action = new URL(req.url).searchParams.get("action") || "state";
    if (req.method === "GET" && action === "state") return json(await getState());
    if (req.method === "POST" && action === "generate") {
      const body = await req.json();
      const bytes = await generate(String(body.case_id || ""));
      return new Response(bytes, { headers: { ...cors, "Content-Type": "application/vnd.ms-excel.sheet.macroEnabled.12", "Content-Disposition": "attachment; filename*=UTF-8''keiyaku-max.xlsm", "Cache-Control": "no-store" } });
    }
    return json({ error: "操作がありません。" }, 404);
  } catch (error) {
    const code = error instanceof Error ? error.message : "ERROR";
    if (code === "AUTH") return json({ error: "ログインし直してください。" }, 401);
    if (code === "REVIEW") return json({ error: "未確認の差分があります。先に確認してください。" }, 409);
    if (code === "CASE") return json({ error: "案件・住戸が見つかりません。" }, 404);
    console.error(code);
    return json({ error: "契約書を生成できませんでした。管理者へ連絡してください。" }, 500);
  }
});
