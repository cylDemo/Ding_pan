# -*- coding: utf-8 -*-
"""源码模式冒烟：确认 P1-A 改造未破坏非打包路径。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gold_data as gd  # noqa: E402

print("FROZEN =", gd.FROZEN)
print("SKILL_SCRIPTS =", gd.SKILL_SCRIPTS)
print("_script_modname('query_price_jhub.py') =", gd._script_modname("query_price_jhub.py"))
print("_script_available('query_price_jhub.py') =", gd._script_available("query_price_jhub.py"))
print("_script_available('not_exist.py') =", gd._script_available("not_exist.py"))

try:
    gd.check_skill()
    print("check_skill: OK")
except Exception as e:
    print("check_skill: FAIL", type(e).__name__, e)

try:
    gd.check_skill(with_news=True, with_trend=True)
    print("check_skill(全量): OK")
except Exception as e:
    print("check_skill(全量): FAIL", type(e).__name__, e)

out = gd.run_script(["query_price_jhub.py", "--overview"])
print("run_script 输出长度 =", len(out))
print("--- 前 400 字 ---")
print(out[:400])
