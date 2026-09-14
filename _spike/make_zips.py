# -*- coding: utf-8 -*-
"""重建两个交付 zip。

用 Python 而非 PowerShell/tar 生成：本环境会把命令文本里的中文路径编码搞坏，
而 Python 源文件是 UTF-8，中文路径可靠，zipfile 亦默认以 UTF-8 记录条目名。
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 构建产物路径（与两个 spec 的 --distpath 一致）：
#   onedir  -> dist_onedir\盯盘\…
#   onefile -> 仓库根目录 盯盘.exe（spec 用 --distpath .）
GREEN_SRC = os.path.join(ROOT, "dist_onedir", "盯盘")
ONEFILE_SRC = os.path.join(ROOT, "盯盘.exe")
GREEN_OUT = os.path.join(ROOT, "盯盘-绿色版.zip")
ONEFILE_OUT = os.path.join(ROOT, "盯盘-发布包.zip")


def find_doc():
    cands = [f for f in os.listdir(ROOT)
             if f.endswith(".txt")
             and 1500 < os.path.getsize(os.path.join(ROOT, f)) < 8000]
    if len(cands) != 1:
        raise SystemExit(f"说明文档不唯一，无法判定: {cands}")
    return cands[0]


def inner_doc_name(name):
    """盯盘-使用说明.txt -> 使用说明.txt"""
    parts = name.split("-", 1)
    return parts[1] if len(parts) == 2 else name


def make_green(doc):
    if not os.path.isdir(GREEN_SRC):
        raise SystemExit(f"onedir 目录不存在: {GREEN_SRC}")
    inner = inner_doc_name(doc)
    base = os.path.dirname(GREEN_SRC)
    with zipfile.ZipFile(GREEN_OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, _dirnames, filenames in os.walk(GREEN_SRC):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, base).replace("\\", "/")
                z.write(full, arc)
        z.write(os.path.join(ROOT, doc), f"盯盘/{inner}")
    return GREEN_OUT


def make_onefile(doc):
    if not os.path.isfile(ONEFILE_SRC):
        raise SystemExit(f"onefile exe 不存在: {ONEFILE_SRC}")
    with zipfile.ZipFile(ONEFILE_OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(ONEFILE_SRC, "盯盘.exe")
        z.write(os.path.join(ROOT, doc), inner_doc_name(doc))
    return ONEFILE_OUT


def report(path, expect_doc):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        bad = z.testzip()
    mb = os.path.getsize(path) / 1024 / 1024
    has_doc = any(n.endswith(expect_doc) for n in names)
    has_exe = any(n.endswith(".exe") for n in names)
    print(f"{os.path.basename(path)}: {len(names)} 项, {mb:.2f}MB, "
          f"CRC={'OK' if bad is None else 'BAD:' + bad}, 含exe={has_exe}, 含说明={has_doc}")
    for n in names[:3]:
        print("   ", n.encode("ascii", "replace").decode("ascii"))
    return len(names), mb, has_exe, has_doc, bad is None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    doc = find_doc()
    print("说明文档:", doc)
    g = make_green(doc)
    o = make_onefile(doc)
    ok = True
    ng, mbg, exeg, docg, crcg = report(g, inner_doc_name(doc))
    no, mbo, exeo, doco, crco = report(o, inner_doc_name(doc))
    if not (crcg and crco and exeg and exeo and docg and doco and ng > 900 and mbg > 5 and mbo > 5):
        ok = False
    print("\n结论:", "两个交付包重建并校验通过" if ok else "存在异常，需人工复核")
    sys.exit(0 if ok else 1)
