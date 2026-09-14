# -*- coding: utf-8 -*-
"""回归：透明度展开子菜单 + 既有菜单行为（进程内）。"""
import time
import json
import tempfile
import os
import gold_widget as gw

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": True, "theme": "dark"}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp

gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

w = gw.Widget()
root = w.root

def _hook(tp, val, tb):
    import traceback
    print("=== callback exception ===")
    traceback.print_exception(tp, val, tb)
root.report_callback_exception = _hook
root.geometry("+200+200")
root.deiconify()
root.update_idletasks()

class Ev:
    def __init__(self, x, y, t):
        self.x_root, self.y_root, self.time = x, y, t

fails = []

def open_menu(t, **kw):
    w._popup_menu(Ev(460, 380, t), **kw)
    m = w._menu_win
    t0 = time.time()
    while time.time() - t0 < 2.0:
        root.update()
        if m.winfo_viewable() and time.time() - t0 > 0.1:
            time.sleep(0.05)
            root.update()
            break
        time.sleep(0.01)
    return m

def labels_of(m):
    return [c for c in m.winfo_children() if isinstance(c, tk.Label)]

def texts_of(m):
    return [c.cget("text") for c in labels_of(m)]

import tkinter as tk

# ── 1：默认收起——有"透明度"行、无百分比子行 ──
m = open_menu(1000)
tx = texts_of(m)
if not any(str(t).startswith("透明度") for t in tx):
    fails.append(f"未找到透明度行: {tx}")
if any("%" in str(t) and "透明度" not in str(t) for t in tx):
    fails.append(f"收起态不应有百分比子行: {tx}")
h_collapsed = m.winfo_reqheight()

# ── 2：alpha_expanded=True——展开 6 档，当前档打 ✓ ──
w._close_menu(); root.update()
m2 = open_menu(2000, alpha_expanded=True)
tx2 = [str(t) for t in texts_of(m2)]
for pct in (100, 95, 88, 78, 68, 58):
    if not any(t.endswith(f"{pct}%") for t in tx2):
        fails.append(f"展开态缺少 {pct}% 档: {tx2}")
if not any(t.startswith("✓") for t in tx2):
    fails.append(f"当前档未打勾: {tx2}")
if abs(m2.winfo_reqheight() - h_collapsed) < 60:
    fails.append("展开后菜单高度未增长")

# ── 3：点击 68% 档 → alpha 生效并持久化，菜单关闭 ──
pct68 = [c for c in labels_of(m2) if str(c.cget("text")).endswith("68%")]
if not pct68:
    fails.append("未找到 68% 行")
else:
    pct68[0].event_generate("<Button-1>", time=2500)
    root.update()
    if abs(float(root.attributes("-alpha")) - 0.68) > 0.005:
        fails.append(f"点击 68% 后 alpha={root.attributes('-alpha')}")
    saved = json.load(open(_tmp, encoding="utf-8"))
    if abs(saved.get("alpha", 0) - 0.68) > 0.005:
        fails.append(f"68% 未持久化: conf={saved.get('alpha')}")

# ── 4：重开菜单（展开态），✓ 应落在 68% ──
root.update()
m3 = open_menu(3000, alpha_expanded=True)
tx3 = [str(t) for t in texts_of(m3)]
if not any(t.startswith("透明度 68%") for t in tx3):
    fails.append(f"透明度行未显示 68%: {tx3}")
if not any(t.startswith("✓") and t.endswith("68%") for t in tx3):
    fails.append(f"✓ 未落在 68%: {tx3}")

# ── 5：收起态点击"透明度"行 → 原位重开为展开态 ──
w._close_menu(); root.update()
m4 = open_menu(4000)
xy_before = (m4.winfo_x(), m4.winfo_y())
alpha_row = [c for c in labels_of(m4) if str(c.cget("text")).startswith("透明度")]
if not alpha_row:
    fails.append("未找到透明度行")
else:
    alpha_row[0].event_generate("<Button-1>", time=4100)
    root.update()
    time.sleep(0.15); root.update()
    m5 = w._menu_win
    if m5 is None or not m5.winfo_exists():
        fails.append("点击透明度行后菜单未重开")
    else:
        tx5 = [str(t) for t in texts_of(m5)]
        if not any(t.endswith("68%") for t in tx5):
            fails.append(f"点击透明度行后未展开百分比子选项: {tx5}")
        dx = abs(m5.winfo_x() - xy_before[0]); dy = abs(m5.winfo_y() - xy_before[1])
        if dx > 2 or dy > 2:
            fails.append(f"展开时菜单位置漂移: {xy_before} -> ({m5.winfo_x()},{m5.winfo_y()})")
        # 点击外部仍可关闭
        w._menu_sweep_click(Ev(50, 50, 4500))
        if w._menu_win is not None:
            fails.append("展开态下点击菜单外未关闭")

root.destroy()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("PASS: 收起/展开6档/68%生效持久化/勾选跟随/原位展开/外部点击关闭")
