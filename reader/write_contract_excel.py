"""既存xlsmの許可セルだけをZIP/XMLパッチし、他のパーツはバイト一致で保持する。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

from extract_registry import SCHEMA, save_json, validate_schema

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TAG = "{" + NS["s"] + "}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DIRECT = {"building.location": "J24", "building.name": "J26", "building.structure": "J28",
          "building.total_floor_area": "AF28", "unit.name": "AF30", "unit.type": "J32",
          "unit.structure": "Q32", "unit.registered_area": "J34", "owner.name": "F37",
          "owner.address": "AB37"}


def sheet_part(z):
    root = ET.fromstring(z.read("xl/workbook.xml"))
    sheet = next((s for s in root.find("s:sheets", NS) if s.get("name") == "基本入力"), None)
    if sheet is None:
        raise ValueError("基本入力シートがありません")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(x.get("Target") for x in rels if x.get("Id") == sheet.get(REL))
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)


def string_value(cell, strings):
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.findall("s:is/s:t", NS))
    value = cell.findtext("s:v", default=None, namespaces=NS)
    if cell.get("t") == "s" and value is not None:
        return strings[int(value)]
    if value is None:
        return None
    if cell.get("t") in ("str", "e"):
        return value
    return Decimal(value)


def shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    return ["".join(t.text or "" for t in list(x.findall("s:t", NS)) +
                    list(x.findall("s:r/s:t", NS)))
            for x in ET.fromstring(z.read("xl/sharedStrings.xml"))]


def lookup(data, path):
    node = data
    for key in path.split("."):
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))


def build_writes(data):
    from normalize_registry import schema_projection
    data = schema_projection(data)
    validate_schema({k: data[k] for k in SCHEMA["properties"]}, SCHEMA)
    writes, skipped = [], []

    def skip(path, reason, cell=None):
        skipped.append({"field": path, "cell": cell, "reason": reason})

    def put(path, cell, converted=None):
        field = lookup(data, path)
        if field["value"] is None:
            skip(path, "取得不能(null)のため既存セルを保持", cell)
        elif not field["sources"]:
            skip(path, "根拠なし", cell)
        else:
            value = field["value"] if converted is None else converted
            if type(value) in (float, int) and value < 0:
                skip(path, "負の面積/数値は転記不可", cell)
                return
            writes.append({"field": path, "cell": cell, "value": value, "sources": field["sources"]})

    for path, cell in DIRECT.items():
        put(path, cell)
    # The template composes a house number from three areas including formulas.
    # Writing the full number to a suffix cell would duplicate its prefix.
    skip("unit.house_number", "家屋番号はJ30/R30の数式を含む複合欄。JSON保持・自動転記見送り", "J30/R30/X30")

    lot = data["building"]["lot_number"]["value"]
    match = re.fullmatch(r"(\d+)(?:番地の?|番|[-−ー])(\d+)", compact(lot)) if lot else None
    if match:
        put("building.lot_number", "AB24", match[1])
        put("building.lot_number", "AG24", match[2])
    else:
        skip("building.lot_number", "番地・枝番に安全に分割できないためJSON保持", "AB24/AG24")

    floor = data["unit"]["floor"]["value"]
    match = re.fullmatch(r"(地下)?(\d+)階(?:部分)?", compact(floor)) if floor else None
    if match:
        put("unit.floor", "AH32", ("地下" if match[1] else "") + match[2])
    else:
        skip("unit.floor", "階を確定できないため既存セルを保持", "AH32")

    date = data["unit"]["built_date"]["value"]
    match = re.fullmatch(r"(明治|大正|昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日(?:新築)?", compact(date)) if date else None
    if match:
        year = 1 if match[2] == "元" else int(match[2])
        import datetime
        starts = {"明治": (1868, 9, 8), "大正": (1912, 7, 30), "昭和": (1926, 12, 25),
                  "平成": (1989, 1, 8), "令和": (2019, 5, 1)}
        eras = list(starts)
        try:
            actual = datetime.date(starts[match[1]][0] + year - 1, int(match[3]), int(match[4]))
            pos = eras.index(match[1])
            if year < 1 or actual < datetime.date(*starts[match[1]]) or (pos < 4 and actual >= datetime.date(*starts[eras[pos + 1]])):
                raise ValueError()
        except ValueError:
            skip("unit.built_date", "不正な和暦日付", "U34/X34/AB34/AF34")
        else:
            for cell, v in zip(("U34", "X34", "AB34", "AF34"), (match[1], year, int(match[3]), int(match[4]))):
                put("unit.built_date", cell, v)
    else:
        skip("unit.built_date", "年月日を確定できないため既存セルを保持", "U34/X34/AB34/AF34")

    for i, floor_area in enumerate(data["building"]["floor_areas"]):
        if i >= 17:
            skip(f"building.floor_areas.{i}", "延床計算用欄17行を超過。JSON保持")
        elif floor_area["floor"]["value"] is not None and floor_area["area"]["value"] is not None:
            put(f"building.floor_areas.{i}.floor", f"AY{23+i}")
            put(f"building.floor_areas.{i}.area", f"BA{23+i}")
        else:
            skip(f"building.floor_areas.{i}", "階と面積の対応が未確定")

    for i, land in enumerate(data["lands"]):
        if i >= 6:
            skip(f"lands.{i}", "6筆の入力上限を超過。JSONには全筆保持")
            continue
        row = 42 + 2*i
        for key, col in {"location": "F", "lot_number": "U", "category": "Y", "area": "AB", "right_type": "AG"}.items():
            put(f"lands.{i}.{key}", f"{col}{row}")
        share = land["right_share"]["value"]
        match = re.fullmatch(r"([\d,]+)分の([\d,]+)", compact(share)) if share else None
        if match and 0 < int(match[2].replace(",", "")) <= int(match[1].replace(",", "")):
            put(f"lands.{i}.right_share", f"AL{row}", int(match[1].replace(",", "")))
            put(f"lands.{i}.right_share", f"AT{row}", int(match[2].replace(",", "")))
        else:
            skip(f"lands.{i}.right_share", "割合を確定できないため既存セルを保持", f"AL{row}/AT{row}")
    exists = data["land_right"]["exists"]["value"]
    if exists is not None:
        put("land_right.exists", "R54", "■" if exists else "□")
        put("land_right.exists", "V54", "□" if exists else "■")
    else:
        skip("land_right.exists", "有無不明のため既存の選択を保持", "R54/V54")
    for key in ("type", "share"):
        if data["land_right"][key]["value"] is not None:
            skip("land_right." + key, "独立入力欄なし。土地符号で対応確認できたlandsの値のみ土地欄に転記")
    return writes, skipped


def cell_pattern(ref):
    return re.compile(r'<c\b(?=[^>]*\br="' + re.escape(ref) + r'")[^>]*?(?:/>|>.*?</c>)', re.DOTALL)


def patch_cell(xml, write):
    pattern = cell_pattern(write["cell"])
    found = list(pattern.finditer(xml))
    if len(found) != 1:
        raise ValueError(f"既存セルが一意に存在しません: {write['cell']}")
    original = found[0].group()
    opening = re.match(r"<c\b([^>]*?)/?>", original).group(1)
    opening = re.sub(r'\s+t="[^"]*"', "", opening)
    value = write["value"]
    if type(value) in (int, float):
        replacement = f'<c{opening} t="n"><v>{value}</v></c>'
    else:
        if len(value) > 32767 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
            raise ValueError(f"Excelへ保存できない文字列: {write['cell']}")
        # Inline strings never become formulas, including strings beginning with '='.
        safe = re.sub(r"_x([0-9a-fA-F]{4})_", r"_x005F_x\1_", value)
        replacement = f'<c{opening} t="inlineStr"><is><t xml:space="preserve">{escape(safe)}</t></is></c>'
    return xml[:found[0].start()] + replacement + xml[found[0].end():]


def verify(source, output, writes):
    with ZipFile(source) as original, ZipFile(output) as result:
        part = sheet_part(original)
        if original.namelist() != result.namelist():
            raise AssertionError("ZIP構成が変化しました")
        changed = [name for name in original.namelist() if original.read(name) != result.read(name)]
        if any(name != part for name in changed):
            raise AssertionError(f"対象シート以外が変化しました: {changed}")
        before, after = original.read(part).decode("utf-8"), result.read(part).decode("utf-8")
        before_masked, after_masked = before, after
        strings = shared_strings(result)
        cells = {c.get("r"): c for c in ET.fromstring(after).findall("s:sheetData/s:row/s:c", NS)}
        for item in writes:
            ref = item["cell"]
            value = string_value(cells[ref], strings)
            expected = item["value"]
            if isinstance(value, str):
                value = re.sub(r"_x005F_(?=x[0-9a-fA-F]{4}_)", "_", value)
            if type(expected) in (int, float):
                expected = Decimal(str(expected))
            if value != expected:
                raise AssertionError(f"再読込不一致: {ref}: {value!r} != {expected!r}")
            item["readback_value"] = item["value"]
            pattern = cell_pattern(ref)
            b = ET.fromstring('<root xmlns="' + NS["s"] + '">' + pattern.search(before).group() + '</root>')[0]
            a = cells[ref]
            if {k: v for k, v in b.attrib.items() if k != "t"} != {k: v for k, v in a.attrib.items() if k != "t"}:
                raise AssertionError(f"セル書式/属性が変化しました: {ref}")
            if b.find("s:f", NS) is not None or a.find("s:f", NS) is not None:
                raise AssertionError(f"数式セルが変更されています: {ref}")
            before_masked = pattern.sub("<unchanged_cell/>", before_masked)
            after_masked = pattern.sub("<unchanged_cell/>", after_masked)
        if before_masked != after_masked:
            raise AssertionError("許可したセル以外のシートXMLが変化しました")
        vba = [n for n in original.namelist() if "vbaproject" in n.lower()]
        return {"passed": True, "changed_parts": changed, "written_cell_count": len(writes),
                "other_parts_byte_identical": True, "formula_cells_unchanged": True,
                "styles_and_merges_unchanged": True,
                "vba_sha256": {n: hashlib.sha256(result.read(n)).hexdigest() for n in vba}}


def write_contract_excel(template, data, output="output/契約書_謄本入力済.xlsm"):
    from normalize_registry import schema_projection
    data = schema_projection(data)
    template, output = Path(template).resolve(), Path(output).resolve()
    if template == output:
        raise ValueError("原本への上書きは禁止です")
    if template.suffix.lower() != ".xlsm" or output.suffix.lower() != ".xlsm":
        raise ValueError("入出力は.xlsmを指定してください")
    if output.exists():
        raise FileExistsError(f"既存出力は上書きしません。別の出力フォルダを指定してください: {output}")
    original_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    planned, skipped = build_writes(data)
    writes = []
    with ZipFile(template) as z:
        part = sheet_part(z)
        xml = z.read(part).decode("utf-8")
        root = ET.fromstring(xml)
        cells = {c.get("r"): c for c in root.findall("s:sheetData/s:row/s:c", NS)}
        strings = shared_strings(z)
        # Fail closed on a different template layout instead of writing by coordinates alone.
        labels = {"B24": "一棟の建物の表示", "B30": "専有部分の建物の表示",
                  "F34": "登記簿面積", "AB37": "登記名義人住所", "B40": "土地"}
        # AB37 is itself an editable field, so only validate it on the original template.
        for ref, expected in labels.items():
            if expected not in str(string_value(cells[ref], strings)):
                raise ValueError(f"対象ひな形の見出し/欄が一致しません: {ref}")
        merges = root.findall("s:mergeCells/s:mergeCell", NS)
        from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple
        for item in planned:
            ref = item["cell"]
            row, col = coordinate_to_tuple(ref)
            cell = cells.get(ref)
            reason = None
            if not 21 <= row <= 54:
                reason = "対象行外"
            elif cell is None:
                reason = "既存セルなし"
            elif cell.find("s:f", NS) is not None:
                reason = "既存数式を保持（取得値はJSONに保存）"
            else:
                for merge in merges:
                    left, top, right, bottom = range_boundaries(merge.get("ref"))
                    if left <= col <= right and top <= row <= bottom and (row, col) != (top, left):
                        reason = "結合セルの先頭ではない"
                        break
            if reason:
                skipped.append({**item, "reason": reason})
            else:
                item["previous_value"] = str(string_value(cell, strings)) if string_value(cell, strings) is not None else None
                xml = patch_cell(xml, item)
                writes.append(item)
        output.parent.mkdir(parents=True, exist_ok=True)
        import uuid
        temp = output.parent / (".pending_" + uuid.uuid4().hex + ".xlsm")
        try:
            with ZipFile(temp, "x") as result:
                result.comment = z.comment
                for member in z.infolist():
                    result.writestr(copy.copy(member), xml.encode("utf-8") if member.filename == part else z.read(member.filename))
            checks = verify(template, temp, writes)
            if hashlib.sha256(template.read_bytes()).hexdigest() != original_hash:
                raise AssertionError("原本が実行中に変化しました")
            # Windows rename refuses overwrites and also works on shares/USB filesystems.
            if os.name == "nt":
                os.rename(temp, output)
            else:
                os.link(temp, output)
        finally:
            temp.unlink(missing_ok=True)
    report = {"template": str(template), "output": str(output), "source_sha256": original_hash,
              "written_cells": writes, "skipped": skipped, "verification": checks,
              "note": "数式と既存キャッシュは保持。Excelを開いた時の再計算はExcelの設定に従います。"}
    save_json(output.parent / "verification.json", report)
    for item in writes:
        print(f"基本入力!{item['cell']} = {json.dumps(item['readback_value'], ensure_ascii=False)}")
    print(f"検証OK: {len(writes)}セル。数式・VBA・書式・結合・他シートは変更なし。")
    return report
