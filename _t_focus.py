# -*- coding: utf-8 -*-
"""探针：菜单打开后静置 5s，观察 FocusOut 自发触发点与 1s 心跳的关系。"""
import time, json, tempfile, os
import gold_widget as gw

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 0.97, "mini": True, "theme": "dark"}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

t0 = time.time()
def ts(): return f"t={time.time()-t0:5.2f}s"

w = gw.Widget(); root = w.root
root.geometry("+300+300")
root.deiconify(); root.update()

# 埋点：_close_menu 触发即打印
_orig_close = gw.Widget._close_menu
def spy_close(self):
    print(f"{ts()} [close-menu] 被调用")
    _orig_close(self)
gw.Widget._close_menu = spy_close

class Ev: pass
ev = Ev(); ev.x_root = 460; ev.y_root = 380
w._popup_menu(ev)
m = w._menu_win
print(f"{ts()} [popup] menu={m} viewable={m.winfo_viewable()}")

# 菜单焦点事件明细
m.bind("<FocusIn>",  lambda e: print(f"{ts()} [FocusIn ] detail={e.type}"))
m.bind("<FocusOut>", lambda e: print(f"{ts()} [FocusOut] detail={e.type}"))
m.bind("<Map>",      lambda e: print(f"{ts()} [Map]"))
m.bind("<Unmap>",    lambda e: print(f"{ts()} [Unmap]"))
root.bind("<FocusIn>",  lambda e: print(f"{ts()} [root FocusIn ]"))
root.bind("<FocusOut>", lambda e: print(f"{ts()} [root FocusOut]"))

# 静置 5 秒（期间 _poll 心跳照常跑）
while time.time() - t0 < 5.0:
    root.update()
    time.sleep(0.02)
alive = w._menu_win is not None and bool(m.winfo_exists())
print(f"{ts()} [result] menu 存活={alive}")
w._close_menu(); root.destroy()
