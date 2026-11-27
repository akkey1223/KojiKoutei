"""共通編 第Ⅰ編14章④ 作業日当り標準作業量 の抽出"""
import pdfplumber, re, json, sys, unicodedata

CIRC = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿'
UNIT = r'(?:\([0-9.]+\))?[^\s0-9/()]*?(?:m[23]|[^\s0-9/()]*)/日(?:・[^\s0-9]+)?'
VAL = re.compile(r'^(?:[0-9][0-9,.]*\s*' + UNIT + r'\s*)+$')
VALS = re.compile(r'([0-9][0-9,.]*)\s*(' + UNIT + r')')
NUM = re.compile(r'^[0-9][0-9,.]*$')
KEY = re.compile(r'標準作業量|日当り|日当')
FOOT = re.compile(r'Ⅰ-14-④-(\d+)')

def clean(s):
    if s is None: return ''
    out = []
    for ch in s:
        out.append(ch if ch in CIRC else unicodedata.normalize('NFKC', ch))
    s = re.sub(r'\s+', ' ', ''.join(out)).strip()
    # 半角英数どうしの間の空白だけ残す（例: 200 250 300）
    s = re.sub(r'(?<![0-9A-Za-z.,]) | (?![0-9A-Za-z])', '', s)
    return s

def cell_text(page, bb):
    t = page.crop((bb[0]+0.5, bb[1]+0.5, bb[2]-0.5, bb[3]-0.5)).extract_text() or ''
    return t.strip()

def grid(page, tb):
    """各格子位置を覆うセル（結合セル込み）の (id, text) を返す"""
    cells = tb.cells
    xs = sorted({round(c[0], 1) for c in cells} | {round(c[2], 1) for c in cells})
    rows = tb.rows
    out = []
    cache = {}
    for r in rows:
        y0 = r.bbox[1]; y1 = min(c[3] for c in r.cells if c)
        line = []
        for i in range(len(xs)-1):
            cx = (xs[i]+xs[i+1])/2; cy = (y0+y1)/2
            if xs[i+1]-xs[i] < 2: continue
            hit = [c for c in cells if c[0]-0.5 <= cx <= c[2]+0.5 and c[1]-0.5 <= cy <= c[3]+0.5]
            if not hit: line.append((None, '')); continue
            c = min(hit, key=lambda c: (c[2]-c[0])*(c[3]-c[1]))
            if c not in cache: cache[c] = cell_text(page, c)
            line.append((c, cache[c]))
        out.append(((r.bbox[0], y0, r.bbox[2], y1), line))
    return out

def norm_num(s):
    s = unicodedata.normalize('NFKC', s).replace(',', '')
    try: return float(s)
    except: return None

def unit_from(label):
    m = re.search(r'[(（]([^()（）]*?/日[^()（）]*)[)）]', label)
    return m.group(1) if m else ''

