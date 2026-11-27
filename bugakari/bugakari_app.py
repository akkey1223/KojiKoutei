"""
歩掛 日当り施工量 抽出アプリ
  土木工事標準積算基準書（共通編・河川編・道路編 …）の PDF から
  歩掛コード（施工パッケージ CB… ／ 施工歩掛 WB…）ごとの日当り施工量を抽出し、
  根拠ページつきの表（Excel・CSV・JSON）にまとめる。年度ごとに出力フォルダを分ける。

使い方
  GUI   : python bugakari_app.py
  CLI   : python bugakari_app.py 共通編.pdf 河川編.pdf 道路編.pdf  [-o 出力フォルダ]
"""
import os, re, sys, json, csv, argparse, datetime, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ext14, ext_codes, ext_buk, match

APP_VER = '1.1'

RANK_TEXT = {
    'A': '名称が一致（コードと日当り表の項目名が同じ）',
    'B': '名称が類似・部分一致、または入力条件の文言が一致',
    'C': '同じ工種の中の候補（どのコードか人が選ぶ）',
    '計算': '設置・撤去を1コードで扱う歩掛の合成値 1/(1/設置+1/撤去)',
}

def rank_of(how):
    if how.startswith(('名称一致', '条件名一致', '作業名一致')): return 'A'
    m = re.match(r'類似名称\((\d\.\d+)\)', how)
    if m: return 'A' if float(m.group(1)) >= 0.95 else 'B'
    if how.startswith(('入力条件一致', '名称部分一致', '工種名一致')): return 'B'
    return 'C'

def cond_text(cond):
    out = []
    for h, v in cond:
        out.append(f'{h}：{v}' if h else v)
    return '／'.join(out)

def nendo_key(n):
    """'令和8年度' → 'R08'"""
    z = unicodedata.normalize('NFKC', n or '')
    m = re.search(r'令和(\d+|元)年度', z)
    if m:
        y = 1 if m.group(1) == '元' else int(m.group(1))
        return f'R{y:02d}'
    return z or '年度不明'


