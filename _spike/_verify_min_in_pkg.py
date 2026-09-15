# -*- coding: utf-8 -*-
r"""验证「最小化到任务栏」改动确实进入了打包产物。

做法：解 CArchive -> 导出 PYZ 到临时文件 -> 遍历 code object 的
co_names/co_consts 收集字面量后再匹配（PYZ 是 zlib 压缩的，
直接在 exe 上搜明文字符串会假阴性）。

带阳性 / 阴性对照，避免"扫不到"被误读为"没包含"。

用法：
  .build_venv\Scripts\python.exe _spike\_verify_min_in_pkg.py <exe路径>
"""
import marshal
import os
import sys
import tempfile
import types

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

# 本轮改动引入的标识（必须命中）
# 说明：_minimize_to_taskbar / btn_min / ShowWindow 是属性名（落 co_names），
#       WS_EX_APPWINDOW / SW_MINIMIZE 是局部变量名（落 co_varnames）。
POSITIVE = ["_minimize_to_taskbar", "btn_min", "ShowWindow",
            "WS_EX_APPWINDOW", "SW_MINIMIZE"]
# 阴性对照（必须 0 命中，否则说明扫描器会误报）
NEGATIVE = ["_definitely_not_a_real_method_xyz", "clawx_def"]


def iter_code(co):
    yield co
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            yield from iter_code(c)


def strings_of(co):
    out = []
    for c in iter_code(co):
        for k in c.co_consts:
            if isinstance(k, str):
                out.append(k)
            elif isinstance(k, bytes):
                out.append(k.decode("utf-8", "replace"))
        out.extend(c.co_names or ())
        out.extend(c.co_varnames or ())   # 局部变量名不入 co_names，须单独采集
    return out


def scan_code(obj, agg):
    """obj 为 marshal 后的 code object 时计入命中，否则忽略。"""
    if isinstance(obj, (bytes, bytearray)):
        try:
            obj = marshal.loads(bytes(obj))
        except Exception:
            return False
    if not isinstance(obj, types.CodeType):
        return False
    s = strings_of(obj)
    for k in agg:
        agg[k] += sum(1 for x in s if x == k)
    return True


def main(exe):
    print("=" * 72)
    print("扫描目标:", exe, "  %.2f MB" % (os.path.getsize(exe) / 1e6))
    print("=" * 72)

    arch = CArchiveReader(exe)
    top = list(arch.toc)
    pyz = [n for n in top if n.lower().endswith(".pyz")]
    print("顶层条目数: %d   PYZ 条目: %s" % (len(top), pyz or "(无)"))
    if not pyz:
        print("结论: FAIL —— 未找到 PYZ")
        return 1

    agg = {k: 0 for k in POSITIVE + NEGATIVE}

    # ── (1) CArchive 顶层脚本/模块条目 ──
    # 关键：主脚本（此处为 gold_widget）**不进 PYZ**，而是作为 PYSOURCE 条目
    # 留在 CArchive 顶层。只扫 PYZ 会漏掉它 → 假阴性。
    top_scanned = []
    for name in top:
        if name.lower().endswith(".pyz"):
            continue
        try:
            blob = arch.extract(name)
        except Exception:
            continue
        if not blob:
            continue
        if scan_code(blob, agg):
            top_scanned.append(name)
    print("顶层可解析为 code object 的条目: %s" % (top_scanned or "(无)"))

    # ── (2) PYZ 内模块 ──
    for pz in pyz:
        blob = arch.extract(pz)
        if not blob:
            continue
        fd, tmp = tempfile.mkstemp(suffix=".pyz")
        os.close(fd)
        with open(tmp, "wb") as f:
            f.write(blob)
        try:
            z = ZlibArchiveReader(tmp)
            mods = sorted(z.toc)
            print("PYZ 内模块数: %d" % len(mods))
            print("  gold_* 与 jdgold 闭包:",
                  [m for m in mods if m.startswith("gold_")
                   or m in ("query_price_jhub", "jos", "bff_client", "secure_store")])
            for m in mods:
                try:
                    obj = z.extract(m)
                except Exception as e:
                    print("  [!] extract 失败 %s: %s" % (m, e))
                    continue
                scan_code(obj, agg)
        finally:
            os.remove(tmp)

    print("\n-- 命中统计 --")
    print("  [阳性 —— 应 >0]")
    for k in POSITIVE:
        print("     %-28s %d" % (k, agg[k]))
    print("  [阴性对照 —— 应 =0]")
    for k in NEGATIVE:
        print("     %-28s %d" % (k, agg[k]))

    has_pos = all(agg[k] > 0 for k in POSITIVE)
    clean_neg = all(agg[k] == 0 for k in NEGATIVE)
    ok = has_pos and clean_neg
    print()
    if ok:
        print("结论: PASS —— 最小化改动已进入该产物")
    elif clean_neg:
        print("结论: FAIL —— 产物未包含该改动")
    else:
        print("结论: FAIL —— 阴性对照被命中，扫描结果不可信")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: _verify_min_in_pkg.py <exe路径>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