LAST = {}
def parse_inner(page, tb, prev=None):
    g = grid(page, tb)
    if not g: return []
    T = [[clean(t) for c, t in line] for _, line in g]
    C = [[c for c, t in line] for _, line in g]
    cont = False
    if prev and not any(KEY.search(x) for r in T for x in r):
        # 見出しの無い続きの表 → 直前の表の見出しを借りる
        ph, punit = prev
        ncols = max(len(r) for r in T)
        if ph and len(ph[0]) == ncols and sum(1 for r in T for x in r if NUM.match(x)) > 3:
            own = []
            for r in T:
                if any(NUM.match(x) for x in r): break
                own.append(r)
            labs = {r[0] for r in own}
            hdr = [r for r in ph if r[0] not in labs]
            # 自前の見出し行は、借りた見出しの同じラベル位置に差し替え
            merged = []
            for r in ph:
                rep = [o for o in own if o[0] == r[0]]
                merged.append(rep[0] if rep else r)
            T = merged + T[len(own):]
            fakeC = [[('h', i, j) for j in range(len(r))] for i, r in enumerate(merged)]
            C = fakeC + C[len(own):]
            g = [((0, 0, 0, 0), None)] * len(merged) + g[len(own):]
            cont = True
    nrow = len(T); recs = []

    def colhead(j, upto):
        parts = []
        for i in range(upto):
            if j < len(T[i]) and T[i][j] and T[i][j] not in parts and not KEY.search(T[i][j]):
                parts.append(T[i][j])
        return '／'.join(parts)

    # --- 横向き表：先頭セルに「標準作業量」がある行 ---
    lab_rows = [i for i in range(nrow) if T[i] and KEY.search(T[i][0]) and any(NUM.match(x) for x in T[i][1:])]
    if lab_rows:
        i0 = lab_rows[0]
        unit = unit_from(T[i0][0])
        span = [i for i in range(i0, nrow) if i == i0 or C[i][0] == C[i0][0]]
        def isnumrow(i): return any(NUM.match(x) for x in T[i][1:])
        # ブロック分け：1ブロック目は i0 以上の数値行、以降は「数値の無い行」から始まる塊
        blocks = []
        cur = None
        for i in span:
            if cur is None:
                cur = dict(hdr=list(range(i0)), vals=[], first=True)
            if isnumrow(i) and (cur['first'] or not cur['vals'] and False):
                cur['vals'].append(i)
            elif not isnumrow(i):
                blocks.append(cur); cur = dict(hdr=[i], vals=[], first=False)
            else:
                cur['hdr'].append(i)
        blocks.append(cur)
        for bk in blocks:
            if not bk['first'] and bk['hdr']:
                bk['vals'] = [bk['hdr'].pop()]   # 最後の行を値とみなす
            for i in bk['vals']:
                seen = set(); rowlab = []
                for j in range(1, len(T[i])):
                    x = T[i][j]
                    if C[i][j] in seen: continue
                    seen.add(C[i][j])
                    if x and not NUM.match(x) and x not in ('-', '－', '―'): rowlab.append(x)
                for j in range(1, len(T[i])):
                    x = T[i][j]
                    if not NUM.match(x): continue
                    hp = []
                    for h in bk['hdr']:
                        if j < len(T[h]) and T[h][j] and T[h][j] not in hp and not KEY.search(T[h][j]): hp.append(T[h][j])
                    cond = [('', '／'.join(hp))] + [('', r) for r in rowlab]
                    recs.append(dict(cond=[c for c in cond if c[1]], valhead='', value=float(x.replace(',', '')),
                                     value_raw=x, unit=unit, multi=0, y=g[i][0][1],
                                     mode='横' if bk['first'] else '横(要確認)'))
        if recs: return recs

    # --- 縦向き表：見出しに「標準作業量」がある列、または値＋単位のセル ---
    valcols = {}
    for j in range(max(len(r) for r in T)):
        for i in range(nrow):
            if j < len(T[i]) and KEY.search(T[i][j]) and i + 1 < nrow:
                valcols.setdefault(j, (i, unit_from(T[i][j])))
                break
    for i in range(nrow):
        for j, x in enumerate(T[i]):
            if VAL.match(x) and j not in valcols:
                valcols[j] = (-1, '')
    valcols = {j: v for j, v in valcols.items()
               if any(j < len(T[i]) and (VAL.match(T[i][j]) or NUM.match(T[i][j])) for i in range(max(v[0], 0) + 1, nrow))
               or v[0] < 0}
    if not valcols: return []
    def isval(i, j):
        x = T[i][j] if j < len(T[i]) else ''
        return bool(VAL.match(x) or (NUM.match(x) and valcols[j][0] >= 0 and i > valcols[j][0]))
    rows_with_val = [i for i in range(nrow) if any(isval(i, j) for j in valcols)]
    if not rows_with_val: return []
    first = rows_with_val[0]
    LAST['hdr'] = (T[:first], next((v[1] for v in valcols.values() if v[1]), ''))
    for i in rows_with_val:
        seen = set(); conds = []
        for j, x in enumerate(T[i]):
            if j in valcols or C[i][j] is None or C[i][j] in seen: continue
            seen.add(C[i][j])
            if not x or x in ('-', '－', '―') or KEY.search(x): continue
            conds.append((colhead(j, first), x))
        for j in sorted(valcols):
            if not isval(i, j): continue
            x = T[i][j]; vh = colhead(j, first)
            if VAL.match(x):
                for k, m in enumerate(VALS.finditer(x)):
                    recs.append(dict(cond=conds, valhead=vh, value=float(m.group(1).replace(',', '')),
                                     value_raw=m.group(1), unit=m.group(2), multi=k, y=g[i][0][1], mode='縦'))
            else:
                recs.append(dict(cond=conds, valhead=vh, value=float(x.replace(',', '')), value_raw=x,
                                 unit=valcols[j][1], multi=0, y=g[i][0][1], mode='縦(続き・要確認)' if cont else '縦'))
    return recs

