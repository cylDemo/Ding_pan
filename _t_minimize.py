# -*- coding: utf-8 -*-
"""回归：标题栏「—」= 隐藏浮窗，Ctrl+Alt+D 双向切换（进程内，真实 Tk + Win32）。

设计约定（v2.0.4 起）：
  · 点「—」→ `withdraw()` 隐藏：既不进任务栏，也不留 Alt+Tab 条目；
  · Ctrl+Alt+D → 可见 ↔ 隐藏 双向切换，并负责把「被 Windows 最小化」的窗口取回；
  · 仅当全局热键注册失败时才退化为 Win32 最小化到任务栏（保底入口）。

覆盖：
  ① 按钮存在、在 title_bar 内、文字为 —、位于 × 左侧（Windows「—×」惯例）、已绑定点击；
  ② 切主题后 fg 跟随（_restyle_widgets / _sweep_theme_colors 双路径）；
  ③ 热键可用时点「—」→ 窗口被隐藏（state=withdrawn、IsWindowVisible=0），
     且**不是** iconic —— 这是「隐藏」而不是「最小化」的关键判据；
  ④ 隐藏态按热键 → 恢复为 normal 且可见，位置/尺寸保持不变；
  ⑤ 再按一次热键 → 又回到隐藏（双向切换）；
  ⑥ 热键不可用（_hotkey_ok=False）时点「—」→ 走保底路径：真最小化
     （IsIconic=1）且带上 WS_EX_APPWINDOW（任务栏有入口），不会「消失且找不回」；
  ⑦ 从 iconic 态按热键 → 必须被取回为 normal（回归 v2.0.3 的真 bug：
     旧实现把 iconic 误判为「可见」而执行 withdraw，导致窗口彻底找不回）。
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

u = ctypes.windll.user32
hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


# ① 结构 + 位置
btn = getattr(w, "btn_min", None)
check(btn is not None, "btn_min 未创建")
if btn is not None:
    check(btn.master is w.title_bar, "btn_min 不在 title_bar 内")
    check(btn.cget("text") == "—", "btn_min 文字不是 —: %r" % btn.cget("text"))
    check(btn.winfo_x() < w.btn_close.winfo_x(),
          "btn_min 未落在 btn_close 左侧: min.x=%d close.x=%d"
          % (btn.winfo_x(), w.btn_close.winfo_x()))
    check(bool(btn.bind("<Button-1>")), "btn_min 未绑定 <Button-1>")

# ② 主题跟随
if btn is not None:
    fg0 = str(btn.cget("fg")).lower()
    w._apply_theme("dark", persist=False)
    root.update()
    fg1 = str(btn.cget("fg")).lower()
    w._apply_theme("light", persist=False)
    root.update()
    fg2 = str(btn.cget("fg")).lower()
    check(fg0 != fg1, "切到 dark 后 btn_min fg 未变化: %s" % fg1)
    check(fg2 == fg0, "切回 light 后 btn_min fg 未复原: %s != %s" % (fg2, fg0))

x0, y0 = root.winfo_x(), root.winfo_y()
w0, h0 = root.winfo_width(), root.winfo_height()

# ③ 热键可用 → 点「—」应「隐藏」而非「最小化」
w._hotkey_ok = True
w._on_min_click()
root.update()
check(root.state() == "withdrawn",
      "点「—」后 state 应为 withdrawn，实际 %r" % root.state())
check(not u.IsWindowVisible(hwnd), "隐藏后窗口仍可见（IsWindowVisible=1）")
check(not u.IsIconic(hwnd), "隐藏后却是最小化态（IsIconic=1）→ 不是预期语义")

# ④ 隐藏态按热键 → 恢复
w._toggle_visible()
root.update()
check(root.state() == "normal",
      "隐藏态按热键后 state 应为 normal，实际 %r" % root.state())
check(bool(u.IsWindowVisible(hwnd)), "按热键后窗口不可见")
check((root.winfo_x(), root.winfo_y()) == (x0, y0),
      "恢复后位置漂移: (%d,%d)->(%d,%d)" % (x0, y0, root.winfo_x(), root.winfo_y()))
check((root.winfo_width(), root.winfo_height()) == (w0, h0),
      "恢复后尺寸变化: (%d,%d)->(%d,%d)" % (w0, h0, root.winfo_width(), root.winfo_height()))

# ⑤ 再按一次 → 又隐藏（双向）
w._toggle_visible()
root.update()
check(root.state() == "withdrawn",
      "再次按热键后 state 应为 withdrawn，实际 %r" % root.state())
w._toggle_visible()
root.update()
check(root.state() == "normal", "第三次按热键应恢复为 normal，实际 %r" % root.state())

# ⑥ 热键不可用 → 点「—」退化为最小化到任务栏
w._hotkey_ok = False
w._on_min_click()
root.update()
check(bool(u.IsIconic(hwnd)), "热键不可用时点「—」未最小化（IsIconic=0）")
ex = u.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
check(not (ex & 0x00000080), "保底路径仍带 WS_EX_TOOLWINDOW（任务栏不会出现入口）")
check(bool(ex & 0x00040000), "保底路径缺少 WS_EX_APPWINDOW")

# ⑦ 从 iconic 态按热键 → 必须被取回（v2.0.3 的真 bug 回归）
w._toggle_visible()
root.update()
check(not u.IsIconic(hwnd),
      "从最小化态按热键未取回（仍 IsIconic=1）→ 复现了「最小化后按热键就找不回」")
check(root.state() == "normal",
      "从最小化态取回后 state 应为 normal，实际 %r" % root.state())
check(bool(u.IsWindowVisible(hwnd)), "从最小化态取回后仍不可见")
check((root.winfo_x(), root.winfo_y()) == (x0, y0),
      "取回后位置漂移: (%d,%d)->(%d,%d)" % (x0, y0, root.winfo_x(), root.winfo_y()))
check((root.winfo_width(), root.winfo_height()) == (w0, h0),
      "取回后尺寸变化: (%d,%d)->(%d,%d)" % (w0, h0, root.winfo_width(), root.winfo_height()))

root.destroy()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("PASS: 「—」隐藏(非最小化)/热键双向切换/位置尺寸保持/保底最小化/iconic 取回")
