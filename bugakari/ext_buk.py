"""施工歩掛（WB…）の各ページにある「日当り施工量」の表を抽出する

各編の本文から、題名に「日当り施工量／日当り作業量／日当り運搬量／日当り施工本数 …」を含む表を拾い、
単価表の摘要欄の表番号（例：表 4.1～表 4.4）で施工歩掛コードと結び付ける。
表はレイアウト保持テキストから読み取る（罫線の無い表にも対応するため）。
"""
import re, unicodedata

from ext_codes import CIRC, LABEL, CODE, page_label, section_of
import ext14

TITLE = re.compile(r'^\s*表\s*([0-9]+)\s*[.．]\s*([0-9]+)\s*(.*)$')
DAILY_WORD = re.compile(r'日当り|1日当り')
DAILY_OK = re.compile(r'(施工|作業|運搬|打設|掘削|削孔|据付|設置|撤去|量|数|延長|面積)')
DAILY_NG = re.compile(r'編成|運転時間|補正|保守|処理費|損料|単価|係数|機械器具|燃料|人員')
NUM = re.compile(r'^[0-9][0-9,]*(\.[0-9]+)?$')
STOP = re.compile(r'^\s*([(（]\s*注|注\s*[)）]|[0-9]+\s*[.．]\s*\S|[0-9]+\s*[-－]\s*[0-9]+\s+\S|[(（][0-9]+[)）]|表\s*[0-9]+\s*[.．])')


def tbl_no(a, b):
    return f'{int(a)}.{int(b)}'


def unit_of(title):
    t = title.replace(' ', '')
    m = re.search(r'[\[［]([^\[\]［］]*?/日[^\[\]［］]*?)[\]］]', t)
    if m: return m.group(1)
    m = re.search(r'[(（\[［]\s*([^()（）\[\]［］]*?/\s*日[^()（）\[\]［］]*?)\s*[)）\]］]\s*$', title)
    if m: return re.sub(r'\s', '', m.group(1))
    m = re.search(r'[(（\[［]\s*([^()（）\[\]［］]*?/\s*日[^()（）\[\]［］]*?)\s*[)）\]］]', title)
    return re.sub(r'\s', '', m.group(1)) if m else ''


def split_cells(line):
    """2文字以上の空白で区切ったセル（位置つき）"""
    out = []
    for m in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)', line):
        t = m.group().strip()
        if re.fullmatch(r'[0-9.,]+(\s+[0-9.,]+)+', t):
            for m2 in re.finditer(r'[0-9.,]+', t): out.append((m.start() + m2.start(), m2.group()))
        else:
            out.append((m.start(), t))
    return out