def run(path, page_idx=None, progress=None):
    """path: 共通編PDF。page_idx: Ⅰ-14-④ の頁番号（0始まり）のリスト。無ければ全頁から探す"""
    pdf = pdfplumber.open(path)
    if page_idx is None:
        page_idx = []
        for pi, page in enumerate(pdf.pages):
            t = (page.extract_text() or '').rstrip()
            if t and FOOT.fullmatch(t.splitlines()[-1].replace(' ', '')): page_idx.append(pi)
    res = []; warn = []
    kousyu = ''; last_title = {}; prev_hdr = {}; lastno = 0
    first, last = min(page_idx), max(page_idx)
    for n, pi in enumerate(range(first, last + 1)):
        page = pdf.pages[pi]
        if progress and n % 10 == 0: progress(f'  日当り表 {n}/{last - first + 1} 頁')
        txt = (page.extract_text() or '').rstrip()
        fm = None
        for l in reversed(txt.splitlines()):
            fm = FOOT.fullmatch(l.strip().replace(' ', ''))
            if fm: break
        if fm:
            lastno = int(fm.group(1)); label = f'Ⅰ-14-④-{lastno}'
        else:
            lastno += 1; label = f'Ⅰ-14-④-{lastno}(推定)'
        tables = page.find_tables()
        def is_outer(t):
            h = t.extract()[0]
            return len(h) >= 2 and clean(h[0]) == '工種名' and clean(h[-1]) == '設定内容'
        outer = [t for t in tables if is_outer(t)]
        inner = [t for t in tables if t not in outer]
        krows = []
        for o in outer:
            for r in o.rows:
                c0 = r.cells[0]
                if c0:
                    t = clean(cell_text(page, c0))
                    if t and t != '工種名': krows.append((c0[1], c0[3], t))
        lines = page.extract_text_lines()
        for tb in inner:
            x0, top, x1, bot = tb.bbox
            ks = [k for k in krows if k[0] - 1 <= top <= k[1] + 1]
            if ks: kousyu = ks[0][2]
            ktop = ks[0][0] if ks else 0
            circ = [ch for ch in page.chars if ch['text'] in CIRC and ch['x0'] < x0 + 3 and ktop - 2 <= ch['top'] and ch['bottom'] <= top + 1
                    and not any(t2.bbox[0] - 1 <= ch['x0'] <= t2.bbox[2] + 1 and t2.bbox[1] - 1 <= ch['top'] <= t2.bbox[3] + 1 for t2 in inner)]
            cand = [l for l in lines if any(abs(l['top'] - ch['top']) < 3 for ch in circ) and re.search('[' + CIRC + ']', l['text'])]
            if cand:
                tl = max(cand, key=lambda l: l['bottom'])
                tt = tl['text']
                title = clean(tt[re.search('[' + CIRC + ']', tt).start():])
                last_title[kousyu] = title
            else:
                title = last_title.get(kousyu, '')
            LAST.clear()
            pr = parse_inner(page, tb, prev_hdr.get(title))
            if 'hdr' in LAST: prev_hdr[title] = LAST['hdr']
            g = grid(page, tb)
            ncell = len({c for _, l in g for c, t in l if c and (NUM.match(clean(t)) or VAL.match(clean(t)))})
            if ncell and len(pr) < ncell * 0.6 and len(pr) < ncell - 1:
                warn.append(dict(page_pdf=pi + 1, page_label=label, kousyu=kousyu, title=title, cells=ncell, extracted=len(pr)))
            for r in pr:
                res.append(dict(kousyu=kousyu, title=title, page_pdf=pi + 1, page_label=label, **r))
        page.close() if hasattr(page, 'close') else None
    return dict(records=res, warnings=warn)

if __name__ == '__main__':
    d = run(sys.argv[1])
    json.dump(d, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
    print(len(d['records']), 'records', len(d['warnings']), 'warnings')
