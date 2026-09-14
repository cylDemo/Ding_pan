# -*- coding: utf-8 -*-
"""股票区/板块区展开收起回归测试：
1) 按钮存在且与金价区按钮右缘垂直对齐（≤2px）；
2) 收起股票区：画布隐藏、表头保留（按钮仍可见）、窗口变矮、字形 ︽、配置持久化；
3) 再展开恢复；板块区同理；
4) 持久化：新实例按保存的收起态启动；
5) 搜索展开/收起不破坏收起态；收起态下加股票自动展开；
6) 删除按钮与收起按钮同屏不重叠。
"""
import json, os, sys, tempfile, time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_widget as gw

_tmpdir = tempfile.mkdtemp()
_tmp = os.path.join(_tmpdir, "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "watchlist": ["600487"], "sectors": ["BK1136"]},
          open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

fails = []

w = gw.Widget()
root = w.root
root.deiconify()
w.conf["watchlist"] = ["600487"]
w.stock_data = {"600487": {"name": "亨通光电", "price": 65.5, "change_pct": 2.49,
                           "amount_yi": 91.89, "turnover": 5.86}}
w.sect_data = {"BK1136": {"name": "光通信模块", "inflow_yi": 22.5,
                          "change_pct": 0.25, "turnover": 4.72, "strength": 37}}
w._render_stocks()
w._render_sectors()
for _ in range(40):
    root.update()
    time.sleep(0.01)

def _right(w_):
    return w_.winfo_rootx() + w_.winfo_width()

def _mapped(w_):
    try:
        return w_.winfo_ismapped()
    except Exception:
        return False

# ── 1. 按钮存在 + 垂直对齐 ──
if not _mapped(w.gold_toggle): fails.append("金价区按钮未显示")
if not _mapped(w.stock_toggle): fails.append("股票区按钮未显示")
if not _mapped(w.sect_toggle): fails.append("板块区按钮未显示")
dg = abs(_right(w.stock_toggle) - _right(w.gold_toggle))
ds = abs(_right(w.sect_toggle) - _right(w.gold_toggle))
if dg > 2: fails.append(f"股票区按钮与金价区按钮右缘偏差 {dg}px > 2")
if ds > 2: fails.append(f"板块区按钮与金价区按钮右缘偏差 {ds}px > 2")

# ── 1b. 删除按钮不被窗口右缘裁切（真实数值会撑宽行，窗口 384 需兜住 352px 行宽）──
win_r = root.winfo_rootx() + root.winfo_width()
body_r = w.body.winfo_rootx() + w.body.winfo_width()
sd = list(w.stock_rows)[0][6]
sec_del = list(w.sect_box.grid_slaves(column=5))[0]
if _right(sd) > body_r - 1: fails.append(f"股票删除按钮仍被裁切: 右缘超出正文 {(_right(sd) - body_r)}px")
if _right(sec_del) > body_r - 1: fails.append(f"板块删除按钮仍被裁切: 右缘超出正文 {(_right(sec_del) - body_r)}px")
if win_r - _right(sd) < 10: fails.append(f"股票删除按钮距窗口右缘余量不足: {win_r - _right(sd)}px")
if win_r - _right(sec_del) < 10: fails.append(f"板块删除按钮距窗口右缘余量不足: {win_r - _right(sec_del)}px")

# ── 2. 收起股票区 ──
h0 = root.winfo_height()
w._toggle_stocks()
for _ in range(30): root.update(); time.sleep(0.01)
if _mapped(w.stocks_canvas): fails.append("股票区收起后画布仍显示")
if not _mapped(w.stocks_header): fails.append("股票区收起后表头（含按钮）丢失")
if not _mapped(w.stock_toggle): fails.append("股票区收起后按钮丢失")
if w.stock_toggle.cget("text") != "︽": fails.append(f"收起态字形错: {w.stock_toggle.cget('text')}")
h1 = root.winfo_height()
if h1 >= h0: fails.append(f"股票区收起后窗口未变矮: {h0} -> {h1}")
saved = json.load(open(_tmp, encoding="utf-8"))
if not saved.get("stocks_collapsed"): fails.append("stocks_collapsed 未持久化")

# ── 3. 再展开 ──
w._toggle_stocks()
for _ in range(30): root.update(); time.sleep(0.01)
if not _mapped(w.stocks_canvas): fails.append("股票区展开后画布未显示")
if w.stock_toggle.cget("text") != "︾": fails.append(f"展开态字形错: {w.stock_toggle.cget('text')}")
h2 = root.winfo_height()
if abs(h2 - h0) > 2: fails.append(f"再展开高度未还原: {h0} -> {h2}")

# ── 4. 收起板块区 ──
w._toggle_sectors()
for _ in range(30): root.update(); time.sleep(0.01)
if _mapped(w.sect_canvas): fails.append("板块区收起后画布仍显示")
if not _mapped(w.sect_header): fails.append("板块区收起后表头（含按钮）丢失")
if not _mapped(w.sect_toggle): fails.append("板块区收起后按钮丢失")
if w.sect_toggle.cget("text") != "︽": fails.append(f"板块收起态字形错: {w.sect_toggle.cget('text')}")
h3 = root.winfo_height()
if h3 >= h2: fails.append(f"板块区收起后窗口未变矮: {h2} -> {h3}")
# 分区收起后右对齐仍成立（表头变矮不影响 place relx）
ds2 = abs(_right(w.sect_toggle) - _right(w.gold_toggle))
if ds2 > 2: fails.append(f"收起后板块按钮对齐破坏: {ds2}px")

# ── 5. 搜索展开/收起不破坏板块收起态与股票收起态 ──
w._toggle_stocks()   # 股票区也收起
for _ in range(20): root.update(); time.sleep(0.01)
# 预置搜索词，防 1s 心跳 _sync_search_state 因“Entry 为空+下拉可见”自愈收下拉
w._suppress_trace = True
w._search_var.set("光纤")
w._suppress_trace = False
w._show_search_results()
for _ in range(20): root.update(); time.sleep(0.01)
if not _mapped(w.search_box): fails.append("搜索态下拉未显示")
w._hide_search_results()
for _ in range(30): root.update(); time.sleep(0.01)
if _mapped(w.stocks_canvas): fails.append("搜索收起后股票区收起态被破坏")
if _mapped(w.sect_canvas): fails.append("搜索收起后板块区收起态被破坏")

# ── 6. 收起态下加股票 → 自动展开 ──
w._add_stock("601069", "西部黄金")
for _ in range(30): root.update(); time.sleep(0.01)
if w.conf.get("stocks_collapsed"): fails.append("加股票未自动展开股票区")
if not _mapped(w.stocks_canvas): fails.append("自动展开后画布未显示")

# ── 7. 持久化：新实例按保存态启动 ──
w.conf["stocks_collapsed"] = True
w.conf["sectors_collapsed"] = True
json.dump(w.conf, open(_tmp, "w", encoding="utf-8"))
try:
    root.destroy()
except Exception:
    pass

w2 = gw.Widget()
root2 = w2.root
root2.deiconify()
w2.stock_data = w.stock_data
w2.sect_data = w.sect_data
w2._render_stocks()
w2._render_sectors()
for _ in range(40): root2.update(); time.sleep(0.01)
if _mapped(w2.stocks_canvas): fails.append("新实例未按持久化收起态启动（股票区）")
if _mapped(w2.sect_canvas): fails.append("新实例未按持久化收起态启动（板块区）")
if not _mapped(w2.stock_toggle) or not _mapped(w2.sect_toggle):
    fails.append("新实例收起态下按钮不可见，无法再展开")
root2.destroy()

if fails:
    print("FAIL")
    for f in fails: print(" -", f)
    sys.exit(1)
print("PASS: 股票/板块区展开收起全部断言通过")
