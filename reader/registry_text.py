"""登記情報提供サービスの全部事項PDFを、文字の座標から罫線表として組み立てる。AIは使わない。

pypdfのlayout抽出は隣り合う行を1行に混ぜることがあるため、文字の高さ位置で行を作り直す。
下線（抹消・変更された事項）は、文字の直下にある細い横線として検出する。
"""
import collections
import re
import unicodedata
from pathlib import Path

RULE_CHARS = re.compile(r'[┃┏┓┗┛┠┨├┤━─┯┷┬┴┼┳┻│┝┥┿]')


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def is_service_pdf(path):
    """登記情報提供サービスの書式（専用フォントと罫線文字）だけを機械読み取りの対象にする。"""
    import pdfplumber
    try:
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return False
            chars = pdf.pages[0].chars
            return any('TOUKI' in (c.get('fontname') or '') for c in chars) and any(c['text'] == '┃' for c in chars)
    except Exception:
        return False


def _underlines(page):
    """Short horizontal rules drawn just under characters, bucketed by their height position."""
    buckets = collections.defaultdict(list)
    for line in page.lines:
        if abs(line['top'] - line['bottom']) < 1.5 and line['x1'] - line['x0'] < 40:
            buckets[round(line['top'])].append((line['x0'], line['x1']))
    return buckets


def _underlined(char, buckets):
    for y in range(round(char['bottom']) - 1, round(char['bottom']) + 4):
        for x0, x1 in buckets.get(y, ()):
            if x0 <= char['x0'] + 1.5 and x1 >= char['x1'] - 1.5:
                return True
    return False


# The registry font prints "余白" (an intentionally blank column) with private-use glyphs.
BLANK_MARKS = ('\ue042\ue043\ue044', '\ue045\ue046\ue047\ue048')
# Private-use glyphs other than the blank marks and the (あ)(い)… collateral-list symbols are 外字
# (a kanji with no standard code point) inside a name or place and cannot be transcribed.
GAIJI = re.compile(r'[\ue000-\ue041\ue049-\ue177\ue1b0-\uf8ff]')


def page_lines(page):
    """[(text, flags)] per visual row; flags[i] is True when text[i] is underlined."""
    buckets = _underlines(page)
    rows = []
    for char in sorted(page.chars, key=lambda c: (c['top'], c['x0'])):
        if rows and abs(rows[-1][0] - char['top']) < 2:
            rows[-1][1].append(char)
        else:
            rows.append([char['top'], [char]])
    lines = []
    for _, chars in rows:
        chars.sort(key=lambda c: c['x0'])
        text = ''.join(c['text'] for c in chars)
        for mark in BLANK_MARKS:
            text = text.replace(mark, '　' * len(mark))
        flags = [_underlined(c, buckets) for c in chars]
        if text.strip():
            lines.append((text, flags))
    return lines


# Registries moved from paper keep old positional kanji numerals ("弐七番地壱九", "昭和五四年弐月弐〇日").
KANJI_DIGITS = str.maketrans('〇一二三四五六七八九壱弐参', '0123456789123')
KANJI_RUN = '[〇一二三四五六七八九壱弐参]+'
KANJI_NUMBER = re.compile(rf'{KANJI_RUN}(?=番|号|年|月|日|階|の|分|$)|(?<=[番の第地])' + KANJI_RUN)


def old_numerals(text):
    """True for a registry printed with kanji-digit dates or lot numbers ("昭和五四年", "弐七番地")."""
    return bool(re.search(rf'(?:昭和|平成){KANJI_RUN}年|{KANJI_RUN}番地?[壱弐参]', text))


def arabic(text):
    """Kanji digits in number positions to arabic, one character for one (flags stay aligned).

    Names are printed with a space between characters ("山　田　一　郎"), so a lone kanji digit is
    never converted; only a room name made entirely of digits is ("建物の名称│弐〇弐").
    """
    text = KANJI_NUMBER.sub(lambda m: m[0].translate(KANJI_DIGITS), text)
    return re.sub(rf'(建物の名称[　 ]*│[　 ]*)({KANJI_RUN})(?=[　 ]*[│┃])', lambda m: m[1] + m[2].translate(KANJI_DIGITS), text)


