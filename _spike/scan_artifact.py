# -*- coding: utf-8 -*-
"""产物凭据扫描器（P1-A spike 用）。

思路：
1) 列出 PyInstaller CArchive 顶层条目（datas/binaries/PYZ 都在这里）；
2) 解开 PYZ（ZlibArchive），对每个模块**递归遍历 code object 的常量表**，
   收集全部字符串字面量，再在其中匹配凭据/敏感特征。

为什么不用"直接在 exe 上搜明文"：PYZ 内容是 zlib 压缩的，
明文字符串搜索会漏检——必须先解包，并且按语义（常量表）收集，
"扫不到"才是可信结论。
"""
import marshal
import os
import sys
import tempfile
import types

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

# 敏感特征（命中 = 凭据/自动交易/持久化模块被带进产物）
SENSITIVE = ["jdjr_config", "clawx_def", "clawx", "autotrade", "launchd",
             "RunAtLoad", "sim_", "query_blogger_trend", "query_gold_analysis",
             "jdjr_query_gold", "jdjr_query_news", "jdjr_query_stock"]
# 期望存在（内部控制项：命中 >0 才说明扫描器确实读到了模块内容）
CONTROL = ["query_price_jhub", "secure_store", "bff_client", "jos"]


def iter_code(co):
    yield co
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            yield from iter_code(c)


def strings_of(co):
    """递归收集 code object（含嵌套）的全部字符串字面量。"""
    out = []
    for c in iter_code(co):
        for k in c.co_consts:
            if isinstance(k, str):
                out.append(k)
            elif isinstance(k, bytes):
                try:
                    out.append(k.decode("utf-8", "replace"))
                except Exception:
                    pass
        out.extend(c.co_names or ())
    return out


def count_hits(strings, keys):
    blob = "\n".join(strings)
    return {k: blob.count(k) for k in keys}


def main(exe):
    print("=" * 74)
    print("扫描目标:", exe, "  %.2f MB" % (os.path.getsize(exe) / 1e6))
    print("=" * 74)

    arch = CArchiveReader(exe)
    top = list(arch.toc)
    pyz = [n for n in top if n.lower().endswith((".pyz", ".pyz.pyz"))]
    print("顶层条目数: %d   PYZ 条目: %s" % (len(top), pyz or "(无)"))

    agg = {k: 0 for k in SENSITIVE + CONTROL}
    mods_seen = []

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
            mods_seen = mods
            print("\nPYZ 内模块数: %d" % len(mods))
            print("  ", ", ".join(mods))
            for m in mods:
                try:
                    obj = z.extract(m)
                except Exception as e:
                    print("   [!] extract 失败 %s: %s" % (m, e))
                    continue
                if isinstance(obj, (bytes, bytearray)):
                    try:
                        obj = marshal.loads(bytes(obj))
                    except Exception:
                        continue
                if not isinstance(obj, types.CodeType):
                    continue
                for k, v in count_hits(strings_of(obj), SENSITIVE + CONTROL).items():
                    agg[k] += v
        finally:
            os.remove(tmp)

    print("\n-- 命中统计（解包 + 常量表语义扫描）--")
    print("  [敏感特征 —— 全部应为 0]")
    for k in SENSITIVE:
        flag = "  <== 命中!" if agg[k] else ""
        print("     %-24s %d%s" % (k, agg[k], flag))
    print("  [内部控制项 —— 应 >0]")
    for k in CONTROL:
        print("     %-24s %d" % (k, agg[k]))
    return agg


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: scan_artifact.py <exe> [<exe> ...]")
        raise SystemExit(2)
    for p in sys.argv[1:]:
        main(p)
        print()
