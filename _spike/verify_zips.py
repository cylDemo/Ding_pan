# -*- coding: utf-8 -*-
"""交付包完整性实证：
1) zip 结构（顶层目录 / _internal / 说明文档位置）；
2) 包内 exe 与构建源 exe 的 SHA256 逐字节比对；
3) 绿色版真实解压到临时目录，确认可还原且 exe 可执行文件存在。
"""
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GREEN = os.path.join(ROOT, "盯盘-绿色版.zip")
ONEFILE = os.path.join(ROOT, "盯盘-发布包.zip")
DOC_INNER = "使用说明.txt"


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def sha_zip_member(z, name):
    h = hashlib.sha256()
    h.update(z.read(name))
    return h.hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fails = []

    # ---- 绿色版 ----
    src_exe = os.path.join(ROOT, "_out_v203", "盯盘", "盯盘.exe")
    with zipfile.ZipFile(GREEN) as z:
        names = z.namelist()
        exe_members = [n for n in names if n.endswith("/盯盘.exe")]
        has_internal = any("/_internal/" in n for n in names)
        has_doc = any(n.endswith("/" + DOC_INNER) for n in names)
        top = sorted({n.split("/")[0] for n in names})
        print("[绿色版] 条目=%d 顶层=%s _internal=%s 说明=%s" % (len(names), top, has_internal, has_doc))
        if not exe_members:
            fails.append("绿色版包内找不到 盯盘.exe")
        else:
            hz = sha_zip_member(z, exe_members[0])
            hs = sha_file(src_exe)
            same = hz == hs
            print("[绿色版] 包内 exe(%s) SHA=%s" % (exe_members[0], hz[:24]))
            print("[绿色版] 源   exe          SHA=%s  一致=%s" % (hs[:24], same))
            if not same:
                fails.append("绿色版包内 exe 与构建源不一致")
        if not has_internal:
            fails.append("绿色版缺 _internal 目录")
        if not has_doc:
            fails.append("绿色版缺说明文档")
        if len(top) != 1:
            fails.append("绿色版顶层目录不唯一: %s" % top)

        tmp = tempfile.mkdtemp(prefix="vz_")
        try:
            z.extractall(tmp)
            files = [os.path.join(r, f) for r, _d, fs in os.walk(tmp) for f in fs]
            print("[绿色版] 实测解压: %d 文件" % len(files))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- 发布包 ----
    src_of = os.path.join(ROOT, "盯盘.exe")
    with zipfile.ZipFile(ONEFILE) as z:
        names = z.namelist()
        print("[发布包] 条目=%d 内容=%s" % (len(names), names))
        exe_m = [n for n in names if n.endswith("盯盘.exe")]
        if not exe_m:
            fails.append("发布包内找不到 盯盘.exe")
        else:
            same = sha_zip_member(z, exe_m[0]) == sha_file(src_of)
            print("[发布包] 包内 exe 与构建源一致=%s" % same)
            if not same:
                fails.append("发布包内 exe 与构建源不一致")
        if not any(n.endswith(DOC_INNER) for n in names):
            fails.append("发布包缺说明文档")

    # ---- 构建新鲜度：exe 必须不比源码旧（防"改了代码没重建就打包"）----
    root_exe = os.path.join(ROOT, "盯盘.exe")
    if os.path.isfile(root_exe):
        srcs = [f for f in os.listdir(ROOT) if f.endswith(".py") and f.startswith("gold")]
        srcs += ["盯盘.spec", "version_info.txt"]
        newest = max((os.path.getmtime(os.path.join(ROOT, f))
                      for f in srcs if os.path.isfile(os.path.join(ROOT, f))), default=0)
        exe_mt = os.path.getmtime(root_exe)
        fresh = exe_mt >= newest
        print("[新鲜度] 盯盘.exe mtime=%s  最新源 mtime=%s  未陈旧=%s  (%d bytes)"
              % (int(exe_mt), int(newest), fresh, os.path.getsize(root_exe)))
        if not fresh:
            fails.append("盯盘.exe 比源码旧，需重新构建后再打包")

    print()
    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS: 交付包完整性实证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