def read_pages(path):
    """Pages in the shape extract_registry.prepare_pdf returns, plus underline flags per row."""
    import pdfplumber
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, 1):
            lines = page_lines(page)
            pages.append({'page': index, 'mode': 'text', 'text': '\n'.join(t for t, _ in lines), 'lines': lines})
    if any(old_numerals(p['text']) for p in pages):
        for p in pages:
            p['lines'] = [(arabic(t), f) for t, f in p['lines']]
            p['text'] = '\n'.join(t for t, _ in p['lines'])
            p['old_numerals'] = True
    return pages


class Cell:
    """One table cell across the rows of a record: fragments keep their page and underline flags."""

    def __init__(self):
        self.fragments = []  # (page, text, flags)

    def add(self, page, text, flags):
        if text.strip('　 '):
            self.fragments.append((page, text, flags))

    @property
    def text(self):
        return compact(''.join(t for _, t, _ in self.fragments))

    @property
    def current(self):
        """Only the characters that are not underlined (i.e. still in effect)."""
        return compact(''.join(ch for _, t, f in self.fragments for ch, u in zip(t, f) if not u))

    @property
    def struck(self):
        """True when every visible character in the cell is underlined."""
        marks = [u for _, t, f in self.fragments for ch, u in zip(t, f) if ch.strip('　 ')]
        return bool(marks) and all(marks)

    def lines(self, current=True):
        """Each fragment's text, in order; with current=True underlined characters are dropped."""
        out = []
        for page, t, f in self.fragments:
            text = compact(''.join(ch for ch, u in zip(t, f) if not (current and u)))
            if text:
                out.append((page, text, t.strip('　 ')))
        return out

    def sources(self, current=True):
        return [{'page': p, 'text': raw} for p, text, raw in self.lines(current)]


def _cells(text, flags):
    """Split a table row on ┃ and │, keeping each piece's underline flags."""
    parts, start = [], None
    for i, ch in enumerate(text):
        if ch in '┃│':
            if start is not None:
                parts.append((text[start:i], flags[start:i]))
            start = i + 1
    return parts


def records(pages):
    """Split every page into (section, rows) records at the table rules.

    A record is the text between two horizontal rules; its rows are lists of Cells by column.
    The section is taken from the latest 表題部/権利部 heading seen, across page breaks.
    """
    section = None
    out = []
    current = None

    def close():
        nonlocal current
        if current and any(c.fragments for c in current['cells']):
            out.append(current)
        current = None

    for page in pages:
        for text, flags in page['lines']:
            stripped = text.strip('　 ')
            if not stripped.startswith(('┃', '┏', '┠', '┗')):
                continue
            # A rule line, including "┃　　　├───┼──┨" that separates a 付記 from its main entry.
            if not RULE_CHARS.sub('', stripped.replace('　', '').replace(' ', '')):
                close()
                continue
            cells = _cells(text, flags)
            if not cells:
                continue
            heading = compact(''.join(t for t, _ in cells))
            for key, name in (('表題部(一棟の建物の表示)', 'building'), ('表題部(敷地権の目的である土地の表示)', 'site'),
                              ('表題部(専有部分の建物の表示)', 'unit'), ('表題部(敷地権の表示)', 'land_right'),
                              ('表題部(土地の表示)', 'land'), ('表題部(主である建物の表示)', 'house'),
                              ('表題部(附属建物の表示)', 'annex'), ('権利部(甲区)', 'A'), ('権利部(乙区)', 'B'),
                              ('共同担保目録', 'collateral'), ('専有部分の家屋番号', 'unit_list')):
                if key in heading:
                    close()
                    section = name
                    current = {'section': section, 'heading': True, 'cells': [Cell() for _ in cells], 'width': len(cells)}
                    for cell, (t, f) in zip(current['cells'], cells):
                        cell.add(page['page'], t, f)
                    break
            else:
                if current is None or current.get('heading') or current['width'] != len(cells):
                    close()
                    current = {'section': section, 'heading': False, 'cells': [Cell() for _ in cells], 'width': len(cells)}
                for cell, (t, f) in zip(current['cells'], cells):
                    cell.add(page['page'], t, f)
    close()
    return out


if __name__ == '__main__':
    import sys
    for path in sys.argv[1:]:
        print('#', Path(path).name, 'service_pdf=', is_service_pdf(path))
        for r in records(read_pages(path)):
            print(r['section'], '|'.join(('~' if c.struck else '') + c.text for c in r['cells']))
