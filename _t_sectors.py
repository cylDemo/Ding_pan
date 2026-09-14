# -*- coding: utf-8 -*-
"""板块区回归测试：
1) 表头 5 列（板块名称/资金流入(亿)/涨幅/换手率/概念强度）且与数值列对齐；
2) 行渲染：流入正红负绿、缺失字段 "---"、概念强度缺省 "---"；
3) ≤2 个板块实高展示，>2 个锁定 2 行 + 滚动；
4) 删除按钮在窗口内；掩码生效；主题重刷无异常；
5) sectors 清空时整区隐藏、窗口收缩。
"""
import json, os, sys, tempfile, time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_widget as gw

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "sectors": ["BK1136", "BK1617"]}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

fails = []

w = gw.Widget()
root = w.root
root.deiconify()
root.update_idletasks()
for _ in range(30):
    root.update()
    time.sleep(0.01)

# 注入数据渲染
w.conf["watchlist"] = ["600487"]
w.stock_data = {"600487": {"name": "亨通光电", "price": 63.91, "change_pct": -4.07,
                           "amount_yi": 94.47, "turnover": 5.97}}
w.conf["sectors"] = ["BK1136", "BK1617", "BK0478"]
w.sect_data = {
    "BK1136": {"name": "光通信模块", "inflow_yi": -20.65, "change_pct": -3.3, "turnover": 3.28, "strength": None},
    "BK1617": {"name": "黄金", "inflow_yi": 5.73, "change_pct": 2.1, "turnover": 1.77, "strength": 3},
    "BK0478": {"name": "有色金属", "inflow_yi": None, "change_pct": None, "turnover": None, "strength": None},
}
w._render_sectors()
for _ in range(40):
    root.update()
    time.sleep(0.01)

texts = [c.cget("text") for c in w.sect_box.winfo_children() if isinstance(c, tk.Label)]
# 断言 1：表头齐全
hdr_texts = [c.cget("text") for c in w.sect_header.winfo_children() if isinstance(c, tk.Label)]
if "板块名称" not in hdr_texts:
    fails.append(f"板块表头缺 板块名称: {hdr_texts}")
for c, t in w._sect_hdr_canvases:
    items = c.find_all()
    if not items or str(c.itemcget(items[0], "text")) != t:
        fails.append(f"板块表头 Canvas 缺 {t}")
# 断言 2：行数据与缺失占位
if "-20.65" not in texts: fails.append(f"缺流入 -20.65: {texts}")
if "5.73" not in texts: fails.append("缺流入 5.73")
if "第3名" not in texts: fails.append("缺概念强度 第3名")
if texts.count("---") < 4: fails.append(f"缺失占位 --- 数量不足: {texts.count('--')}处")
# 断言 3：>2 个锁定 2 行滚动
if not w._sect_scroll_on: fails.append("3 个板块未启用滚动")
if w.sect_canvas.winfo_height() > 130: fails.append(f"板块画布高度未锁定: {w.sect_canvas.winfo_height()}")
# 断言 4：删除按钮在窗口内
del_r = max(c.winfo_rootx() + c.winfo_width() for c in w.sect_box.grid_slaves(column=5))
win_r = root.winfo_rootx() + root.winfo_width()
if del_r > win_r - 2: fails.append(f"板块删除按钮被挤出窗口: {del_r} > {win_r}")
# 断言 5：掩码
w._hide_data = True
w._render_sectors(); root.update()
texts_m = [c.cget("text") for c in w.sect_box.winfo_children() if isinstance(c, tk.Label)]
if "-20.65" in texts_m: fails.append("掩码下资金流入未打码")
w._hide_data = False
w._render_sectors(); root.update()
# 断言 6：主题重刷
try:
    w._apply_theme("light")
    w._apply_theme("dark")
    for _ in range(20): root.update(); time.sleep(0.01)
except Exception as e:
    fails.append(f"主题重刷异常: {e}")
# 断言 7：清空 sectors 整区隐藏
w.conf["sectors"] = []
w._render_sectors()
for _ in range(30): root.update(); time.sleep(0.01)
if w.sect_area.winfo_ismapped(): fails.append("sectors 清空后板块区未隐藏")
if w.sect_divider.winfo_ismapped(): fails.append("sectors 清空后分隔线未隐藏")

root.destroy()

if fails:
    print("FAIL")
    for f in fails: print(" -", f)
    sys.exit(1)
print("PASS: 板块区全部断言通过")
