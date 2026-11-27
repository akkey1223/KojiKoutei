"""工事工程表.html を組み立てる。

src/工事工程表.src.html の目印を、次の内容に置き換えて1つのHTMLにする（ネットにつながっていないPCでも動くように）。
  @@PDFJS@@        vendor/pdf.min.mjs（pdf.js 本体）
  @@PDFWORKER@@    vendor/pdf.worker.min.mjs（pdf.js の処理用）
  @@CMAPS@@        vendor/cmaps/*.bcmap（日本語の文字の対応表。名前→base64 の JSON）
  @@INPPARSE@@     src/inpparse.js（入力データリストの読み取り）

使い方：python app/build.py
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src" / "工事工程表.src.html"
OUT = HERE / "工事工程表.html"


def main() -> None:
    html = SRC.read_text(encoding="utf-8")
    vendor = HERE / "vendor"
    parts = {
        "@@PDFJS@@": (vendor / "pdf.min.mjs").read_text(encoding="utf-8"),
        "@@PDFWORKER@@": (vendor / "pdf.worker.min.mjs").read_text(encoding="utf-8"),
        "@@CMAPS@@": json.dumps({p.stem: base64.b64encode(p.read_bytes()).decode("ascii")
                                 for p in sorted((vendor / "cmaps").glob("*.bcmap"))}),
        "@@INPPARSE@@": (HERE / "src" / "inpparse.js").read_text(encoding="utf-8"),
    }
    for k, v in parts.items():
        if html.count(k) != 1:
            raise SystemExit(f"目印 {k} がちょうど1つではありません")
        low = v.lower()
        if "</script" in low or "<!--" in low or "<script" in low:
            raise SystemExit(f"{k} の中身に <script や <!-- が含まれているため埋め込めません")
        html = html.replace(k, v)
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"{OUT.name}：{OUT.stat().st_size / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