def squeeze(s):
    """日本語の文字間の空白を詰める（例：設    置 → 設置）"""
    s = re.sub(r'(?<=[^\x00-\x7f])\s+(?=[^\x00-\x7f])', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def numtok(s):
    return NUM.match(s) is not None


def parse_block(lines, unit):
    """表の行（テキスト）から [(条件[(見出し,値)], 値見出し, 数値文字列)] を作る"""
    rows = [split_cells(l) for l in lines if l.strip()]
    rows = [r for r in rows if r]
    out = []
    # --- 横向き：「日当り…」の行に数値が横に並ぶ表 ---
    raw = [l for l in lines if l.strip()]
    for i, r in enumerate(rows):
        lab = r[0][1]
        vals = [c for c in r[1:] if numtok(c[1])]
        ok = DAILY_WORD.search(lab) and len(vals) >= 2 and len(vals) == len(r) - 1
        if not ok and len(r) >= 2 and all(numtok(c[1]) for c in r):
            # 見出しが上下に折り返されている（例：日当り運搬量／数値／（m3)）
            up = rows[i - 1] if i > 0 else []
            if len(up) == 1 and DAILY_WORD.search(up[0][1]) and up[0][0] < r[0][0]:
                lab = up[0][1]
                if i + 1 < len(rows) and len(rows[i + 1]) == 1 and re.fullmatch(r'[(（].*[)）]', rows[i + 1][0][1]):
                    lab += rows[i + 1][0][1]
                vals = list(r); ok = True; i_head_limit = i - 1
        if not ok: continue
        lim = i if DAILY_WORD.search(r[0][1]) else i - 1
        xs = [c[0] + len(c[1]) / 2 for c in vals]
        bounds = [xs[0] - (xs[1] - xs[0]) / 2] + [(xs[k] + xs[k + 1]) / 2 for k in range(len(xs) - 1)] + [10 ** 4]
        left = max(0, int(bounds[0]))
        # 列見出し：値の位置に文字が並んでいる直前の行
        hk = None; hseg = None
        n = len(vals)
        for k in range(lim - 1, -1, -1):
            toks = raw[k][left:].split() if len(raw[k]) > left else []
            if toks and len(toks) % n == 0 and not all(numtok(t) for t in toks) and len(raw[k][:left].strip()) > 0:
                g = len(toks) // n
                hk, hseg = k, [' '.join(toks[j * g:(j + 1) * g]) for j in range(n)]; break
            segs = [squeeze(raw[k][max(0, int(bounds[j])):int(bounds[j + 1])]) for j in range(n)]
            if sum(1 for x in segs if x) >= n - 1 and not all(numtok(x) for x in segs if x):
                hk, hseg = k, segs; break
        hlab = squeeze(raw[hk][:left]) if hk is not None else ''

        # それより上は「見出し：内容」の前提条件（字下げ行は続き）
        ctx = []
        lm = min((rows[k][0][0] for k in range(0, hk if hk is not None else lim) if rows[k]), default=0)
        pend = ''
        for k in range(0, hk if hk is not None else lim):
            line = raw[k]
            if rows[k][0][0] <= lm + 1:
                ctx.append([rows[k][0][1], (pend + ' ' + ' '.join(c[1] for c in rows[k][1:])).strip()])
                pend = ''
            elif ctx and ctx[-1][1] and not pend:
                ctx[-1][1] += ' ' + line.strip()
            elif ctx and not ctx[-1][1]:
                ctx[-1][1] = line.strip()
            else:
                pend += ' ' + line.strip()
        # 次の見出しの前にある字下げ行は、次の見出しに属する場合がある（上下に分かれたセル）
        if pend and ctx: ctx[-1][1] += ' ' + pend.strip()
        mu = re.search(r'[(（]([^()（）]+)[)）]', lab)
        u = unit or (re.sub(r'[\s)）]', '', mu.group(1)) + '/日' if mu else '')
        for j, v in enumerate(vals):
            cond = [(squeeze(h), squeeze(t)) for h, t in ctx]
            if hseg and hseg[j]: cond.append((hlab, hseg[j]))
            out.append((cond, '', v[1], u))
        return out, '横'
    # --- 縦向き：各行の末尾が数値（複数の値列もあり） ---
    head = None
    prev_labels = []
    for r in rows:
        nums = [c for c in r if numtok(c[1])]
        labs = [c for c in r if not numtok(c[1])]
        if not nums:
            if head is None or not out:
                head = r          # 値の行より前の、数値の無い行 = 見出し
            continue
        # 数値は行の右側にまとまっている前提
        first_num = r.index(nums[0])
        if any(not numtok(c[1]) for c in r[first_num:]):
            # 値の後ろに文字（単位など）がある場合はそのまま条件に入れる
            pass
        labels = [c for c in r[:first_num]]
        # 左の見出しが省略された行（セル結合）は、前の行の左側を引き継ぐ
        if prev_labels and labels and labels[0][0] > prev_labels[0][0] + 4:
            keep = [p for p in prev_labels if p[0] < labels[0][0] - 2]
            labels = keep + labels
        elif prev_labels and not labels:
            labels = list(prev_labels)
        prev_labels = labels
        hnames = []
        if head:
            for pos, txt in labels:
                hn = [h[1] for h in head if abs(h[0] - pos) <= 6 or (h[0] <= pos + 2 and pos <= h[0] + len(h[1]) * 2)]
                hnames.append(hn[0] if hn else '')
        else:
            hnames = [''] * len(labels)
        cond = [(squeeze(hnames[k]), squeeze(labels[k][1])) for k in range(len(labels))]
        vh_all = []
        if head and len(nums) > 1:
            hv = [h for h in head if h[0] >= (labels[-1][0] + 2 if labels else 0)]
            vh_all = [h[1] for h in hv[-len(nums):]] if len(hv) >= len(nums) else []
        for k, v in enumerate(nums):
            vh = squeeze(vh_all[k]) if k < len(vh_all) else ''
            out.append((cond, vh, v[1], unit))
    return out, '縦'


def parse_grid(page, tb, unit):
    """罫線のある表（pdfplumber）を [(条件, 値見出し, 数値, 単位)] にする"""
    g = ext14.grid(page, tb)
    if not g: return [], ''
    T = [[squeeze(ext14.clean(t)) for c, t in l] for _, l in g]
    C = [[c for c, t in l] for _, l in g]
    nrow, ncol = len(T), max(len(r) for r in T)
    isnum = lambda x: numtok(x.replace(' ', ''))
    out = []
    # 横向き：先頭列に「日当り」がある行が値の行
    vrows = [i for i in range(nrow) if T[i] and DAILY_WORD.search(T[i][0]) and any(isnum(x) for x in T[i][1:])]
    if vrows:
        for i in vrows:
            mu = re.search(r'[(（]([^()（）]+)[)）]', T[i][0])
            u = unit or (mu.group(1) + '/日' if mu and '/日' not in mu.group(1) else (mu.group(1) if mu else ''))
            for j in range(1, len(T[i])):
                if not isnum(T[i][j]): continue
                cond = []
                for k in range(nrow):
                    if k in vrows or j >= len(T[k]) or not T[k][j] or isnum(T[k][j]): continue
                    cond.append((T[k][0] if T[k][0] != T[k][j] else '', T[k][j]))
                out.append((cond, '', T[i][j].replace(' ', ''), u))
        return out, '横'
    # 縦向き・行列：数値の少ない列が条件、多い列が値
    first = next((i for i in range(nrow) if any(isnum(x) for x in T[i][1:])), None)
    if first is None: return [], ''
    data = range(first, nrow)
    def ratio(j):
        xs = [T[i][j] for i in data if j < len(T[i]) and T[i][j] and T[i][j] not in ('-', '－', '―')]
        return sum(1 for x in xs if isnum(x)) / len(xs) if xs else 0
    vcols = [j for j in range(ncol) if ratio(j) >= 0.6]
    lcols = [j for j in range(ncol) if j not in vcols]
    if not vcols: return [], ''
    def head(j):
        hs = []
        for i in range(first):
            if j < len(T[i]) and T[i][j] and T[i][j] not in hs and not (DAILY_WORD.search(T[i][j]) and '/日' in T[i][j].replace(' ', '')):
                hs.append(T[i][j])
        return '／'.join(hs)
    hu = ''
    for i in range(first):
        for x in T[i]:
            m = re.search(r'[(（]([^()（）]*?/日[^()（）]*)[)）]', x.replace(' ', ''))
            if m: hu = m.group(1)
    last_unit = []
    for i in data:
        cond = []; seen = set()
        for j in lcols:
            if j >= len(T[i]) or C[i][j] in seen: continue
            seen.add(C[i][j])
            if T[i][j] and T[i][j] not in ('-', '－', '―'): cond.append((head(j), T[i][j]))
        for j in vcols:
            if j < len(T[i]) and isnum(T[i][j]):
                vh = head(j) if len(vcols) > 1 or head(j) else ''
                u = unit or hu
                if not u or u in ('1日当り', '1日・1層当り'):
                    cu = [v for h, v in cond if h.replace(' ', '') == '単位']
                    if cu:
                        if cu[0] in ('〃', '″', '”'): cu = [last_unit[0]] if last_unit else cu
                        else: last_unit[:] = [cu[0]]
                        u = cu[0] + '/日' + ('' if not unit else '')
                out.append((cond, vh if len(vcols) > 1 else '', T[i][j].replace(' ', ''), u))
    return out, '縦'


def find_tables(pages, toc, pdf=None):
    """日当り表を拾う：[{setsu, sub, no, title, unit, page_pdf, page_label, rows}]"""
    res = []
    for pi, p in enumerate(pages):
        lab = page_label(p)
        if not lab: continue
        lines = p.splitlines()
        for li, l in enumerate(lines):
            m = TITLE.match(l)
            if not m: continue
            m_ = m
            ttl = re.sub(r'\s+', ' ', m.group(3)).strip()
            t2 = ttl.replace(' ', '')
            if not (DAILY_WORD.search(t2) and DAILY_OK.search(t2)) or DAILY_NG.search(t2):
                continue
            unit = unit_of(ttl)
            # 次の表題・注記・項目見出しまで（最大40行）
            blk = []
            for l2 in lines[li + 1: li + 41]:
                if STOP.match(l2) and blk: break
                if '土木工事標準積算基準書' in l2 or LABEL.fullmatch(l2.strip().replace(' ', '')): break
                blk.append(l2)
            # 単位だけの行（例：(m2/日)）は単位として使う
            for b in blk[:2]:
                if not unit and re.fullmatch(r'\s*[(（][^()（）]*?/日[^()（）]*[)）]\s*', b):
                    unit = re.sub(r'[\s()（）]', '', b)
            rows, mode = [], ''
            if pdf is not None:
                try:
                    pg = pdf.pages[pi]
                    tops = [m['top'] for m in pg.search(r'表\s*[0-9０-９]+\s*[．.]\s*[0-9０-９]+')
                            if [int(x) for x in re.findall(r'[0-9]+', unicodedata.normalize('NFKC', m['text']))][:2] == [int(m_.group(1)), int(m_.group(2))]]
                    best = None
                    alltb = pg.find_tables() if tops else []
                    for y in tops:
                        below = [t for t in alltb if t.bbox[1] >= y - 2]
                        if below:
                            t0 = min(below, key=lambda t: t.bbox[1])
                            d = t0.bbox[1] - y
                            if d < 80 and (best is None or d < best[0]): best = (d, t0)
                    if best:
                            rows, mode = parse_grid(pg, best[1], unit)
                            mode = '罫線表・' + mode if rows else ''
                except Exception:
                    rows = []
            if not rows:
                rows, mode = parse_block(blk, unit)
                mode = '本文読取・' + mode
            if not rows: continue
            main, sub = section_of(toc, lab)
            res.append(dict(setsu=lab.rsplit('-', 1)[0], sub=sub, section=main, no=tbl_no(m.group(1), m.group(2)),
                            title=ttl, unit=unit, page_pdf=pi + 1, page_label=lab, rows=rows, mode=mode))
    return res


REF = re.compile(r'表\s*([0-9]+)\s*[.．]\s*([0-9]+)(?:\s*[～~〜]\s*表?\s*([0-9]+)\s*[.．]\s*([0-9]+))?')


def tanka_refs(pages, toc):
    """単価表ごとの参照表番号：{(code, setsu, sub): {表番号,…}}"""
    refs = {}
    for pi, p in enumerate(pages):
        lab = page_label(p)
        if not lab: continue
        lines = p.splitlines()
        for li, l in enumerate(lines):
            for m in CODE.finditer(l):
                if '施工単位' in l[m.end():].replace(' ', ''): continue
                code = m.group(2)
                blk = []
                for l2 in lines[li + 1: li + 40]:
                    if CODE.search(l2) or re.match(r'^\s*[(（]\s*[0-9]+\s*[)）].*(単価表|当り)', l2): break
                    blk.append(l2)
                txt = unicodedata.normalize('NFKC', ' '.join(blk))
                main, sub = section_of(toc, lab)
                s = refs.setdefault((code, lab.rsplit('-', 1)[0], sub), set())
                for r in REF.finditer(txt):
                    a, b = int(r.group(1)), int(r.group(2))
                    if r.group(3):
                        c, d = int(r.group(3)), int(r.group(4))
                        if a == c:
                            for k in range(b, d + 1): s.add(f'{a}.{k}')
                        else:
                            s.add(f'{a}.{b}'); s.add(f'{c}.{d}')
                    else:
                        s.add(f'{a}.{b}')
    return refs


def harmonic(a, b):
    return 1 / (1 / a + 1 / b)


def extract(vol, pdf_path=None):
    """vol: ext_codes.extract の結果（_pages, toc, codes を使う）
    戻り値：{code: [daily行…]}（行は文書の並び順）"""
    pages, toc = vol['_pages'], vol['toc']
    pdf = None
    if pdf_path:
        import pdfplumber
        pdf = pdfplumber.open(pdf_path)
    tables = find_tables(pages, toc, pdf)
    refs = tanka_refs(pages, toc)
    wb = [c for c in vol['codes'] if c['code'].startswith('WB')]
    out = {}
    for c in wb:
        setsu = c['page_label'].rsplit('-', 1)[0] if c['page_label'] else ''
        if not setsu: continue
        cand = [t for t in tables if t['setsu'] == setsu and t['sub'] == c['subsection']]
        r = set()
        for (code, st, sb), s in refs.items():
            if code == c['code'] and st == setsu: r |= s
        how = '単価表の参照表'
        hit = [t for t in cand if t['no'] in r]
        if not hit:
            others = [x for x in wb if x is not c and x['page_label'].rsplit('-', 1)[0] == setsu and x['subsection'] == c['subsection']]
            if cand and not others:
                hit, how = cand, '節内の唯一の施工歩掛'
        if not hit: continue
        rows = []
        for t in hit:
            for cond, vh, v, u in t['rows']:
                rows.append(dict(item=f'表{t["no"]} {t["title"]}', cond=cond, valhead=vh,
                                 value=float(v.replace(',', '')), value_raw=v, unit=u or t['unit'],
                                 src_label=t['page_label'], src_pdf=t['page_pdf'], how=how, mode='施工歩掛頁・' + t['mode']))
        # 設置・撤去の2行だけの表で、1コードが設置と撤去の両方を受け持つ場合は合成値も付ける
        lab = {(''.join(v for h, v in x['cond'])).replace(' ', ''): x for x in rows}
        if set(lab) == {'設置', '撤去'}:
            a, b = lab['設置']['value'], lab['撤去']['value']
            v = harmonic(a, b)
            rows.append(dict(lab['設置'], cond=[('', '設置・撤去（合成）')], value=round(v),
                             value_raw=f'{v:.1f}', how='計算：1/(1/設置+1/撤去)', mode='計算値'))
        out[c['code']] = rows
    return out, tables
