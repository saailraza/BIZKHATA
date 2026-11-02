"""Minimal .xlsx writer / reader (Python standard library only). Used for Excel export and the backup import."""
import io
import re
import zipfile
from xml.sax.saxutils import escape as _esc

X = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def esc(s):
    return _esc(str(s), {'"': '&quot;'})


def unesc(s):
    s = str(s).replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), s)
    return s.replace('&amp;', '&')


def col_name(i):
    s, i = '', i + 1
    while i > 0:
        m = (i - 1) % 26
        s = chr(65 + m) + s
        i = (i - 1) // 26
    return s


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def clean_name(n, i):
    n = re.sub(r'[\[\]\*\?/\\:]', ' ', str(n))[:31].strip()
    return n or 'Sheet%d' % (i + 1)


def write_xlsx(sheets):
    """sheets: [{'name': str, 'rows': [[...], ...]}]  first row = headings. Numbers stay numbers."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', X + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                    + ''.join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(sheets))) + '</Types>')
        z.writestr('_rels/.rels', X + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', X + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                    + ''.join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (esc(clean_name(s['name'], i)), i + 1, i + 1) for i, s in enumerate(sheets)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', X + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + ''.join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets)))
                    + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (len(sheets) + 1))
        z.writestr('xl/styles.xml', X + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for si, sh in enumerate(sheets):
            width = max([1] + [len(r) for r in sh['rows']])
            rows = []
            for ri, r in enumerate(sh['rows']):
                cells = []
                for ci, v in enumerate(r):
                    if v is None or v == '':
                        continue
                    ref, st = col_name(ci) + str(ri + 1), (' s="1"' if ri == 0 else '')
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        cells.append('<c r="%s"%s><v>%s</v></c>' % (ref, st, repr(v)))
                    else:
                        cells.append('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, st, esc(v)))
                rows.append('<row r="%d">%s</row>' % (ri + 1, ''.join(cells)))
            z.writestr('xl/worksheets/sheet%d.xml' % (si + 1), X + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="1" max="%d" width="22" customWidth="1"/></cols><sheetData>%s</sheetData></worksheet>' % (width, ''.join(rows)))
    return out.getvalue()


def read_xlsx(data):
    """returns {'Sheet name': [[cell, ...], ...]}   (also reads files that were re-saved in Excel)"""
    z = zipfile.ZipFile(io.BytesIO(data))

    def txt(n):
        try:
            if z.getinfo(n).file_size > 40 * 1024 * 1024:
                raise ValueError('file too large')
            return z.read(n).decode('utf-8')
        except KeyError:
            return ''

    wb = txt('xl/workbook.xml')
    if not wb:
        raise ValueError('not an xlsx file')
    rels = {}
    for m in re.finditer(r'<Relationship\b[^>]*>', txt('xl/_rels/workbook.xml.rels')):
        i, t = re.search(r'Id="([^"]+)"', m.group(0)), re.search(r'Target="([^"]+)"', m.group(0))
        if i and t:
            tg = t.group(1).lstrip('/')
            rels[i.group(1)] = tg if tg.startswith('xl/') else 'xl/' + tg
    shared = []
    for m in re.finditer(r'<si\b[^>]*>([\s\S]*?)</si>', txt('xl/sharedStrings.xml')):
        shared.append(unesc(''.join(re.findall(r'<t\b[^>]*>([\s\S]*?)</t>', m.group(1)))))
    out = {}
    for m in re.finditer(r'<sheet\b[^>]*>', wb):
        nm, i = re.search(r'name="([^"]*)"', m.group(0)), re.search(r'r:id="([^"]+)"', m.group(0))
        if not nm or not i or i.group(1) not in rels:
            continue
        rows = []
        for rm in re.finditer(r'<row\b[^>]*>([\s\S]*?)</row>', txt(rels[i.group(1)])):
            cells = {}
            for cm in re.finditer(r'<c\b([^>]*?)(?:/>|>([\s\S]*?)</c>)', rm.group(1)):
                ref = re.search(r'r="([A-Z]+)\d+"', cm.group(1))
                if not ref:
                    continue
                t = (re.search(r't="([^"]+)"', cm.group(1)) or [None, None])[1]
                body, v = cm.group(2) or '', ''
                if t == 'inlineStr':
                    v = unesc(''.join(re.findall(r'<t\b[^>]*>([\s\S]*?)</t>', body)))
                else:
                    vm = re.search(r'<v>([\s\S]*?)</v>', body)
                    if vm:
                        raw = vm.group(1)
                        if t == 's':
                            v = shared[int(raw)] if int(raw) < len(shared) else ''
                        elif t == 'str':
                            v = unesc(raw)
                        elif t == 'b':
                            v = raw
                        else:
                            try:
                                v = float(raw)
                                v = int(v) if v == int(v) and 'e' not in raw.lower() and '.' not in raw else v
                            except ValueError:
                                v = unesc(raw)
                cells[col_index(ref.group(1))] = v
            n = (max(cells) + 1) if cells else 0
            rows.append([cells.get(k, '') for k in range(n)])
        out[unesc(nm.group(1))] = rows
    return out