def build(pdfs, outdir=None, progress=print):
    t0 = datetime.datetime.now()
    vols = []
    kyotsu = None
    for path in pdfs:
        progress(f'読込中: {os.path.basename(path)}')
        d = ext_codes.extract(path, progress=progress)
        d['path'] = path
        vols.append(d)
        progress(f'  → {d["volume"] or "編名不明"} {d["nendo"]}  {d["pages"]}頁  コード {len(d["codes"])}件')
        if d['volume'] == '共通編':
            kyotsu = d
    if kyotsu is None:
        raise SystemExit('共通編のPDFが見つかりません（日当り標準作業量の表 第Ⅰ編14章④ は共通編に載っています）。')
    nendos = {v['nendo'] for v in vols if v['nendo']}
    if len(nendos) > 1:
        raise SystemExit(f'年度の違うPDFが混ざっています: {sorted(nendos)}')
    nendo = kyotsu['nendo']

    # 第Ⅰ編14章④ の頁と、編の区分（1 共通編 / 2 河川編 / 3 道路編 …）
    pages = kyotsu['_pages']
    idx = [i for i, pg in enumerate(pages) if ext_codes.page_label(pg).startswith('Ⅰ-14-④-')]
    if not idx:
        raise SystemExit('共通編の中に 第Ⅰ編14章④「作業日当り標準作業量」の頁が見つかりません。')
    toc = '\n'.join(pages[i] for i in idx[:5])
    grp_name = dict(re.findall(r'(\d)\s*【([^】]+)】', toc))
    grp_start = sorted((int(p), g) for g, p in re.findall(r'(\d)-\s*1\s+\S.*?Ⅰ-14-④-\s*(\d+)', toc))
    def group_of(label):
        n = int(re.match(r'(\d+)', label.split('④-')[1]).group(1))
        g = ''
        for st, gg in grp_start:
            if n >= st: g = gg
        return grp_name.get(g, '')

    progress('日当り標準作業量の表を読み取り中（第Ⅰ編14章④）')
    r14 = ext14.run(kyotsu['path'], idx, progress=progress)
    recs, warns = r14['records'], r14['warnings']
    progress(f'  → {len(recs)}行  要確認の表 {len(warns)}件')

    codes = [c for v in vols for c in v['codes']]
    progress('歩掛コードと突き合わせ中')
    rows = []          # コード別（1コード×1条件 = 1行）
    allrows = []       # 日当り表の全行
    for no, x in enumerate(recs, 1):
        grp = group_of(x['page_label'])
        res = match.best_codes(x['kousyu'], x['title'], x['cond'], codes, grp)
        base = dict(
            no=no, nendo=nendo, group=grp, kousyu=x['kousyu'], title=x['title'],
            cond=cond_text(x['cond']), valhead=x['valhead'], value=x['value'], unit=x['unit'],
            src_label=x['page_label'], src_pdf=x['page_pdf'], src_vol='共通編', seq=no,
            extract=x['mode'],
        )
        allrows.append(dict(base, codes='、'.join(f'{c["code"]}' for c, _ in res),
                            how=res[0][1] if res else '', rank=rank_of(res[0][1]) if res else ''))
        for c, how in res:
            rows.append(dict(base, code=c['code'], kind=c['kind'], cname=c['name'], cunit=c['unit'],
                             cvol=c['volume'], csec=c['section'], csub=c['subsection'],
                             clabel=c['page_label'], cpdf=c['page_pdf'], how=how, rank=rank_of(how)))
    # 施工歩掛（WB…）は、各歩掛のページにある日当り施工量の表を優先する
    progress('施工歩掛のページの日当り施工量を読み取り中')
    cmap = {c['code']: c for c in codes}
    bukrows = []
    for v in vols:
        got, _tables = ext_buk.extract(v, v['path'])
        for code, lst in got.items():
            c = cmap[code]
            for k, x in enumerate(lst, 1):
                how = x['how']
                rank = 'A' if how == '単価表の参照表' else ('計算' if how.startswith('計算') else 'B')
                bukrows.append(dict(
                    no='', nendo=nendo, group=v['volume'], kousyu=c['section'], title=x['item'],
                    cond=cond_text(x['cond']), valhead=x['valhead'], value=x['value'], unit=x['unit'],
                    src_label=x['src_label'], src_pdf=x['src_pdf'], src_vol=v['volume'], seq=k, extract=x['mode'],
                    code=code, kind=c['kind'], cname=c['name'], cunit=c['unit'], cvol=c['volume'],
                    csec=c['section'], csub=c['subsection'], clabel=c['page_label'], cpdf=c['page_pdf'],
                    how=how, rank=rank))
    own = {r['code'] for r in bukrows}
    rows = [r for r in rows if r['code'] not in own] + bukrows
    progress(f'  → 施工歩掛 {len(own)}コード {len(bukrows)}行')
    linked = {}
    for r in rows: linked[r['code']] = linked.get(r['code'], 0) + 1
    # 並びはコードごとに元の表の順（＝入力条件の選択肢の順）のまま
    rows.sort(key=lambda r: (r['code'], r['seq']))

    # ---- 出力 ----
    nk = nendo_key(nendo)
    outdir = outdir or os.path.join(os.path.dirname(os.path.abspath(pdfs[0])), '日当り施工量_出力')
    outdir = os.path.join(outdir, f'{nk}_{nendo}')
    os.makedirs(outdir, exist_ok=True)
    stem = f'日当り施工量_{nendo}'
    info = dict(
        app=f'歩掛 日当り施工量 抽出アプリ v{APP_VER}', nendo=nendo, created=t0.strftime('%Y-%m-%d %H:%M'),
        sources=[dict(file=os.path.basename(v['path']), volume=v['volume'], pages=v['pages'], codes=len(v['codes'])) for v in vols],
        counts=dict(daily_rows=len(recs), wb_page_rows=len(bukrows), code_rows=len(rows), codes=len(codes),
                    codes_with_daily=len(linked), warnings=len(warns)),
    )
    write_excel(os.path.join(outdir, stem + '.xlsx'), info, rows, allrows, codes, linked, warns)
    write_csv(os.path.join(outdir, stem + '_コード別.csv'), rows)
    write_json(os.path.join(outdir, f'{nk}_日当り.json'), info, rows)
    progress(f'出力しました: {outdir}')
    return outdir, info


COLS_CODE = [
    ('年度', 'nendo', 10), ('歩掛コード', 'code', 11), ('種別', 'kind', 12), ('コード名称', 'cname', 30),
    ('施工単位', 'cunit', 7), ('掲載編', 'cvol', 8), ('節（工種）', 'csec', 22), ('小節', 'csub', 22),
    ('コード掲載頁', 'clabel', 13), ('コード掲載頁(PDF)', 'cpdf', 9),
    ('日当り表の工種名', 'kousyu', 22), ('日当り表の項目', 'title', 26), ('施工条件', 'cond', 48), ('値の区分', 'valhead', 18),
    ('日当り施工量', 'value', 10), ('単位', 'unit', 9),
    ('根拠頁（日当り）', 'src_label', 14), ('根拠の編', 'src_vol', 8), ('根拠頁(PDF)', 'src_pdf', 9),
    ('紐付け方法', 'how', 18), ('確度', 'rank', 5), ('表の読取り', 'extract', 16), ('並び順', 'seq', 7),
]
COLS_ALL = [
    ('通し番号', 'no', 7), ('年度', 'nendo', 10), ('編区分', 'group', 8), ('工種名', 'kousyu', 24), ('項目', 'title', 28),
    ('施工条件', 'cond', 50), ('値の区分', 'valhead', 18), ('日当り施工量', 'value', 10), ('単位', 'unit', 9),
    ('根拠頁', 'src_label', 14), ('根拠頁(PDF)', 'src_pdf', 9), ('対応する歩掛コード', 'codes', 26),
    ('紐付け方法', 'how', 18), ('確度', 'rank', 5), ('表の読取り', 'extract', 12),
]


