# -*- coding: utf-8 -*-
"""P1-A 落地自检入口（仅用于验证，不属于交付产物）。

用途：以与生产 spec 相同的收集方式（闭包进 PYZ、datas 为空）构建后，
在**打包运行时**验证三件事：
  1) jdgold 模块来自 PYZ 而非磁盘（查 __file__ 是否落在 sys._MEIPASS）；
  2) 包内不再有 _MEIPASS/jdgold 明文目录（datas=[] 生效）；
  3) gold_data.check_skill() / run_script() 在新语义下能取到真实金价。
"""
import importlib
import os
import sys

import gold_data as gd

try:  # 控制台可能是 GBK，避免中文/emoji 打印直接把自检打断
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    print("FROZEN =", gd.FROZEN)
    print("sys._MEIPASS =", getattr(sys, "_MEIPASS", None))
    print("SKILL_SCRIPTS =", gd.SKILL_SCRIPTS)
    print("SKILL_SCRIPTS 是目录 =", os.path.isdir(gd.SKILL_SCRIPTS))

    meipass = getattr(sys, "_MEIPASS", "") or ""
    bundled_dir = os.path.join(meipass, "jdgold") if meipass else ""
    print("包内 _MEIPASS/jdgold 目录存在 =", bool(bundled_dir) and os.path.isdir(bundled_dir))

    mod = importlib.import_module("query_price_jhub")
    mf = getattr(mod, "__file__", None)
    print("query_price_jhub.__file__ =", mf)
    from_pyz = bool(mf) and bool(meipass) and os.path.abspath(mf).startswith(meipass)
    print(">>> 结论：模块来自 PYZ =", from_pyz)

    try:
        gd.check_skill()
        print("check_skill: OK")
    except Exception as e:
        print("check_skill: FAIL", type(e).__name__, e)

    out = gd.run_script(["query_price_jhub.py", "--overview"])
    print("run_script 输出长度 =", len(out))
    hits = [ln for ln in out.splitlines() if ("金价" in ln or "黄金" in ln)][:4]
    for ln in hits:
        print("DATA:", ln[:140])


if __name__ == "__main__":
    main()
