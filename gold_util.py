# -*- coding: utf-8 -*-
"""盯盘 · 无状态工具函数（可脱 Tk 单测）。

从 gold_widget.py 迁出（Tier 0.2）。这些函数原先挂在 `Widget` 上，但
**不使用任何实例状态**（零 self 引用），放在类里只是历史包袱：
它们让"想单测一个字符串截断/时段判断"变成"必须起一个真窗口"。

边界说明（迁出前评估报告称这 4 个"tk 调用 0"——其中 `fit_name` 不成立）：
  · `sign` / `area_glyph` / `gold_window_active`：纯函数，零依赖，可直接 import；
  · `fit_name`：**依赖 Tk**——用 tkfont 度量字宽，调用时须已有（默认）Tk root，
    root 不存在时按原语义吞掉异常并原样返回名称。故"import 即可测"只对前三个成立。
"""

from datetime import datetime
from tkinter import font as tkfont

from gold_theme import F_STOCK_NAME, STOCK_COL_WIDTHS

# 金价自动刷新时段窗口（本机本地时间）：工作日 9:30~18:00。
# 窗口外不发任何京东请求（手动「立即刷新」不受限）；窗口开启瞬间会立即补一次。
GOLD_WIN_DAYS = (0, 1, 2, 3, 4)      # Monday=0 … Friday=4
GOLD_WIN_START = (9, 30)             # 含起点
GOLD_WIN_END = (18, 0)               # 不含终点


def sign(n):
    """正数前缀 "+"，其余为空串（涨跌幅展示用）。"""
    return "+" if (n or 0) > 0 else ""


def area_glyph(collapsed):
    """内容在按钮**下方**的区块（股票/板块区）箭头方向：

    展开中显示 ︾（点击收起，内容向下收拢）；收起中显示 ︽（点击展开）。
    金价区内容在按钮上方，方向相反（展开中 ︽），同一套"箭头指向内容
    收拢方向"的逻辑。
    """
    return "︽" if collapsed else "︾"


def gold_window_active(now=None):
    """金价自动轮询是否处于刷新时段窗口内（工作日 9:30~18:00，本地时间）。"""
    now = now or datetime.now()
    if now.weekday() not in GOLD_WIN_DAYS:
        return False
    m = now.hour * 60 + now.minute
    s = GOLD_WIN_START[0] * 60 + GOLD_WIN_START[1]
    e = GOLD_WIN_END[0] * 60 + GOLD_WIN_END[1]
    return s <= m < e


def fit_name(name):
    """按名称列（col 0）宽度截断过长股票名，超出部分以 … 结尾。

    列宽固定方案下列宽不可被内容撑大，否则删除按钮会被推出窗口外。
    需要已存在的（默认）Tk root 才能度量字宽；无 root 时按原语义返回原名。
    """
    try:
        f = tkfont.Font(font=F_STOCK_NAME)
    except Exception:
        return name
    maxw = STOCK_COL_WIDTHS[0] - 8  # 扣除 Label 默认内边距余量
    if f.measure(name) <= maxw:
        return name
    out = name
    while out and f.measure(out + "…") > maxw:
        out = out[:-1]
    return (out + "…") if out else name
