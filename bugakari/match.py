"""Ⅰ-14-④ の日当り標準作業量 と 各編の歩掛コード を突き合わせる"""
import re, unicodedata, difflib

CIRC = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿'

def key(s):
    s = re.sub(r'^\s*[' + CIRC + r']', '', s or '')
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'※.*$', '', s)
    s = re.sub(r'[\s　]', '', s)
    s = s.replace('（', '(').replace('）', ')').replace('，', ',').replace('、', ',')
    s = s.replace('〔', '(').replace('〕', ')').replace('[', '(').replace(']', ')')
    return s

def loose(s):
    s = key(s)
    return re.sub(r'[()・,]', '', s)

def section_ok(c, kk):
    sc = 0
    for s in (c['section'], c['subsection']):
        ks = key(s)
        if not ks: continue
        if ks == kk: sc = max(sc, 2)
        elif kk and (kk in ks or ks in kk): sc = max(sc, 1)
    return sc

def _core(name, kk):
    """コード名・条件値を（中心語の候補, 括弧内の語）に分ける。節名と同じ括弧書きは除く"""
    s = key(name)
    parens = re.findall(r'\(([^()]*)\)', s)
    base = re.sub(r'\([^()]*\)', '', s).replace('作業', '')
    parens = [p for p in parens if p and p not in kk and kk.find(p) < 0]
    alts = [a for a in re.split(r'[・,]', base) if a]
    return alts, set(parens)

def by_work_name(conds, insec, kk):
    out = []
    for h, v in conds:
        if not re.search(r'作業|工種|種別|区分|工程', h or ''): continue
        valt, vpar = _core(v, kk)
        if len(valt) != 1: continue
        vb = valt[0]
        if vb in ('設置', '撤去', '設置撤去', '有り', '無し'): continue
        best = []
        for c in insec:
            alts, cpar = _core(c['name'], kk)
            if not alts: continue
            sc = 0
            for a in alts:
                if a == vb: sc = max(sc, 3)
                elif len(vb) >= 2 and a.startswith(vb): sc = max(sc, 2)
            if not sc: continue
            if cpar and vpar and not (cpar & vpar): continue        # 人力施工 ⇔ 機械施工 の食い違い
            if cpar and not vpar: sc -= 1
            if vpar and cpar and (cpar & vpar): sc += 1
            best.append((sc, c))
        if best:
            top = max(s for s, c in best)
            if top >= 2:
                return [(c, '作業名一致') for s, c in best if s == top]
    return out

def best_codes(rec_kousyu, title, conds, codes, group_vol):
    """1レコードについて当てはまるコードを返す [(code, 方法)]。方法の先頭語で確からしさが分かる"""
    kt, kk = key(title), key(rec_kousyu)
    lk = loose(title)
    def sec_score(c):
        return section_ok(c, kk) + (0.5 if c['volume'] == group_vol else 0)
    usable = [c for c in codes if '材料費' not in c['name']]
    insec = [c for c in usable if section_ok(c, kk) >= 1 and c['volume'] == group_vol] or \
            [c for c in usable if section_ok(c, kk) >= 1]
    # (a) 条件欄の値がコード名と一致（例：工種＝不陸整正）
    for h, v in conds:
        kv = key(v)
        hits = [c for c in usable if key(c['name']) == kv]
        if hits:
            m = max(sec_score(c) for c in hits)
            if m >= 1:
                return [(c, '条件名一致') for c in hits if sec_score(c) == m]
    # (b) 見出し名がコード名と一致
    hits = ([c for c in usable if key(c['name']) == kt] or [c for c in usable if loose(c['name']) == lk]) if kt else []
    if hits:
        m = max(sec_score(c) for c in hits)
        return [(c, '名称一致') for c in hits if sec_score(c) == m]
    # (b2) 条件欄の作業名などがコード名の中心語と一致（例：作業名＝除根作業 → 除根(伐木除根)）
    hit = by_work_name(conds, insec, kk)
    if hit:
        return hit
    # (c) 同じ工種（節）の中で名称が似ているもの
    sc = sorted(((difflib.SequenceMatcher(None, loose(c['name']), lk).ratio(), c) for c in insec), key=lambda x: -x[0])
    if sc and sc[0][0] >= 0.75:
        top = sc[0][0]
        return [(c, f'類似名称({top:.2f})') for r, c in sc if r == top]
    # (d) 節内のコードのうち、入力条件の本文に条件値が多く書かれているもの
    vals = [loose(v) for h, v in conds if len(loose(v)) >= 2]
    if insec and vals:
        cnt = [(sum(1 for v in vals if v in loose(c.get('jtext', ''))), c) for c in insec]
        top = max(n for n, c in cnt)
        if top > 0:
            hit = [c for n, c in cnt if n == top]
            if len(hit) > 1 and lk:
                sim = [(difflib.SequenceMatcher(None, loose(c['name']), lk).ratio(), c) for c in hit]
                best = max(s for s, c in sim)
                hit = [c for s, c in sim if s >= best - 1e-9]
            if len(hit) <= 3:
                return [(c, f'入力条件一致({top}/{len(vals)})') for c in hit]
    # (e) 見出しの語を含むコード名（節内）
    part = [c for c in insec if lk and loose(c['name']) and (lk in loose(c['name']) or loose(c['name']) in lk)]
    if part:
        return [(c, '名称部分一致') for c in part]
    # (f) 工種名＝コード名
    hits = [c for c in usable if kk and key(c['name']) == kk]
    if hits:
        m2 = max(sec_score(c) for c in hits)
        return [(c, '工種名一致') for c in hits if sec_score(c) == m2]
    # (g) 節内の候補を全部（要選択）
    if insec and len(insec) <= 12:
        return [(c, '節内候補(要選択)') for c in insec]
    return []
