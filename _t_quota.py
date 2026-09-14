# -*- coding: utf-8 -*-
"""京东配额错误识别 / 刷新时段窗口 / 长退避回归测试：
1) collect() 对「频次超出」响应抛 QuotaError（区别于普通网络异常）；
2) 正常行情不受影响（parse_overview 仍工作）；
3) 刷新时段窗口：工作日 9:30~18:00 内开启，边界正确，周末/夜间关闭；
4) UI 收到 ("quota", ...) → 红点 + 时间位「额度恢复中」+ _quota_mode 置位；
5) 配额模式下实际刷新间隔托底 ≥300s（窗口内）；
6) 窗口外自动轮询不发车、无数据时提示「非刷新时段」；窗口开启立即补发；
7) 成功一次即解除配额模式，恢复 normal 间隔。
"""
import datetime
import json, os, sys, tempfile, time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_data as gd
import gold_widget as gw

fails = []

# ── 1. collect() 识别配额错误 ──
_real_run = gd.run_script
_QUOTA_MSG = ("BFF error code=500 msg=您好，调用频次超出平台当天上限，"
              "请稍后再试（解决方案参考: https://open.jd.com/v2/#/doc/guide?listId=533）")
gd.run_script = lambda args, timeout=90: _QUOTA_MSG
try:
    gd.collect(with_news=False, with_trend=False)
    fails.append("配额响应未抛 QuotaError")
except gd.QuotaError as e:
    if "配额" not in str(e):
        fails.append(f"QuotaError 文案不对: {e}")
except Exception as e:
    fails.append(f"配额响应抛错类型不对: {type(e).__name__}: {e}")

# ── 2. 正常响应不受影响 ──
_OK = """# 黄金行情速览

一、实时行情

| 品种 | 最新价 | 涨跌额 | 涨跌幅 | 今开 | 昨收 | 最高 | 最低 |
|------|------|------|------|------|------|------|------|
| 京东24h金价 | 812.50 | +1.20 | +0.15% 🔴 | 811.30 | 811.30 | 813.00 | 810.50 |
"""
gd.run_script = lambda args, timeout=90: _OK
try:
    d = gd.collect(with_news=False, with_trend=False)
    if (d.get("main") or {}).get("price") != 812.50:
        fails.append(f"正常行情解析坏了: {d.get('main')}")
except gd.QuotaError:
    fails.append("正常响应被误判为配额错误")

# ── 3. 刷新时段窗口边界 ──
D = datetime.datetime
_w = gw.Widget._gold_window_active
cases = [
    (D(2026, 9, 11, 10, 0),  True,  "周五上午"),
    (D(2026, 9, 11, 9, 30),  True,  "周五9:30整（含起点）"),
    (D(2026, 9, 11, 9, 29),  False, "周五9:29"),
    (D(2026, 9, 11, 17, 59), True,  "周五17:59"),
    (D(2026, 9, 11, 18, 0),  False, "周五18:00整（不含终点）"),
    (D(2026, 9, 11, 8, 0),   False, "周五早上8点"),
    (D(2026, 9, 11, 22, 0),  False, "周五夜间"),
    (D(2026, 9, 12, 10, 0),  False, "周六"),
    (D(2026, 9, 13, 10, 0),  False, "周日"),
    (D(2026, 9, 14, 9, 30),  True,  "周一9:30"),
]
for now, want, tag in cases:
    got = _w(gw.Widget.__new__(gw.Widget), now)   # 不跑 __init__，纯函数式调用
    if got != want:
        fails.append(f"窗口判断[{tag}]: 期望 {want} 实际 {got}")

# ── 4~7. UI：quota 消息 + 间隔托底 + 窗口门控 + 成功解除 ──
_tmpdir = tempfile.mkdtemp()
_tmp = os.path.join(_tmpdir, "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "watchlist": [], "sectors": []}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

w = gw.Widget()
root = w.root
root.deiconify()
for _ in range(20):
    root.update()
    time.sleep(0.01)

w.interval = 5
w._gold_window_active = lambda: True   # 窗口内
w.q.put(("quota", "京东接口当日调用配额已用尽，次日 0 点自动恢复"))
w._poll()   # 直接驱动心跳（root.update() 等不到 1s 定时回调）

if not getattr(w, "_quota_mode", False):
    fails.append("quota 消息后 _quota_mode 未置位")
if w.t_time.cget("text") != "额度恢复中":
    fails.append(f"时间位提示不对: {w.t_time.cget('text')}")

# 配额模式下间隔托底：把 _last 拨到 299s 前，不应发车（fetch 已被 mock 为空，
# 改用计数探针验证发车意图）
launched = {"n": 0}
w.fetch = lambda: launched.__setitem__("n", launched["n"] + 1)
w._last = time.time() - 299
w._poll()
if launched["n"] != 0:
    fails.append("配额模式 299s 后仍发车（托底 <300s 未生效）")
w._last = time.time() - 301
w._poll()
if launched["n"] != 1:
    fails.append("配额模式 301s 后未发车")

# 窗口外：不发车 + 无数据时提示「非刷新时段」
w._gold_window_active = lambda: False
w._last = 0.0
w._poll()
if launched["n"] != 1:
    fails.append("窗口外自动轮询仍发车")
if w.t_time.cget("text") != "非刷新时段":
    fails.append(f"窗口外无数据提示不对: {w.t_time.cget('text')}")

# 有数据时窗口外：保持展示，不覆盖时间位
w.q.put(("ok", {"updated_at": "2026-09-11 17:40:00",
                "main": {"name": "京东24h金价", "price": 812.50,
                         "change_pct": 0.15, "diff": 1.20}}))
w._gold_window_active = lambda: True
w._poll()
if getattr(w, "_quota_mode", True):
    fails.append("成功后 _quota_mode 未解除")
if w.t_time.cget("text") == "额度恢复中":
    fails.append("成功后时间位未恢复")
w._gold_window_active = lambda: False
w._poll()
if w.t_time.cget("text") != "17:40":
    fails.append(f"窗口外有数据时时间位被覆盖: {w.t_time.cget('text')}")
if w.m_price.cget("text") in ("—", ""):
    fails.append("窗口外有数据时价格被清空")

root.destroy()
gd.run_script = _real_run

if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("PASS: 配额识别/窗口边界/UI提示/长退避/窗口门控/盘外保数据 全部断言")
