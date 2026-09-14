# -*- coding: utf-8 -*-
"""回归：菜单层级/置顶守护/静置存活/清扫关闭（进程内）。"""
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

def open_menu(t):
    w._popup_menu(Ev(460, 380, t))
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

def is_above(m):
    return bool(int(root.tk.call("wm", "stackorder", m, "isabove", root)))

m = open_menu(1000)
if m.winfo_x() != 460 or m.winfo_y() != 380:
    fails.append(f"菜单位置: ({m.winfo_x()},{m.winfo_y()})")
if not bool(m.attributes("-topmost")) or not bool(root.attributes("-topmost")):
    fails.append("双置顶失败")

# 静置 3 秒存活
t0 = time.time()
while time.time() - t0 < 3.0:
    root.update()
    time.sleep(0.02)
if not (w._menu_win is not None and bool(m.winfo_exists())):
    fails.append("菜单静置 3 秒内自动关闭")

# 被盖守护：菜单拽下 topmost → 一次心跳救回
m.attributes("-topmost", False)
root.update()
w._poll()
root.update()
if not bool(m.attributes("-topmost")):
    fails.append("菜单守护未恢复 topmost")

# 呼出同事件放行 / 内部点击不误关 / 外部点击关 / Esc 关
w._menu_sweep_click(Ev(460, 380, 1000))
if w._menu_win is None:
    fails.append("同事件被误杀")
w._menu_sweep_click(Ev(460, 380, 3100))
if w._menu_win is None:
    fails.append("菜单内点击被误关")
w._menu_sweep_click(Ev(50, 50, 3200))
if w._menu_win is not None:
    fails.append("外部点击未关闭")
open_menu(4000)
w._menu_sweep_esc(Ev(0, 0, 4100))
if w._menu_win is not None:
    fails.append("Esc 未关闭")

# 关菜单后置顶自愈
root.attributes("-topmost", False)
w._poll()
root.update()
if not bool(root.attributes("-topmost")):
    fails.append("置顶自愈失效")

root.destroy()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("PASS: 位置/双置顶/静置存活/被盖守护/清扫关闭/自愈")
