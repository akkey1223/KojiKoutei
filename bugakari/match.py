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
