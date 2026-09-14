# -*- coding: utf-8 -*-
"""Tier 0.3 等价性核对：抽取只应"改缩进 + 加包装"，不应丢行。

做法：把 HEAD 版与工作区的 gold_widget.py 各自归一化（去缩进、丢空行、丢纯注释行），
比对多重集合。正常情况下"消失的行"只应是**被改写的外壳**（for 头、赋值解包、
被移出的小注释），数量应为个位数；任何函数体语句丢失都会在这里现形。
"""
import collections
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = os.path.join(ROOT, "gold_widget.py")


def norm(text):
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return collections.Counter(out)


def main():
    old = subprocess.run(["git", "show", "HEAD:gold_widget.py"], cwd=ROOT,
                         capture_output=True).stdout.decode("utf-8")
    new = io.open(GW, encoding="utf-8").read()
    a, b = norm(old), norm(new)

    missing = a - b   # 旧有新无 → 可疑丢失
    added = b - a     # 新增（包装/取数行/docstring 首行）

    print("== 旧有新无（应为个位数，且都是被改写的'外壳'行）==")
    tot = 0
    for ln, n in sorted(missing.items(), key=lambda kv: -kv[1]):
        print("  x%d  %s" % (n, ln[:110]))
        tot += n
    print("  合计 %d 行" % tot)

    print("\n== 新增（应只有 def 行 / 调用行 / docstring / 参数行）==")
    for ln, n in sorted(added.items(), key=lambda kv: -kv[1]):
        print("  x%d  %s" % (n, ln[:110]))

    # 归纳：真·代码语句（以关键字/赋值/调用形态出现）不应出现在 missing 里
    suspicious = [ln for ln in missing
                  if re.match(r"^(self\.|tk\.|if |for |while |try|except|return|raise|"
                              r"lbl\.|name_l|code_l|price_l|pct_l|tr_l|amt_l|del_btn|"
                              r"inflow_l|st_l|a\.|p\.|c\.|m\.|w\.|f\.|out |d\[)", ln)]
    print("\n可疑丢失（需人工确认）:", "无" if not suspicious else "")
    for s in suspicious:
        print("   !", s)
    return 1 if suspicious else 0


if __name__ == "__main__":
    sys.exit(main())
