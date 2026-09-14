#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glog 回归测试（必须在子进程里跑：会替换 sys.stdout/stderr）。

覆盖：
1. 自激循环防护 —— redirect_std_streams() 之后再 log/print/warn，
   不得出现 log→stderr(_Tee)→log 的无限递归（历史上会刷爆日志并吃满 CPU）；
2. utf-8 中文不乱码；
3. 路径脱敏（本机主目录 → ~）；
4. 按大小轮转（1MB 上限，保留 .1/.2/.3）；
5. 分级阈值过滤。
"""
import io
import json
import os
import sys
import tempfile

fails = []
tmpdir = tempfile.mkdtemp()
logpath = os.path.join(tmpdir, "test.log")
os.environ["GOLD_WIDGET_LOG"] = logpath
os.environ["GOLD_WIDGET_LOG_LEVEL"] = "DEBUG"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glog

# ── 1. 自激循环防护 ──
# 先制造"sys.stderr 已被换成 tee"的前置条件（模拟冻结 --noconsole 场景）
glog.redirect_std_streams()
for _ in range(5):
    glog.warn("循环防护探针")
    print("stdout 探针")
    print("stderr 探针", file=sys.__stderr__)
size_after_5 = os.path.getsize(logpath)
# 若存在自激循环，5 次调用会写出远大于 5 行的内容（实测可达百 KB~MB 级）
if size_after_5 > 8000:
    fails.append(f"疑似日志自激循环：5 次调用写出 {size_after_5} 字节")
content = io.open(logpath, encoding="utf-8").read()
if content.count("循环防护探针") > 20:
    fails.append(f"探针被放大重复 {content.count('循环防护探针')} 次")

# ── 2. 中文不乱码 ──
glog.info("中文编码检查：光纤概念 涨幅 第30名")
content = io.open(logpath, encoding="utf-8").read()
if "中文编码检查：光纤概念 涨幅 第30名" not in content:
    fails.append("utf-8 中文写入异常（乱码或丢失）")

# ── 3. 路径脱敏 ──
home = os.path.expanduser("~")
glog.info(f"路径脱敏检查 {os.path.join(home, 'AppData', 'x.json')}")
content = io.open(logpath, encoding="utf-8").read()
if home in content:
    fails.append("主目录未被脱敏")
if ("~" + os.sep + "AppData") not in content:
    fails.append("脱敏后的 ~ 形式未出现")

# ── 4. 轮转 ──
for i in range(4000):
    glog.info("填充行 " + "x" * 400)
if not os.path.exists(logpath + ".1"):
    fails.append("未产生轮转备份 .1")
if os.path.getsize(logpath) > glog.MAX_BYTES + 100000:
    fails.append(f"当前日志超出上限未轮转: {os.path.getsize(logpath)}")

# ── 5. 分级过滤 ──
os.environ["GOLD_WIDGET_LOG_LEVEL"] = "ERROR"  # 该变量在 import 时读取，这里手动改内部阈值
glog._MIN = glog._LEVELS["ERROR"]
n0 = os.path.getsize(logpath)
glog.info("这条不应被写入")
glog.debug("这条也不应被写入")
if os.path.getsize(logpath) != n0:
    fails.append("分级阈值过滤失效（INFO/DEBUG 被写入）")
glog.error("这条应被写入")
if os.path.getsize(logpath) == n0:
    fails.append("ERROR 级未写入")

# 结果必须走 sys.__stdout__ 写出：此时 sys.stdout 已被换成 _Tee，
# 且阈值已被抬到 ERROR，普通 print 会被日志系统吃掉。
glog._MIN = glog._LEVELS["DEBUG"]
_out = sys.__stdout__ or sys.stdout
_out.write(json.dumps({"fails": fails, "size": os.path.getsize(logpath)}, ensure_ascii=False) + "\n")
_out.write(("PASS: glog 日志系统全部断言通过" if not fails else "FAIL: " + " | ".join(fails)) + "\n")
_out.flush()
sys.exit(1 if fails else 0)
