"""各編PDFから 歩掛コード（施工パッケージ CB… / 施工歩掛 WB… 等）の索引と、目次の節名を抽出"""
import subprocess, re, unicodedata, json, sys

CIRC = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿'
ROMAN = 'ⅠⅡⅢⅣⅤⅥⅦⅧ'
LABEL = re.compile(r'([' + ROMAN + r'])\s*-\s*(\d+)\s*-\s*([' + CIRC + r'])\s*-\s*(\d+)')
CODE = re.compile(r'(パッケージコード|施工歩掛コード|歩掛コード)\s*([A-Z]{2}\d{6})')
NAMELINE = re.compile(r'^\s*(?:[(（]\s*([0-9０-９]+)\s*[)）]|([0-9０-９]+)\s*[)）])\s*(.*)$')

def norm(s):
    s = ''.join(ch if ch in CIRC or ch in ROMAN else unicodedata.normalize('NFKC', ch) for ch in s)
    return s.replace('­', '-').replace('­', '-')

def pages_text(pdf, engine=None, progress=None):
    """頁ごとのテキスト（レイアウト保持）。pdftotext があれば高速、無ければ pdfplumber"""
    import shutil
    if engine is None:
        engine = 'pdftotext' if shutil.which('pdftotext') else 'pdfplumber'
    if engine == 'pdftotext':
        out = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', pdf, '-'], capture_output=True, text=True, encoding='utf-8').stdout
        pages = out.split('\f')
        if pages and not pages[-1].strip(): pages = pages[:-1]
    else:
        import pdfplumber
        pages = []
        with pdfplumber.open(pdf) as doc:
            n = len(doc.pages)
            for i, p in enumerate(doc.pages):
                pages.append(p.extract_text(layout=True) or '')
                p.close() if hasattr(p, 'close') else None
                if progress and i % 50 == 0: progress(f'  文字読取 {i}/{n} 頁')
    return [norm(p) for p in pages]

def page_label(text):
    lines = [l.strip().replace(' ', '') for l in text.splitlines() if l.strip()]
    for l in reversed(lines):
        m = LABEL.fullmatch(l)
        if m:
            return f'{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}'
    return ''

def body_lines(text):
    return [l for l in text.splitlines() if l.strip() and '土木工事標準積算基準書' not in l and not LABEL.fullmatch(l.strip().replace(' ', ''))]

def volume_title(pages):
    for p in pages[:30]:
        m = re.search(r'土木工事標準積算基準書\s*[(（](\S+?編)[)）]\s*(\S+年度)', p)
        if m: return m.group(1), m.group(2)
    return '', ''

TOCE = re.compile(r'(?:([' + CIRC + r'](?:-\d+)?)\s+)?([^·・.]*?)\s*[·・.]{2,}\s*([' + ROMAN + r'])\s*-\s*(\d+)\s*-\s*([' + CIRC + r'])\s*-\s*(\d+)')

def parse_toc(pages):
    """総目次から 節・小節 の名称と開始頁を拾う（例: Ⅲ-1-① 消波根固めブロック工, ①-2 …(ブロック撤去工) 24頁～）"""
    ents = {}
    for p in pages:
        if not TOCE.search(p): continue
        lines = p.splitlines()
        pend = {}
        for li, l in enumerate(lines):
            # 2段組を大きな空白で分割
            cols = [(m.start(), m.group()) for m in re.finditer(r'\S(?:.*?\S)?(?=\s{6,}|$)', l)]
            for x, seg in cols:
                side = 0 if x < 60 else 1
                m = TOCE.search(seg)
                if m:
                    num, name = m.group(1) or '', m.group(2).strip()
                    if not name or (not num and pend.get(side)):
                        pn, pname = pend.get(side, ('', ''))
                        num = num or pn; name = (pname + name).strip()
                    key = (f'{m.group(3)}-{m.group(4)}-{m.group(5)}', num, int(m.group(6)))
                    name = re.sub(r'\s+', '', name)
                    name = re.sub(r'^第\d+章\S*?(?=[^\d])', '', name) if False else name
                    if name and num and key not in ents:
                        ents[key] = name
                    pend[side] = ('', '')
                else:
                    mm = re.match(r'^([' + CIRC + r'](?:-\d+)?)\s+(.+)$', seg.strip())
                    if mm: pend[side] = (mm.group(1), mm.group(2).strip())
                    elif pend.get(side, ('', ''))[1]:
                        pend[side] = (pend[side][0], pend[side][1] + seg.strip())
    return [dict(setsu=k[0], num=k[1], start=k[2], name=v) for k, v in ents.items()]