def write_excel(path, info, rows, allrows, codes, linked, warns):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    head_fill = PatternFill('solid', fgColor='DDEBF7')
    bold = Font(bold=True)
    thin = Side(style='thin', color='BFBFBF')
    rank_fill = {'A': None, 'B': PatternFill('solid', fgColor='FFF2CC'), 'C': PatternFill('solid', fgColor='FCE4D6'), '計算': PatternFill('solid', fgColor='E2EFDA')}

    def sheet(ws, cols, data, rank_key='rank'):
        ws.append([c[0] for c in cols])
        for i, (_, _, w) in enumerate(cols, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
            c = ws.cell(1, i); c.font = bold; c.fill = head_fill
            c.alignment = Alignment(wrap_text=True, vertical='center')
        for d in data:
            ws.append([d.get(k, '') for _, k, _ in cols])
            f = rank_fill.get(d.get(rank_key, ''))
            if f:
                for i in range(1, len(cols) + 1): ws.cell(ws.max_row, i).fill = f
        ws.freeze_panes = 'C2'
        ws.auto_filter.ref = ws.dimensions

    # 説明
    ws = wb.active; ws.title = '説明'
    lines = [
        ('歩掛 日当り施工量 一覧', ''),
        ('年度', info['nendo']), ('作成日時', info['created']), ('作成', info['app']), ('', ''),
        ('元資料', '')] + [(f"  {s['volume']}", f"{s['file']}（{s['pages']}頁・コード{s['codes']}件）") for s in info['sources']] + [
        ('', ''),
        ('日当り施工量の出典', '共通編 第Ⅰ編 第14章 ④「作業日当り標準作業量」の表'),
        ('', '施工歩掛（WB…）は、各歩掛のページの日当り施工量の表を優先（単価表の摘要にある表番号で紐付け）'),
        ('並び順', 'コードごとに元の表の順のまま（入力条件の選択肢の順）'),
        ('歩掛コードの出典', '各編の「施工単価入力基準表」（パッケージコード・施工歩掛コード）'),
        ('', ''),
        ('件数', ''),
        ('  日当り表の行数', info['counts']['daily_rows']),
        ('  施工歩掛ページの行数', info['counts']['wb_page_rows']),
        ('  コード別の行数', info['counts']['code_rows']),
        ('  コード総数', info['counts']['codes']),
        ('  日当りが紐付いたコード数', info['counts']['codes_with_daily']),
        ('  自動で読み切れなかった表', info['counts']['warnings']),
        ('', ''),
        ('確度', ''),
    ] + [(f'  {k}', v) for k, v in RANK_TEXT.items()] + [
        ('', ''),
        ('注意', '日当り表の値は自動読取りです。工程の根拠に使うときは「根拠頁」で原本を確かめてください。'),
        ('', '確度B・C の行（色付き）と「要確認」シートの表は、特に原本との照合をお勧めします。'),
        ('', '「表の読取り」が 横・続き の表は、見出しの組み合わせを自動で補っています。'),
    ]
    for a, b in lines: ws.append([a, b])
    ws['A1'].font = Font(bold=True, size=14)
    ws.column_dimensions['A'].width = 28; ws.column_dimensions['B'].width = 90

    sheet(wb.create_sheet('コード別日当り施工量'), COLS_CODE, rows)
    sheet(wb.create_sheet('日当り表（全行）'), COLS_ALL, allrows)

    ws = wb.create_sheet('コード一覧')
    cols = [('歩掛コード', 'code', 11), ('種別', 'kind', 12), ('コード名称', 'name', 34), ('施工単位', 'unit', 8),
            ('掲載編', 'volume', 8), ('節（工種）', 'section', 24), ('小節', 'subsection', 24), ('掲載頁', 'page_label', 13),
            ('掲載頁(PDF)', 'page_pdf', 9), ('日当り行数', 'n', 9), ('出典', 'source', 16)]
    data = [dict(c, n=linked.get(c['code'], 0)) for c in sorted(codes, key=lambda c: c['code'])]
    sheet(ws, cols, data, rank_key='_')
    for r in range(2, ws.max_row + 1):
        if not ws.cell(r, 10).value:
            for i in range(1, len(cols) + 1): ws.cell(r, i).font = Font(color='808080')

    ws = wb.create_sheet('要確認')
    ws.append(['■ 自動で読み切れなかった表（原本の頁を直接ご確認ください）'])
    ws.append(['根拠頁', '共通編PDF頁', '工種名', '項目', '数値セル数', '読み取れた行数'])
    for w in warns:
        ws.append([w['page_label'], w['page_pdf'], w['kousyu'], w['title'], w['cells'], w['extracted']])
    ws.append([]); ws.append(['■ 歩掛コードが見つからなかった項目'])
    ws.append(['根拠頁', '共通編PDF頁', '工種名', '項目', '行数'])
    seen = {}
    for a in allrows:
        if not a['codes']:
            k = (a['src_label'], a['src_pdf'], a['kousyu'], a['title'])
            seen[k] = seen.get(k, 0) + 1
    for k, n in seen.items(): ws.append(list(k) + [n])
    for i, w in enumerate([14, 11, 34, 40, 11, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in ws.iter_rows():
        for c in r:
            if isinstance(c.value, str) and c.value.startswith('■'): c.font = bold
    wb.save(path)


def write_csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in COLS_CODE])
        for d in rows: w.writerow([d.get(k, '') for _, k, _ in COLS_CODE])


def write_json(path, info, rows):
    """工程アプリ読み込み用：コード → 条件ごとの日当り施工量"""
    by = {}
    for r in rows:
        e = by.setdefault(r['code'], dict(code=r['code'], name=r['cname'], unit=r['cunit'], kind=r['kind'],
                                          page=r['clabel'], volume=r['cvol'], daily=[]))
        e['daily'].append(dict(item=r['title'], cond=r['cond'], valhead=r['valhead'], value=r['value'],
                               unit=r['unit'], src=r['src_label'], src_vol=r['src_vol'], src_pdf=r['src_pdf'],
                               how=r['how'], rank=r['rank']))
    json.dump(dict(info=info, codes=list(by.values())), open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ---------------- GUI ----------------
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    import threading
    root = tk.Tk(); root.title(f'歩掛 日当り施工量 抽出 v{APP_VER}'); root.geometry('720x480')
    files = []
    outvar = tk.StringVar(value='')
    frm = tk.Frame(root); frm.pack(fill='x', padx=10, pady=8)
    tk.Label(frm, text='① 同じ年度の積算基準書PDF（共通編は必須、河川編・道路編など）').pack(anchor='w')
    lb = tk.Listbox(frm, height=5); lb.pack(fill='x')
    def add():
        for p in filedialog.askopenfilenames(filetypes=[('PDF', '*.pdf')]):
            if p not in files: files.append(p); lb.insert('end', p)
    def clear():
        files.clear(); lb.delete(0, 'end')
    b = tk.Frame(frm); b.pack(anchor='w', pady=4)
    tk.Button(b, text='PDFを追加', command=add).pack(side='left')
    tk.Button(b, text='クリア', command=clear).pack(side='left', padx=6)
    tk.Label(frm, text='② 出力フォルダ（空欄なら最初のPDFと同じ場所に「日当り施工量_出力」）').pack(anchor='w', pady=(8, 0))
    o = tk.Frame(frm); o.pack(fill='x')
    tk.Entry(o, textvariable=outvar).pack(side='left', fill='x', expand=True)
    tk.Button(o, text='参照', command=lambda: outvar.set(filedialog.askdirectory() or outvar.get())).pack(side='left')
    log = scrolledtext.ScrolledText(root, height=12); log.pack(fill='both', expand=True, padx=10, pady=6)
    def say(s):
        log.insert('end', s + '\n'); log.see('end')
    def run():
        if not files:
            messagebox.showwarning('PDF未選択', 'PDFを選んでください'); return
        btn.config(state='disabled')
        def work():
            try:
                out, info = build(files, outvar.get() or None, progress=lambda s: root.after(0, say, s))
                root.after(0, lambda: messagebox.showinfo('完了', f'出力しました\n{out}'))
                if sys.platform.startswith('win'): os.startfile(out)
            except BaseException as e:
                root.after(0, lambda: messagebox.showerror('エラー', str(e)))
            finally:
                root.after(0, lambda: btn.config(state='normal'))
        threading.Thread(target=work, daemon=True).start()
    btn = tk.Button(root, text='③ 抽出して表を作る', command=run, height=2); btn.pack(fill='x', padx=10, pady=(0, 10))
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) == 1:
        gui()
    else:
        ap = argparse.ArgumentParser(description='積算基準書PDFから歩掛コード別の日当り施工量を抽出')
        ap.add_argument('pdf', nargs='+', help='同じ年度の積算基準書PDF（共通編は必須）')
        ap.add_argument('-o', '--out', help='出力フォルダ')
        a = ap.parse_args()
        build(a.pdf, a.out)
