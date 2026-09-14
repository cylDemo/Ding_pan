# -*- coding: utf-8 -*-
"""P1-A 回归：验证 runpy → import+main(argv) 的语义等价，以及 check_skill 分形态判定。

重点：
1) _script_modname 文件名→模块名解析；
2) 源码模式 _script_available 仍按文件存在性判定（不得误报缺失）；
3) 模拟打包语义直调 _run_inproc：能真实取到行情（证明 import+main 通路可用）；
4) 参数透传有效、sys.argv/sys.path 用后复原（不得污染全局）；
5) FROZEN 分支 check_skill 改用模块可导入性：齐备时不误报、缺失时给出可定位文案。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_data as gd  # noqa: E402

fails = []

# ── 1. 文件名 → 模块名 ──
if gd._script_modname("query_price_jhub.py") != "query_price_jhub":
    fails.append("_script_modname 未去掉 .py")
if gd._script_modname("a/b/jos.py") != "jos":
    fails.append("_script_modname 未剥离目录")

# ── 2. 源码模式仍按文件判定 ──
if gd.FROZEN:
    fails.append("测试前提错误：当前应为源码模式")
if not gd._script_available("query_price_jhub.py"):
    fails.append("源码模式下 query_price_jhub 应判定为可用")
if gd._script_available("no_such_script.py"):
    fails.append("不存在的脚本不应判定为可用")

# ── 3. import+main 通路能真实取数 ──
_argv_before = list(sys.argv)
_out = gd._run_inproc(["query_price_jhub.py", "--overview"])
if len(_out) < 50:
    fails.append(f"_run_inproc 输出过短: {len(_out)}")
if "金价" not in _out and "黄金" not in _out:
    fails.append("_run_inproc 未产出可解析的行情文本")

# ── 4. 无副作用：argv 复原、参数确被消费 ──
if sys.argv != _argv_before:
    fails.append(f"sys.argv 未复原: {sys.argv}")
_lst = gd._run_inproc(["query_price_jhub.py", "--list"])
if len(_lst) < 20:
    fails.append("_run_inproc 在 --list 下无输出（参数可能未透传）")

# ── 5. FROZEN 分支 check_skill 用 find_spec ──
_skill = gd.SKILL_SCRIPTS
_old_frozen = gd.FROZEN
_old_news = gd.NEWS_SCRIPTS
_old_path = sys.path[:]
try:
    if _skill and os.path.isdir(_skill):
        sys.path.insert(0, _skill)
    gd.FROZEN = True
    gd.NEWS_SCRIPTS = ("no_such_news.py",)
    try:
        gd.check_skill()
    except Exception as e:
        fails.append(f"FROZEN 分支 check_skill 齐备时误报: {type(e).__name__}: {e}")
    try:
        gd.check_skill(with_news=True)
        fails.append("FROZEN 分支缺模块时未抛错")
    except RuntimeError as e:
        if "缺少 jdgold 模块" not in str(e):
            fails.append(f"FROZEN 分支缺模块文案不可定位: {e}")
finally:
    gd.FROZEN = _old_frozen
    gd.NEWS_SCRIPTS = _old_news
    sys.path = _old_path

if fails:
    print("FAIL:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: P1-A 语义等价 + 分形态 check_skill 全部通过")
