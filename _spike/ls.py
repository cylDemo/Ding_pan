# -*- coding: utf-8 -*-
"""列出项目根目录文件（含中文名），结果落盘为 UTF-8，避免控制台编码糊码。"""
import datetime
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_spike", "ls.txt")

rows = []
for f in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, f)
    kind = "DIR " if os.path.isdir(p) else "FILE"
    if os.path.isdir(p):
        try:
            sz = sum(os.path.getsize(os.path.join(r, x))
                     for r, _d, fs in os.walk(p) for x in fs)
            cnt = sum(len(fs) for _r, _d, fs in os.walk(p))
        except Exception:
            sz, cnt = 0, 0
    else:
        sz, cnt = os.path.getsize(p), 1
    t = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
    rows.append((kind, sz, cnt, t, f))

with open(OUT, "w", encoding="utf-8") as fh:
    for kind, sz, cnt, t, f in rows:
        fh.write(f"{kind} {sz:>12} {cnt:>5}份 {t}  {f}\n")
print("written:", OUT, len(rows), "entries")
