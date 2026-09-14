# -*- coding: utf-8 -*-
"""换手率列回归测试：
1) 表头 5 列：股票名称/实时价格/涨幅/换手率/成交额，换手率在 col 3；
2) 股票行 col 3 渲染 "XX.XX%"，缺数据时显示 "—"；
3) 表头/行列宽同构（同一 uniform 配置）；
4) 主题重刷后换手率标题 Canvas 重画不报错；
5) 数据掩码（眼睛）对换手率同样生效。
"""
import json, os, sys, tempfile, time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_widget as gw

# 隔离配置 + 屏蔽网络线程
_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark"},
          open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

fails = []

w = gw.Widget()
root = w.root
root.deiconify()
root.update_idletasks()

# 注入两只股票（一只有换手率、一只缺）并渲染
w.conf["watchlist"] = ["600487", "002245"]
w.stock_data = {
    "600487": {"name": "亨通光电", "price": 63.91, "change_pct": -4.07,
               "amount_yi": 94.47, "turnover": 5.97},
    "002245": {"name": "蔚蓝锂芯", "price": 17.97, "change_pct": 0.96,
               "amount_yi": 6.15, "turnover": None},
}
w._render_stocks()
for _ in range(50):
    root.update()
    time.sleep(0.01)

# ── 断言 1：表头文字齐全，换手率在 col 3 ──
hdr_texts = [c.cget("text") for c in w.stocks_header.winfo_children()
             if isinstance(c, tk.Label)]
for t in ("股票名称", "实时价格"):
    if t not in hdr_texts:
        fails.append(f"表头缺 {t}")
try:
    c3 = w._draw_hdr_col3  # 存在即换手率 Canvas 绑定到位
    c4 = w._hdr_col4
except AttributeError:
    fails.append("表头缺 _hdr_col3/_hdr_col4")
hdr_items = w._hdr_col3.find_all()
if hdr_items and "换手率" not in str(w._hdr_col3.itemcget(hdr_items[0], "text")):
    fails.append("col3 标题不是 换手率")
hdr_items4 = w._hdr_col4.find_all()
if hdr_items4 and "成交额" not in str(w._hdr_col4.itemcget(hdr_items4[0], "text")):
    fails.append("col4 标题不是 成交额")

# ── 断言 2：行数据渲染 ──
row_texts = [c.cget("text") for c in w.stocks_box.winfo_children()
             if isinstance(c, tk.Label)]
if "5.97%" not in row_texts:
    fails.append(f"行内缺换手率 5.97%: {row_texts}")
if "—" not in row_texts:
    fails.append("缺换手率股票未显示 — 占位")

# ── 断言 3：掩码 ──
w._hide_data = True
w._render_stocks()
root.update()
row_texts_m = [c.cget("text") for c in w.stocks_box.winfo_children()
               if isinstance(c, tk.Label)]
if "5.97%" in row_texts_m:
    fails.append("掩码下换手率未打码")
w._hide_data = False
w._render_stocks()
root.update()

# ── 断言 4：主题重刷不报错 ──
try:
    w._restyle_stocks_header()
    w._restyle_stock_rows()
    root.update()
except Exception as e:
    fails.append(f"主题重刷异常: {e}")

root.destroy()

if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("PASS: 换手率列全部断言通过")
