# -*- coding: utf-8 -*-
"""回归：标题栏「最小化到任务栏」按钮（—）（进程内，真实 Tk + Win32）。

覆盖：
  ① 按钮存在、在 title_bar 内、文字为 —、位于 × 左侧（Windows「—×」惯例）、已绑定点击；
  ② 切主题后 fg 跟随（_restyle_widgets / _sweep_theme_colors 双路径）；
  ③ 点击后窗口真进入最小化态（Win32 IsIconic=1）——Tk iconify() 对 override-redirect
     窗口会抛 TclError，故此步是「实现没退化成 withdraw」的关键判据；
  ④ 已去掉 WS_EX_TOOLWINDOW 且带上 WS_EX_APPWINDOW（否则任务栏不出现入口）；
  ⑤ 恢复后位置/尺寸保持（ShowWindow(SW_RESTORE) 不跑位）。
"""
import ctypes
import json
import os
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import gold_widget as gw

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "light",
           "watchlist": []}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp

gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

w = gw.Widget()
root = w.root
root.geometry("+240+240")
root.deiconify()
root.update_idletasks()
root.update()

fails = []

# ① 结构 + 位置
btn = getattr(w, "btn_min", None)
if btn is None:
    fails.append("btn_min 未创建")
else:
    if btn.master is not w.title_bar:
        fails.append("btn_min 不在 title_bar 内")
    if btn.cget("text") != "—":
        fails.append("btn_min 文字不是 —: %r" % btn.cget("text"))
    if btn.winfo_x() >= w.btn_close.winfo_x():
        fails.append("btn_min 未落在 btn_close 左侧: min.x=%d close.x=%d"
                     % (btn.winfo_x(), w.btn_close.winfo_x()))
    if not btn.bind("<Button-1>"):
        fails.append("btn_min 未绑定 <Button-1>")

# ② 主题跟随
if btn is not None:
    fg0 = str(btn.cget("fg")).lower()
    w._apply_theme("dark", persist=False)
    root.update()
    fg1 = str(btn.cget("fg")).lower()
    w._apply_theme("light", persist=False)
    root.update()
    fg2 = str(btn.cget("fg")).lower()
    if fg0 == fg1:
        fails.append("切到 dark 后 btn_min fg 未变化: %s" % fg1)
    if fg2 != fg0:
        fails.append("切回 light 后 btn_min fg 未复原: %s != %s" % (fg2, fg0))

# ③④⑤ 真实最小化
u = ctypes.windll.user32
hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
x0, y0 = root.winfo_x(), root.winfo_y()
w0, h0 = root.winfo_width(), root.winfo_height()

w._minimize_to_taskbar()
root.update()
if not u.IsIconic(hwnd):
    fails.append("调用后未最小化（IsIconic=0）→ 可能退化成 withdraw")

ex = u.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
if ex & 0x00000080:
    fails.append("仍带 WS_EX_TOOLWINDOW（任务栏不会出现入口）")
if not (ex & 0x00040000):
    fails.append("缺少 WS_EX_APPWINDOW")

u.ShowWindow(hwnd, 9)  # SW_RESTORE
root.update()
if u.IsIconic(hwnd):
    fails.append("SW_RESTORE 未能恢复（仍 IsIconic=1）")
if (root.winfo_x(), root.winfo_y()) != (x0, y0):
    fails.append("恢复后位置漂移: (%d,%d)->(%d,%d)"
                 % (x0, y0, root.winfo_x(), root.winfo_y()))
if (root.winfo_width(), root.winfo_height()) != (w0, h0):
    fails.append("恢复后尺寸变化: (%d,%d)->(%d,%d)"
                 % (w0, h0, root.winfo_width(), root.winfo_height()))

root.destroy()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("PASS: 最小化按钮结构/×左侧/主题跟随/IsIconic/APPWINDOW样式/恢复保持位置尺寸")
