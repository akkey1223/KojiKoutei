/* 入力データリスト（国交省システム出力）PDFの読み取り
   SoukatsuCheck（soukatsu/pdfgeom.py・parse_common.py・parse_inp.py）を pdf.js 用に移したもの。
   使い方：const r = await INP.parse(pdfjsLib, Uint8Array, {onPage, getDocOpts})
   戻り値：{items:[...], isChange, title, pages} */
const INP = (() => {
  const KUBUN = 0, KOSHU = 1, SHUBETSU = 2, SAIBETSU = 3, BUGAKARI = 4, INNER = 5, COMMENT = 6;
  const LEVEL_NAME = ['工事区分', '工種', '種別', '細別', '歩掛', '内訳', 'コメント'];
  const RE_DEPTH = /^\((\d+)\)$/;
  const RE_CODE = /^[A-Z]{1,3}\d{5,7}$/;
  const RE_J = /^(J\d{2})\s+(.+?)\s{2,}(.+?)\s*$/;
  const KIROUZAI = new Set(['労務', '材料', '損料', '賃料', '雑費', '機械', 'ｺﾒﾝﾄ', 'コメント', '運転', '登録']);
  const LEVEL_MAP = { '1': KUBUN, '2': KOSHU, '3': SHUBETSU, '4': SAIBETSU };
  const ASC = 0.859, DESC = 0.14;

  /* ---------- 比較用の正規化（soukatsu/normalize.py の norm 相当） ---------- */
  const TR = { '･': '・', '·': '・', '‧': '・', '•': '・', '［': '[', '］': ']', '【': '[', '】': ']', '〔': '(', '〕': ')', '｛': '{', '｝': '}', '＜': '<', '＞': '>',
    '－': '-', '‐': '-', '−': '-', '―': '-', 'ｰ': 'ー', '～': '~', '〜': '~', '，': ',', '、': ',', '､': ',', '；': ';', '：': ':', '＝': '=', '×': 'x', '✕': 'x',
    '㎥': 'm3', '㎡': 'm2', '㎞': 'km', '㎜': 'mm', '㎝': 'cm', 'ｍ': 'm' };
  function norm(s) {
    if (!s) return '';
    let t = s.normalize('NFKC');
    t = [...t].map(c => TR[c] ?? c).join('');
    t = t.replace(/[\s　]+/g, '');
    t = t.replace(/(?<=[ァ-ヴ])[-ｰ‐](?=[ァ-ヴ])/g, 'ー');
    return t.replace(/m³/g, 'm3').replace(/m²/g, 'm2').toLowerCase();
  }

  /* ---------- ページの文字と罫線（pdfgeom.py 相当） ---------- */
  const half = c => { const u = c.codePointAt(0); return u < 0x2000 || (u >= 0xff61 && u <= 0xff9f); };
  async function loadPage(page, index) {
    const vp = page.getViewport({ scale: 1 });
    const P = (x, y) => vp.convertToViewportPoint(x, y);
    const g = { index, width: vp.width, height: vp.height, spans: [], hlines: [], vlines: [] };
    /* 罫線：線分・細い矩形・枠の矩形 */
    const ol = await page.getOperatorList();
    const O = globalThis.__pdfOPS;
    let ctm = [1, 0, 0, 1, 0, 0];
    const stack = [];
    const mul = (m, n) => [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3], m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]];
    const tp = (x, y) => { const X = ctm[0] * x + ctm[2] * y + ctm[4], Y = ctm[1] * x + ctm[3] * y + ctm[5]; return P(X, Y) };
    let pend = null;
    const paintKind = fn => {
      if (fn === O.stroke || fn === O.closeStroke) return 's';
      if (fn === O.fill || fn === O.eoFill) return 'f';
      if (fn === O.fillStroke || fn === O.eoFillStroke || fn === O.closeFillStroke || fn === O.closeEOFillStroke) return 'fs';
      if (fn === O.endPath) return 'n';
      return null;
    };
    const emit = (segs, kind) => {
      for (const sg of segs) {
        if (sg[0] === 'l') {
          const [, A, B] = sg;
          if (Math.abs(A[1] - B[1]) < 0.8 && Math.abs(A[0] - B[0]) > 3) g.hlines.push([(A[1] + B[1]) / 2, Math.min(A[0], B[0]), Math.max(A[0], B[0])]);
          else if (Math.abs(A[0] - B[0]) < 0.8 && Math.abs(A[1] - B[1]) > 3) g.vlines.push([(A[0] + B[0]) / 2, Math.min(A[1], B[1]), Math.max(A[1], B[1])]);
        } else {
          const [, rx0, ry0, rx1, ry1] = sg, w = rx1 - rx0, h = ry1 - ry0;
          if (h <= 1.6 && w > 3) g.hlines.push([(ry0 + ry1) / 2, rx0, rx1]);
          else if (w <= 1.6 && h > 3) g.vlines.push([(rx0 + rx1) / 2, ry0, ry1]);
          else if ((kind === 's' || kind === 'fs') && w > 3 && h > 3) {
            g.hlines.push([ry0, rx0, rx1], [ry1, rx0, rx1]); g.vlines.push([rx0, ry0, ry1], [rx1, ry0, ry1]);
          }
        }
      }
    };
    for (let i = 0; i < ol.fnArray.length; i++) {
      const fn = ol.fnArray[i], args = ol.argsArray[i];
      if (fn === O.save) stack.push(ctm.slice());
      else if (fn === O.restore) { if (stack.length) ctm = stack.pop() }
      else if (fn === O.transform) ctm = mul(args, ctm);
      else if (fn === O.constructPath) {
        const [ops, co] = args; let k = 0, cp = null, start = null; const segs = [];
        for (const op of ops) {
          if (op === O.moveTo) { cp = tp(co[k], co[k + 1]); start = cp; k += 2 }
          else if (op === O.lineTo) { const np = tp(co[k], co[k + 1]); if (cp) segs.push(['l', cp, np]); cp = np; k += 2 }
          else if (op === O.curveTo) { cp = tp(co[k + 4], co[k + 5]); k += 6 }
          else if (op === O.curveTo2 || op === O.curveTo3) { cp = tp(co[k + 2], co[k + 3]); k += 4 }
          else if (op === O.closePath) { if (cp && start && (cp[0] !== start[0] || cp[1] !== start[1])) segs.push(['l', cp, start]); cp = start }
          else if (op === O.rectangle) {
            const x = co[k], y = co[k + 1], w = co[k + 2], h = co[k + 3]; k += 4;
            const ps = [tp(x, y), tp(x + w, y), tp(x + w, y + h), tp(x, y + h)];
            const xs = ps.map(p => p[0]), ys = ps.map(p => p[1]);
            segs.push(['r', Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
          }
        }
        pend = (pend || []).concat(segs);
        const k2 = paintKind(ol.fnArray[i + 1]);
        if (k2) { emit(pend, k2); pend = null; i++ }
      } else {
        const k2 = paintKind(fn);
        if (k2 && pend) { emit(pend, k2); pend = null }
      }
    }
    g.hlines = mergeSeg(g.hlines); g.vlines = mergeSeg(g.vlines);
    /* 文字：pdf.js は空白を別の要素に分け、長い空白は落とすので、同じ行で間に縦罫線の無い要素をつなぎ、すき間の幅から空白の数を戻す
       （PyMuPDF では1つのマスの文字は1つのスパンになる） */
    const ruleBetween = (xa, xb, ya, yb) => g.vlines.some(([x, a, b]) => x > xa - 0.3 && x < xb + 0.3 && a < yb && b > ya);
    /* 元の説明：pdf.js は空白を別の要素に分けるので、同じ行で接している要素をつなぎ、空白の幅から空白の数を戻す */
    const tc = await page.getTextContent({ disableNormalization: true });
    let cur = null;
    const flush = () => { if (cur && cur.text.length) g.spans.push(cur); cur = null; };
    for (const it of tc.items) {
      if (it.str === undefined) continue;
      const [a, b, c, d, e, f] = it.transform;
      const size = Math.hypot(c, d), hw = Math.hypot(a, b) / 2;   // 全角の半分＝半角の幅
      const [x0, base] = P(e, f), w = it.width;
      if (!it.str.length) { continue; }
      const isSp = !it.str.trim();
      if (isSp && ruleBetween(x0 + 0.3, x0 + w - 0.3, base - size * ASC, base + size * DESC)) { flush(); continue }   // 罫線をまたぐ空白はマスの区切り
      let text = it.str, chars = [];
      if (isSp) {
        const n = Math.max(1, Math.round(w / hw));
        text = /^\u3000+$/.test(it.str) && n <= 2 * it.str.length ? it.str : ' '.repeat(n);   // 全角空白はそのまま
        { const cs = [...text], k = cs.length; cs.forEach((ch, i) => chars.push([ch, x0 + i * w / k, x0 + (i + 1) * w / k])) }
      } else {
        const cs = [...text], units = cs.map(ch => half(ch) ? 1 : 2), tot = units.reduce((s, v) => s + v, 0) || 1;
        let x = x0;
        cs.forEach((ch, i) => { const cw = w * units[i] / tot; chars.push([ch, x, x + cw]); x += cw });
      }
      const y0 = base - size * ASC, y1 = base + size * DESC, x1 = x0 + w;
      if (cur && Math.abs(cur.base - base) < 0.6 && Math.abs(cur.size - size) < 0.3 && x0 >= cur.x1 - 1.5 && x0 - cur.x1 < 420 && !ruleBetween(cur.x1, x0, y0, y1)) {
        const gap = x0 - cur.x1;
        if (gap > hw * 0.6) { const n = Math.round(gap / hw); for (let i = 0; i < n; i++) { cur.chars.push([' ', cur.x1 + i * gap / n, cur.x1 + (i + 1) * gap / n]); } cur.text += ' '.repeat(n) }
        cur.text += text; cur.chars.push(...chars); cur.x1 = x1;
      } else {
        flush();
        cur = { text, x0, y0, x1, y1, size, page: index, base, chars };
      }
      if (it.hasEOL) flush();
    }
    flush();
    for (const s of g.spans) { s.xc = (s.x0 + s.x1) / 2; s.yc = (s.y0 + s.y1) / 2; s.h = s.y1 - s.y0 }
    return g;
  }
  function mergeSeg(segs, tolPos = 0.8, tolGap = 2.5) {
    const s = segs.slice().sort((p, q) => (Math.round(p[0] / tolPos) - Math.round(q[0] / tolPos)) || (p[1] - q[1]));
    const out = [];
    for (const [p, a, b] of s) {
      const l = out[out.length - 1];
      if (l && Math.abs(l[0] - p) <= tolPos && a <= l[2] + tolGap) l[2] = Math.max(l[2], b);
      else out.push([p, a, b]);
    }
    return out;
  }
  function hlineYs(g, x0, x1, y0 = -1e9, y1 = 1e9, minCover = 0.5) {
    const ys = [], sw = Math.max(1, x1 - x0);
    for (const [y, a, b] of g.hlines) { if (y < y0 || y > y1) continue; if (Math.min(b, x1) - Math.max(a, x0) >= sw * minCover) ys.push(y) }
    ys.sort((a, b) => a - b); const out = [];
    for (const y of ys) if (!out.length || y - out[out.length - 1] > 1.5) out.push(y);
    return out;
  }
  function vlineXs(g, y0, y1, minCover = 0.5) {
    const xs = [], sh = Math.max(1, y1 - y0);
    for (const [x, a, b] of g.vlines) if (Math.min(b, y1) - Math.max(a, y0) >= sh * minCover) xs.push(x);
    xs.sort((a, b) => a - b); const out = [];
    for (const x of xs) if (!out.length || x - out[out.length - 1] > 1.5) out.push(x);
    return out;
  }

  /* ---------- 表の共通処理（parse_common.py 相当） ---------- */
  function colIndex(cols, x) {
    for (let i = 0; i < cols.length; i++) { const [a, b] = cols[i]; if (a - 0.5 <= x && x < b + 0.5) return i }
    if (cols.length && x < cols[0][0]) return 0;
    return cols.length - 1;
  }
  const spansIn = (spans, x0, x1, y0, y1, by = 'start') => spans.filter(s => y0 - 0.5 <= s.yc && s.yc <= y1 + 0.5 && (() => { const x = by === 'start' ? s.x0 : s.xc; return x0 - 0.5 <= x && x < x1 + 0.5 })());
  function joinLines(spans, sep = '\n') {
    if (!spans.length) return '';
    const ss = spans.slice().sort((a, b) => (a.yc - b.yc) || (a.x0 - b.x0)), lines = [];
    for (const s of ss) { const l = lines[lines.length - 1]; if (l && Math.abs(l[0].yc - s.yc) < Math.max(2, s.h * 0.45)) l.push(s); else lines.push([s]) }
    return lines.map(l => l.sort((a, b) => a.x0 - b.x0).map(s => s.text).join(' ')).join(sep);
  }
  const cellText = spans => joinLines(spans.filter(s => s.text.trim()));

  /* ---------- 入力データリスト（parse_inp.py 相当） ---------- */
  function header(g) {
    const hd = {};
    for (const s of g.spans) {
      const t = norm(s.text);
      if (t === '区分' && !hd.kubun) hd.kubun = s;
      else if (t.startsWith('工事区分・工種・種別')) hd.name = s;
      else if (t === '単位') hd.unit = s;
      else if (t === '数量') hd.qty = s;
      else if (t === '摘要') hd.tekiyo = s;
      else if (t === '入力条件') hd.cond = s;
    }
    return ['kubun', 'name', 'unit', 'qty', 'tekiyo'].every(k => hd[k]) ? hd : null;
  }
  async function parse(pdfjs, data, opts = {}) {
    globalThis.__pdfOPS = pdfjs.OPS;
    const doc = await pdfjs.getDocument(Object.assign({ data, isEvalSupported: false, disableFontFace: true, useSystemFonts: false }, opts.getDocOpts || {})).promise;
    const pages = [];
    for (let i = 1; i <= doc.numPages; i++) { const p = await doc.getPage(i); pages.push(await loadPage(p, i - 1)); p.cleanup(); if (opts.onPage) opts.onPage(i, doc.numPages) }
    await doc.destroy();
    let title = '';
    const entries = []; let isChange = false;
    for (const g of pages) {
      const hd = header(g);
      if (!hd) continue;
      if (!title) { const t = g.spans.find(s => s.yc < hd.kubun.y0 && Math.abs(s.x0 - 84) < 60 && /工事/.test(s.text) && !/工事名|工事区分/.test(s.text)); if (t) title = t.text.trim() }
      for (const s of g.spans) if (s.text.includes('回変更') && s.y0 < hd.kubun.y0) isChange = true;
      const hys = g.spans.filter(s => Math.abs(s.y0 - hd.unit.y0) < 40 && s.y0 >= hd.unit.y0 - 2 && (s.text.includes('前回') || s.text.includes('入') || s === hd.unit)).map(s => s.y1);
      const hy = Math.max(...hys);
      const ys = hlineYs(g, hd.unit.x0 - 1, hd.unit.x1 + 1, hy - 1);
      if (ys.length < 2) continue;
      const xs = vlineXs(g, ys[0], ys[ys.length - 1], 0.5);
      const cols = []; for (let i = 0; i + 1 < xs.length; i++) if (xs[i + 1] - xs[i] > 4) cols.push([xs[i], xs[i + 1]]);
      const ci = {}; for (const k of Object.keys(hd)) if (k !== 'cond') ci[k] = colIndex(cols, hd[k].xc);
      ci.cond = ci.qty + 1;
      const geo = { cols, ci };
      for (let j = 0; j + 1 < ys.length; j++) {
        const ya = ys[j], yb = ys[j + 1];
        if (yb - ya < 4) continue;
        const row = g.spans.filter(s => ya - 0.5 <= s.yc && s.yc <= yb + 0.5 && s.text.trim());
        if (!row.length) continue;
        const [ka, kb] = cols[ci.kubun];
        const kub = spansIn(row, ka, kb, ya, yb);
        if (!kub.length) { if (entries.length) entries[entries.length - 1].e.parts.push([g.index, ya, yb, row]); continue }
        entries.push({ e: { parts: [[g.index, ya, yb, row]] }, geo });
      }
    }
    const items = [];
    for (const { e, geo } of entries) { const it = toItem(e, geo, isChange); if (it) items.push(it) }
    /* 木構造：数字区分は階層どおり、歩掛は直前の細別の子 */
    const stack = []; let lastSai = null, byDepth = {};
    items.forEach((it, i) => {
      it.seq = i;
      if (it.level === COMMENT) { if (lastSai) lastSai.comments.push(it.name); return }
      if (it.level === INNER || it.level === BUGAKARI) {
        if (it.level === BUGAKARI) { it.parent = lastSai; if (lastSai) lastSai.children.push(it) }
        it.box = byDepth[it.depth - 1] || null;
        if (it.box) it.box.subs.push(it);
        byDepth[it.depth] = it;
        for (const d of Object.keys(byDepth)) if (+d > it.depth) delete byDepth[d];
        return;
      }
      byDepth = it.level === SAIBETSU ? { 0: it } : {};
      while (stack.length && stack[stack.length - 1].level >= it.level) stack.pop();
      it.parent = stack.length ? stack[stack.length - 1] : null;
      if (it.parent) it.parent.children.push(it);
      stack.push(it);
      lastSai = it.level === SAIBETSU ? it : null;
    });
    return { items: items.filter(it => it.level !== COMMENT), isChange, title, pages: pages.length };
  }
  function toItem(e, geo, isChange) {
    const { cols, ci } = geo;
    const [pg, ya, yb, row] = e.parts[0];
    const [ka, kb] = cols[ci.kubun];
    const kubLines = joinLines(spansIn(row, ka, kb, ya, yb)).split('\n');
    const kind = kubLines[0].trim();
    let depth = null;
    for (const t of kubLines.slice(1)) { const m = RE_DEPTH.exec(t.trim()); if (m) depth = +m[1] }
    let level;
    if (LEVEL_MAP[kind] != null) level = LEVEL_MAP[kind];
    else if (depth != null && depth >= 1 && !KIROUZAI.has(kind)) level = BUGAKARI;
    else if (depth != null && depth >= 1 && kind !== 'ｺﾒﾝﾄ' && kind !== 'コメント') level = INNER;
    else if (depth != null && depth >= 1) level = COMMENT;
    else return null;
    const [na, nb] = cols[ci.name], [ua, ub] = cols[ci.unit];
    const nsp = [], extraUnit = [];
    for (const sp of spansIn(row, na, nb, ya, yb)) {
      if (sp.x1 > nb + 2) { const [a, b] = splitAt(sp, nb); if (a.text.trim()) nsp.push(a); if (b.text.trim()) extraUnit.push(b) }
      else nsp.push(sp);
    }
    const lines = cellText(nsp).split('\n').map(t => t.replace(/^[　 ]+|[　 ]+$/g, '')).filter(Boolean);
    let nameMain = '', specTxt = '';
    if (nsp.length) {
      /* 名称欄は4段。名称は最大2段（1段目が右端まで詰まって折り返しているか、括弧が閉じていないときだけ2段目も名称）、残りが規格 */
      const ksp = spansIn(row, ka, kb, ya, yb).sort((a, b) => a.y0 - b.y0);
      const refY = ksp.length ? ksp[0].y0 : Math.min(...nsp.map(s => s.y0));
      const pitch = ksp.length >= 2 && ksp[1].y0 - ksp[0].y0 > 4 ? ksp[1].y0 - ksp[0].y0 : 12;
      const slot = sp => Math.max(0, Math.round((sp.y0 - refY) / pitch));
      const bySlot = {};
      for (const sp of nsp) (bySlot[slot(sp)] = bySlot[slot(sp)] || []).push(sp);
      const wrapped = sps => {
        const t = sps.slice().sort((a, b) => a.x0 - b.x0).map(x => x.text).join('').replace(/^[　 ]+|[　 ]+$/g, '');
        const opens = [...t].filter(c => '（(［[【｛{'.includes(c)).length, closes = [...t].filter(c => '）)］]】｝}'.includes(c)).length;
        const vis = sps.flatMap(x => x.chars).filter(c => c[0].trim());
        const right = vis.length ? Math.max(...vis.map(c => c[2])) : Math.max(...sps.map(x => x.x1));
        const fsz = Math.max(...sps.map(x => x.size));
        return opens > closes || right >= nb - fsz * 1.05;
      };
      const ss = Object.keys(bySlot).map(Number).sort((a, b) => a - b);
      let nName = 1;
      if (ss.length >= 2 && ss[1] === ss[0] + 1 && wrapped(bySlot[ss[0]])) nName = 2;
      const nameSlots = new Set(ss.slice(0, nName));
      let l1 = nsp.filter(s => nameSlots.has(slot(s))), rest = nsp.filter(s => !nameSlots.has(slot(s)));
      if (!l1.length) { l1 = rest.slice(0, 1); rest = rest.slice(1) }
      const txt = sps => sps.slice().sort((a, b) => (a.y0 - b.y0) || (a.x0 - b.x0)).map(sp => sp.text.replace(/^[　 ]+|[　 ]+$/g, '')).filter(Boolean).join('');
      nameMain = txt(l1); specTxt = txt(rest);
    }
    const unit = cellText(spansIn(row, ua, ub, ya, yb).concat(extraUnit)).trim();
    const [qa, qb] = cols[ci.qty];
    const qsp = spansIn(row, qa, qb, ya, yb).filter(s => /\d/.test(s.text)).sort((a, b) => a.y0 - b.y0).map(s => s.text.trim());
    const it = { level, levelName: LEVEL_NAME[level], kind, depth: depth || 0, page: pg, name: lines.join('\n'), nameMain, spec: specTxt, unit, qtyPrev: '', qty: '',
      code: '', conds: [], condCodes: [], unitQty: '', kikaku: '', children: [], subs: [], comments: [], parent: null, box: null };
    if (level === BUGAKARI) { if (qsp.length) it.qty = qsp[qsp.length - 1] }
    else if (isChange && qsp.length >= 2) { it.qtyPrev = qsp[0]; it.qty = qsp[1] }
    else if (qsp.length) it.qty = qsp[0];
    const [ca, cb] = cols[ci.cond], [ta, tb] = cols[ci.tekiyo];
    let condSp = [], tekSp = [];
    for (const [p, a, b, r] of e.parts) { condSp = condSp.concat(spansIn(r, ca, cb, a, b)); tekSp = tekSp.concat(spansIn(r, ta, tb, a, b)) }
    for (const s of tekSp) { const c = norm(s.text).toUpperCase(); if (RE_CODE.test(c)) { it.code = c; break } }
    for (const s of tekSp) { const m = /^\s*単位数量\s+([\d,.]+)/.exec(s.text); if (m) { it.unitQty = m[1]; break } }
    if (level === SAIBETSU) {
      const cs = condSp.filter(s => s.page === pg).sort((a, b) => (a.y0 - b.y0) || (a.x0 - b.x0)), kik = [];
      for (const s of cs) { const t = s.text.trim(); if (/^Q\d{2}\b/.test(t) || t.startsWith('工種区分')) break; if (/^[\d,.\s\-()（）]+$/.test(t) || t.includes('合意率')) continue; kik.push(s) }
      it.kikaku = cellText(kik);
    } else if (level === INNER) it.kikaku = lines.slice(1).join('\n');
    else if (level === BUGAKARI) {
      for (const s of condSp.slice().sort((a, b) => (a.page - b.page) || (a.y0 - b.y0))) {
        const m = RE_J.exec(s.text.trim());
        if (m) { it.conds.push([m[2].trim(), m[3].trim()]); it.condCodes.push(m[1]); continue }
        /* 条件名が途中で切れて値との間が空白1つの行（例「J01 樹木・竹の区分　樹木密集度及び 伐木（機械施工）」）は、最後の空白の後ろを値にする */
        const m2 = /^(J\d{2})\s+(.+)\s(\S+)$/.exec(s.text.trim());
        if (m2) { it.conds.push([m2[2].trim(), m2[3].trim()]); it.condCodes.push(m2[1]) }
      }
      it.kikaku = lines.slice(1).join('\n');
    }
    return it;
  }
  function splitAt(sp, x) {
    const t = sp.text, n = Math.max(1, t.length), w = (sp.x1 - sp.x0) / n, k = Math.max(0, Math.min(n, Math.round((x - sp.x0) / w)));
    const mk = (tx, a, b) => Object.assign({}, sp, { text: tx, x0: a, x1: b, xc: (a + b) / 2, chars: [] });
    return [mk(t.slice(0, k), sp.x0, sp.x0 + w * k), mk(t.slice(k), sp.x0 + w * k, sp.x1)];
  }
  const num = s => { const v = parseFloat(String(s || '').replace(/[,\s]/g, '')); return isFinite(v) ? v : null };
  return { parse, norm, num, LEVEL_NAME, KUBUN, KOSHU, SHUBETSU, SAIBETSU, BUGAKARI, INNER };
})();
if (typeof module !== 'undefined') module.exports = INP;
