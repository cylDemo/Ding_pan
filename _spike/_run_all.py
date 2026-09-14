# -*- coding: utf-8 -*-
r"""跑全部 _t_*.py 回归，输出退出码 + 结果行摘要。

用法（系统 Python 3.12，自带 tkinter）：
  <py312>\python.exe _spike\_run_all.py [--tag 基线]

设计要点：
  · 逐个子进程跑，单个崩溃不拖累其余；
  · 认退出码 + 末行 PASS/FAIL 双口径（部分脚本只 print 不 exit）；
  · stdout/stderr 合并、UTF-8 解码，超时 180s 单独标记。
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

TESTS = ["_t_log.py", "_t_pyz.py", "_t_focus.py", "_t_menu.py", "_t_alpha.py",
         "_t_collapse.py", "_t_quota.py", "_t_routing.py", "_t_sectors.py",
         "_t_sectors_keepold.py", "_t_strength.py", "_t_turnover.py"]


def run_one(name, timeout=180):
    t0 = time.time()
    try:
        p = subprocess.run([PY, os.path.join(ROOT, name)], cwd=ROOT,
                           capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "TIMEOUT", "TIMEOUT"
    dt = time.time() - t0
    blob = (out + "\n" + err).strip()
    lines = [ln for ln in blob.splitlines() if ln.strip()]
    verdict = "?"
    for ln in reversed(lines):
        s = ln.strip()
        if s.startswith("PASS") or s.startswith("FAIL"):
            verdict = s
            break
    else:
        verdict = lines[-1] if lines else "(no output)"
    return name, rc, dt, verdict, lines


def main():
    tag = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--tag" else ""
    if tag:
        print("=== 回归批次: %s ===" % tag)
    ok = bad = 0
    rows = []
    for name in TESTS:
        n, rc, dt, verdict, lines = run_one(name)
        good = (rc == 0)
        if good:
            ok += 1
        else:
            bad += 1
        rows.append((name, rc, dt, verdict, lines))
        print("%-24s rc=%-4s %5.1fs  %s" % (n, rc, dt, verdict[:110]))
    print("\n---- 汇总: %d/%d 通过 ----" % (ok, ok + bad))
    if bad:
        print("\n==== 失败明细 ====")
        for name, rc, dt, verdict, lines in rows:
            if rc != 0:
                print("\n### %s (rc=%s)" % (name, rc))
                for ln in lines[-25:]:
                    print("   ", ln)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