def parse_heads(pages):
    """本文の各頁の冒頭にある見出し（例: ② 土工 ／ ②-2 土工(ICT)）から節・小節名と開始頁を拾う"""
    ents = []; seen = set()
    for p in pages:
        lab = page_label(p)
        if not lab: continue
        setsu, pg = lab.rsplit('-', 1)
        pg = int(pg)
        for l in body_lines(p)[0:6]:
            m = re.match(r'^\s*([' + CIRC + r'](?:\s*-\s*\d+)?)\s*(\S.{0,80})$', l)
            if not m or m.group(1)[0] != setsu[-1]: continue
            num = re.sub(r'\s', '', m.group(1)); name = re.sub(r'\s+', '', m.group(2))
            if '-' not in num and pg != 1: continue
            if (setsu, num) in seen: continue
            seen.add((setsu, num))
            ents.append(dict(setsu=setsu, num=num, start=pg, name=name))
    return ents

def section_of(toc, label):
    """頁ラベル(Ⅲ-1-①-24) → 節名と小節名"""
    if not label: return '', ''
    m = re.match(r'(.+-.+-.)-(\d+)', label)
    setsu, pg = m.group(1), int(m.group(2))
    cands = [t for t in toc if t['setsu'] == setsu]
    main = next((t['name'] for t in cands if t['num'] and '-' not in t['num']), '')
    if not main:
        main = next((t['name'] for t in cands if t['start'] == 1), '')
    subs = sorted([t for t in cands if '-' in t['num'] and t['start'] <= pg], key=lambda t: t['start'])
    sub = subs[-1]['name'] if subs else ''
    return main, sub

def extract(pdf, engine=None, progress=None):
    pages = pages_text(pdf, engine, progress)
    vol, nendo = volume_title(pages)
    toc = parse_heads(pages)
    codes = {}
    for pi, p in enumerate(pages):
        label = page_label(p)
        lines = p.splitlines()
        for li, l in enumerate(lines):
            found = list(CODE.finditer(l))
            if not found:
                # 「パッケージコー／ド」のように見出しが折り返されている行
                found = [m for m in re.finditer(r'()\b([CW]B\d{6})\b', l) if '施工単位' in l[m.end():].replace(' ', '')]
            for m in found:
                code = m.group(2)
                kind = 'パッケージコード' if code.startswith('CB') else '施工歩掛コード'
                rest = l[m.end():].replace(' ', '')
                in_kijun = '施工単位' in rest
                um = re.search(r'施工単位(\S+)', rest)
                unit = um.group(1) if um else ''
                # 名称：上にある「(n) 名称」行（複数行にまたがる場合は連結）
                name = ''; k = li - 1; buf = []
                while k >= 0 and li - k <= 6:
                    s = lines[k].strip()
                    nm = NAMELINE.match(s)
                    if nm:
                        name = (nm.group(3) + ''.join(reversed(buf))).strip(); break
                    if s and not CODE.search(s) and not re.fullmatch(r'(パッケージコー|施工歩掛コー|ド|コード)', s.replace(' ', '')): buf.append(s)
                    if len(buf) > 2: break
                    k -= 1
                name = re.sub(r'\s+', '', name)
                name = re.sub(r'\d*(個|m3|m2|m|t|本|基|箇所|日|式)?当り単価表$', '', name)
                main, sub = section_of(toc, label)
                # 入力条件（J条件）の本文：次のコードが出てくるまで（次頁の先頭も少し含める）
                blk = []
                for l2 in lines[li + 1:]:
                    if CODE.search(l2) or re.search(r'\b[CW]B\d{6}\b.*施工単位', l2.replace(' ', '')): break
                    blk.append(l2)
                if pi + 1 < len(pages) and len(blk) < 60:
                    for l2 in pages[pi + 1].splitlines()[:40]:
                        if CODE.search(l2) or NAMELINE.match(l2.strip()): break
                        blk.append(l2)
                jtext = re.sub(r'\s+', '', ''.join(blk))
                rec = dict(code=code, kind='施工パッケージ' if kind == 'パッケージコード' else '施工歩掛',
                           name=name, unit=unit, volume=vol, nendo=nendo, page_pdf=pi + 1, page_label=label,
                           section=main, subsection=sub, source='施工単価入力基準表' if in_kijun else '単価表等', jtext=jtext[:3000])
                old = codes.get(code)
                if old is None or (old['source'] != '施工単価入力基準表' and in_kijun) or (not old['name'] and name and old['source'] == rec['source']):
                    codes[code] = rec
    return dict(volume=vol, nendo=nendo, toc=toc, codes=list(codes.values()), pages=len(pages), _pages=pages)

if __name__ == '__main__':
    d = extract(sys.argv[1]); d.pop('_pages')
    json.dump(d, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
    print(d['volume'], d['nendo'], len(d['codes']), 'codes', len(d['toc']), 'toc')
