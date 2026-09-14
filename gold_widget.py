#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金盯盘 · 桌面角落小浮窗（免登录）

无边框置顶小窗，常驻屏幕角落，定时刷新京东黄金公开行情。
需带 tkinter 的解释器（本机系统 Python 3.12 可用），建议用 pythonw.exe 启动以隐藏控制台。

交互：
  拖动    按住窗口任意处拖动
  双击    迷你 / 标准 视图切换
  右键    菜单（刷新 / 置顶 / 透明度 / 退出）
"""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import font as tkfont

import gold_data
import glog

APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
           else os.path.dirname(os.path.abspath(__file__)))

# ── 日志（统一走 glog，替代历史 widget.log 的裸文件追加）──
# pythonw / PyInstaller --noconsole 下 sys.stdout/stderr 为 None，此时 print
# 会抛 AttributeError 且信息彻底丢失 → 由 glog 接管到日志文件。
# 相对旧实现的改进：
#   · utf-8 统一写盘（旧日志存在 GBK / UTF-8 混写乱码）
#   · 1MB × 3 轮转（旧日志只增不减，已涨到 73KB 无上限）
#   · 主目录脱敏（旧日志含 C:\Users\<name>\... 本机路径，外发即信息泄漏）
# 日志落用户主目录（~/.gold_widget.log）而非 exe 目录：装到 Program Files
# 后 exe 目录通常不可写。
glog.install_excepthook()
if sys.stdout is None or sys.stderr is None:
    glog.redirect_std_streams()

# ── Windows 高分屏清晰度 ──
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

APP_NAME = "盯盘"
__version__ = "2.0.1"          # 与 version_info.txt 保持同步；用于排障时确认用户手上的版本
CONF_PATH = os.path.join(os.path.expanduser("~"), ".gold_widget.json")

# 刷新间隔：命令行 --interval 可覆盖。实测京东公开接口 5s 级连续调用零失败、
# 3s 起会出现「上次未拉完就发起下次」的重叠，故最小锁定 3s。
# 默认 5s 保持实时节奏；配额压力由「刷新时段窗口」化解：
# 自动轮询只在工作时间 GOLD_WIN 内发车（约 8.5h × 720 ≈ 6100 次/天），
# 盘外零调用；若窗口内配额仍被打爆，另有 ≥300s 长退避兜底（见 _poll）。
MIN_INTERVAL = 3
DEFAULT_INTERVAL = 5

# 金价自动刷新时段窗口（本机本地时间）：工作日 9:30~18:00。
# 窗口外不发任何京东请求（手动「立即刷新」不受限）；窗口开启瞬间会立即补一次。
GOLD_WIN_DAYS = (0, 1, 2, 3, 4)      # Monday=0 … Friday=4
GOLD_WIN_START = (9, 30)             # 含起点
GOLD_WIN_END = (18, 0)               # 不含终点

# 股票行情独立快轨：与金价彻底解耦（双轨制）。
# 腾讯行情（qt.gtimg.cn）为单次 HTTP GET、速率宽容，实测 2s 级连续调用稳定，
# 因此股票不再受金价 3s 下限拖累；命令行 --stock-interval 可覆盖。
MIN_STOCK_INTERVAL = 1
DEFAULT_STOCK_INTERVAL = 2

# 配色：白底极简 + 蓝高亮，红涨绿跌。
# 所有颜色都通过 THEME 间接读取（dict 风格），支持运行时切换主题。
THEMES = {
    "light": {
        "bg":     "#FFFFFF",   # 窗口主背景
        "border": "#DCDFE4",   # 1px 边框
        "fg":     "#111418",   # 主文字
        "fg2":    "#5B6169",   # 次要文字
        "fg3":    "#9AA0A8",   # 弱化文字（时间、副信息）
        "line":   "#EDEEF0",   # 分隔线
        "up":     "#E5342B",   # 涨（中国 A 股惯例：红涨）
        "down":   "#1A9E5C",   # 跌
        "blue":   "#3B82F6",   # 高亮
        "hover":  "#F2F4F7",   # 悬浮/菜单
        "pill":   "#E5E5E5",   # 搜索胶囊底色（设计稿 rgba(229,229,229,1)）
    },
    "dark": {
        "bg":     "#15171B",
        "border": "#2A2D33",
        "fg":     "#F2F4F7",
        "fg2":    "#A8AEB7",
        "fg3":    "#6B7178",
        "line":   "#26292F",
        "up":     "#FF5A4D",
        "down":   "#26C77A",
        "blue":   "#3B82F6",
        "hover":  "#1E2127",
        "pill":   "#262A31",   # 深色模式搜索胶囊底色
    },
}

class _Theme:
    """当前主题持有器：直接读属性拿到最新值，切主题时遍历 widget 重 config。"""
    def __init__(self, mode="light"):
        self._d = dict(THEMES.get(mode, THEMES["light"]))
    def set(self, mode):
        self._d = dict(THEMES[mode])
    def get(self, k):
        return self._d[k]
    # 属性风格访问，简化代码
    def __getattr__(self, k):
        if k.startswith("_"): raise AttributeError(k)
        return self._d[k]

THEME = _Theme()

F_TITLE = ("Microsoft YaHei UI", 9)
F_SMALL = ("Microsoft YaHei UI", 9)
F_NAME  = ("Microsoft YaHei UI", 10)
F_MID   = ("Microsoft YaHei UI", 10, "bold")
F_BIG   = ("Microsoft YaHei UI", 22, "bold")
# 股票行用字
F_STOCK_NAME = ("Microsoft YaHei UI", 10, "bold")   # 股票名（带 × 删除）
F_STOCK_PRC  = ("Microsoft YaHei UI", 13, "bold")   # 价格
F_STOCK_PCT  = ("Microsoft YaHei UI", 11, "bold")   # 涨跌%
F_STOCK_AMT  = ("Microsoft YaHei UI", 10)           # 成交额
F_SEARCH     = ("Microsoft YaHei UI", 11)           # 搜索框

# 高度参数（仅用于标准模式动态计算）
HEADER_H    = 100   # 标题栏 + 金价行 + 状态栏 ≈ 100
SEARCH_PILL_H = 26  # 搜索胶囊条高度（设计稿 20dp，放大适配 11pt 字体）
STOCKS_HEADER_H = 18  # 股票区列标题行高度（股票名称/价格/涨幅/成交额）
STOCK_ROW_H = 40    # 兜底估算用：每只股票双行布局高度（实测约 52px，窗口高度以实测为准）
STOCKS_MAX  = 8     # 最多展示 8 只股票
STOCKS_VISIBLE = 3  # 股票区固定可视行数：≤3 只按实际高度展示，>3 只锁定 3 行 + 滚轮滚动
SEARCH_ROW_H = 28   # 搜索结果每行高度
SEARCH_MAX_ROWS = 6

# 股票区 5 个数据列的显式列宽（px）：表头（stocks_header）与数据区
# （stocks_box）是两个独立容器，grid 均分（uniform/weight）会受各自内容
# 最小宽度影响，两容器字体不同（表头 8pt / 数据 10pt bold）会导致列边界
# 错位、表头与数值对不齐。两边用同一组固定像素列宽（weight=0）即可保证
# 列边界严格一致。各列 ≥ 数据行 Label 实测 reqwidth（含默认 padx）。
# col0=84 可完整容纳 6 字符名（如"有色ETF银华"），更长名称渲染时截断加 …。
# 合计 326 + 删除列 18 = 344 = 容器宽（窗口 368 减内边距）。
STOCK_COL_WIDTHS = (84, 56, 64, 58, 64)  # 名称/价格/涨幅/换手率/成交额

# 板块区（上中下三段布局的"下"段）：与股票区同构的 固定表头 + 滚动画布。
SECTORS_MAX     = 8   # 最多 8 个板块
SECTORS_VISIBLE = 2   # 默认可视 2 个，>2 个滚轮滚动（窗口高度锁定）
SECTORS_HEADER_H = 18
SECT_COL_WIDTHS = (84, 68, 56, 56, 62)  # 板块名称/资金流入(亿)/涨幅/换手率/概念强度


# 标准模式窗口高度改为实测驱动（见 Widget._std_height / _layout_stocks）：
# 空态固定 164；有股票时 = 164 + 股票区实测可视高度（≤3 只实高，>3 只锁定 3 行）。

SIZE_MINI = (248, 124)  # 迷你模式固定
SIZE_STD_BASE = (384, 240)  # 标准模式基础（容纳 3 只股票；按 watchlist 数量动态拉伸）。
# 384：正文可用 358px——板块/股票行的实际请求宽（352/346，真实数值如"第30名"
# 会比预留列宽略宽撑行）+ 窗口左右各 ~13px 内边距，delete 列不再被右缘裁切。


SIZE = {  # 迷你 / 标准（标准高度会在 _apply_size 里按 watchlist 动态覆盖）
    True:  SIZE_MINI,
    False: SIZE_STD_BASE,
}


# 配置损坏时的最近一次提示（供 UI 一次性展示；不持久化）
LAST_CONF_ERROR = None


def _atomic_write_json(path, obj):
    """原子写 JSON：同目录临时文件 + fsync + os.replace。

    旧实现直接以 "w" 覆写配置文件：写入瞬间崩溃 / 断电 / 被杀软终止会留下
    被截断的半截 JSON → 下次启动静默回退内置默认值，用户自选股/板块凭空消失。
    os.replace 在同一文件系统上是原子的——要么旧内容完整，要么新内容完整。
    """
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".gold_widget.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_conf():
    global LAST_CONF_ERROR
    d = {"x": None, "y": None, "mini": True, "alpha": 0.97, "topmost": True,
         "theme": "light", "watchlist": ["601069", "002738", "600487"],
         "sectors": ["BK1136", "BK1617"],  # 光通信模块 / 黄金（东财板块代码）
         "gold_collapsed": False}
    raw = {}
    if os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("配置根节点不是 JSON 对象")
            d.update(raw)
        except Exception as e:
            # 损坏绝不静默重置（否则用户只会觉得"我的股票莫名没了"）：
            # 备份原文件保留证据 + 落日志 + 由 UI 一次性告知。
            raw = {}
            bak = CONF_PATH + ".corrupt"
            if os.path.exists(bak):
                bak = "%s.%d" % (CONF_PATH + ".corrupt", int(time.time()))
            try:
                os.replace(CONF_PATH, bak)
            except Exception as e:
                # 备份改名失败（占用/权限）：原文件留在原处，下次启动仍会解析失败 →
                # 必须留痕，否则用户会反复"自选股莫名消失"却查不到原因。
                bak = ""
                glog.warn(f"损坏配置备份失败（原文件保留在原处）: {e}")
            LAST_CONF_ERROR = ("配置文件损坏，已重置为默认"
                               + (f"（原文件备份为 {os.path.basename(bak)}）" if bak else ""))
            glog.error(f"配置解析失败已重置: {e}")
    if d.get("theme") not in THEMES:
        d["theme"] = "light"
    d["gold_collapsed"] = bool(d.get("gold_collapsed"))
    # watchlist 归一化：纯字符串列表、去重保序
    wl = d.get("watchlist") or []
    if not isinstance(wl, list):
        wl = []
    seen = set()
    norm = []
    for c in wl:
        c = str(c).strip()
        if c and c not in seen:
            seen.add(c)
            norm.append(c)
    d["watchlist"] = norm
    # sectors 归一化：大写、去重保序（与 watchlist 同一套规则）
    sl = d.get("sectors") or []
    if not isinstance(sl, list):
        sl = []
    seen2 = set()
    norm_s = []
    for c in sl:
        c = str(c).strip().upper()
        if c and c not in seen2:
            seen2.add(c)
            norm_s.append(c)
    d["sectors"] = norm_s
    # 首次启动 / 老用户升级时持久化默认 watchlist/sectors，避免每次都用代码默认值
    if "watchlist" not in raw or "sectors" not in raw:
        try:
            _atomic_write_json(CONF_PATH, d)
        except Exception as e:
            glog.warn(f"首次配置写入失败: {e}")
    return d


def save_conf(c):
    try:
        _atomic_write_json(CONF_PATH, c)
    except Exception as e:
        glog.error(f"配置写入失败: {e}")


def sign(n):
    return "+" if (n or 0) > 0 else ""


class Widget:
    def __init__(self, interval=DEFAULT_INTERVAL, stock_interval=DEFAULT_STOCK_INTERVAL):
        self.conf = load_conf()
        # 配置曾损坏被重置时，首屏提示一次（详见 load_conf / glog 日志）
        self._conf_notice = LAST_CONF_ERROR
        self._conf_notice_until = (time.time() + 10) if LAST_CONF_ERROR else 0.0
        # 同步主题：先调 _apply_theme 让所有 widget 创建时用正确色
        THEME.set(self.conf.get("theme", "light"))
        self.interval = max(MIN_INTERVAL, int(interval))
        # 股票独立快轨（不跟随金价的 3s 下限）
        self.stock_interval = max(MIN_STOCK_INTERVAL, int(stock_interval))
        self.q = queue.Queue()
        self.data = None
        self.dragging = False
        self._dx = self._dy = 0
        self._fetching = False          # 金价拉取防重叠
        self._fail_streak = 0
        self._stock_fetching = False    # 股票拉取防重叠（独立锁，互不阻塞）
        self._stock_fail_streak = 0
        self._last = time.time()        # 金价上次发车时间（首帧已由 __init__ 线程发车，
        self._stock_last = time.time()  # 不再让 _poll 首 tick 因 0 值重复发一次）
        self._menu_win = None  # 自绘右键菜单浮层（无边框 Toplevel，见 _popup_menu）
        # 隐私掩码：True 时所有行情数据以 "****" 展示（默认明文，不持久化）
        self._hide_data = False
        # 股票 / 搜索状态
        self.stock_data = {}        # {code: {name, price, change_pct, amount_yi, turnover}}
        self.sect_data = {}         # {code: {name, inflow_yi, change_pct, turnover, strength}}
        self.stock_rows = []        # [(code, frame, name_l, price_l, pct_l, amt_l, del_btn, code_l), ...]
        self._search_results = []
        self._search_after_id = None  # 防抖计时器 id
        self._search_box_visible = False  # 当前是否在展示搜索结果（覆盖股票区）
        self._search_ph_on = False  # placeholder 是否显示在 Entry 内
        self._suppress_trace = False  # placeholder 增删期间抑制 _on_search_change

        # 启动计时探针：把各阶段耗时写进日志，便于用户反馈"启动慢"时定位
        _bt = time.perf_counter()

        def _boot(msg):
            glog.info(f"[boot] {msg} +{int((time.perf_counter() - _bt) * 1000)}ms")

        _boot("Tk 创建前")
        self.root = tk.Tk()
        _boot("Tk 创建后")
        print(f"[init] Tk 已创建, 解释器={sys.executable}", flush=True)
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.configure(bg=THEME.border)
        self.root.attributes("-topmost", bool(self.conf["topmost"]))
        self.root.attributes("-alpha", float(self.conf["alpha"]))
        print("[init] 窗口属性设置完成", flush=True)

        # 1px 外框 + 主题内容区
        self.outer = tk.Frame(self.root, bg=THEME.border, padx=1, pady=1)
        self.outer.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.outer, bg=THEME.bg)
        self.inner.pack(fill="both", expand=True)

        self._build_title()
        _boot("标题栏完成")
        self._build_body()
        _boot("主体完成")

        for w in (self.inner, self.title_bar, self.body):
            w.bind("<ButtonPress-1>", self._start_move)
            w.bind("<B1-Motion>", self._do_move)
            w.bind("<ButtonRelease-1>", self._stop_move)
        # 迷你/标准切换：仅标题栏区域双击生效。
        # 不能 bind 到 root——root 在所有 widget 的 bindtags 里，双击搜索框（选中文本
        # 的高频操作）、双击股票区都会误触 toggle_mini，把搜索条/下拉/股票区全部藏掉，
        # 表现为“下拉结果突然消失”。
        for tw in (self.title_bar, self.dot, self.t_label, self.t_time):
            tw.bind("<Double-Button-1>", lambda e: self.toggle_mini())
        self.root.bind("<Button-3>", self._popup_menu)
        # 右键菜单的全局关闭清扫：一次性注册、菜单关闭时自哑（见 _menu_sweep_click）。
        # bindtags 顺序 widget→class→toplevel→all 保证呼出菜单那次右键先走 _popup_menu，
        # 清扫再靠事件时间戳放行同一次点击。
        self.root.bind_all("<Button-1>", self._menu_sweep_click, add="+")
        self.root.bind_all("<Button-3>", self._menu_sweep_click, add="+")
        self.root.bind_all("<Escape>", self._menu_sweep_esc, add="+")
        self._menu_open_ev_time = 0
        # 股票区 >3 只时滚轮滚动查看（handler 内做边界/状态校验，不影响其他区域）
        self.root.bind_all("<MouseWheel>", self._on_stocks_wheel)

        self._place()
        _boot("初始定位完成")
        self._apply_size()
        _boot("尺寸应用完成")
        self.root.update_idletasks()
        _boot("update_idletasks 完成")
        print(f"[init] 窗口 x={self.root.winfo_x()} y={self.root.winfo_y()} "
              f"size={self.root.winfo_width()}x{self.root.winfo_height()} "
              f"viewable={self.root.winfo_viewable()}", flush=True)

        self.root.after(100, self._poll)
        # 双轨首帧：金价与股票各自拉取，互不等待
        threading.Thread(target=self._worker, daemon=True).start()
        self.fetch_stock()
        self._start_global_hotkey()

    # ── 全局热键（仅打包模式启用） ──
    # Ctrl+Alt+D 唤出/隐藏浮窗。RegisterHotKey(None, ...) 注册到调用线程，
    # 需在该线程跑 GetMessage 循环；WM_HOTKEY 到达后经队列转交 Tk 主线程。
    def _start_global_hotkey(self):
        if not getattr(sys, "frozen", False):
            return

        def thread():
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            MOD_ALT, MOD_CONTROL, VK_D = 0x0001, 0x0002, 0x44
            WM_HOTKEY, HOTKEY_ID = 0x0312, 0xB19C
            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_D):
                print("[warn] 全局热键 Ctrl+Alt+D 注册失败（可能被其他程序占用）", flush=True)
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.q.put(("hotkey", None))
            user32.UnregisterHotKey(None, HOTKEY_ID)

        threading.Thread(target=thread, daemon=True, name="hotkey").start()

    def _toggle_visible(self):
        st = self.root.state()
        print(f"[hotkey] toggle: state={st}", flush=True)
        if st == "withdrawn":
            self.root.deiconify()
            # overrideredirect(True) 窗口在 Windows 上 withdraw 后 deiconify
            # 可能不重新映射：强制刷新窗口管理器状态后 lift 回来
            self.root.update_idletasks()
            self.root.attributes("-topmost", bool(self.conf["topmost"]))
            self.root.lift()
        else:
            self.root.withdraw()

    # ── 界面 ──
    def _build_title(self):
        self.title_bar = tk.Frame(self.inner, bg=THEME.bg, height=28)
        self.title_bar.pack(fill="x", padx=10, pady=(8, 0))
        self.title_bar.pack_propagate(False)

        self.dot = tk.Label(self.title_bar, text="●", fg=THEME.blue, bg=THEME.bg, font=("Microsoft YaHei UI", 7))
        self.dot.pack(side="left")
        self.t_label = tk.Label(self.title_bar, text=APP_NAME, fg=THEME.fg2, bg=THEME.bg, font=F_TITLE)
        self.t_label.pack(side="left", padx=(4, 0))

        self.btn_close = tk.Label(self.title_bar, text="×", fg=THEME.fg3, bg=THEME.bg,
                                  font=("Microsoft YaHei UI", 10), cursor="hand2")
        self.btn_close.pack(side="right", padx=(2, 0))
        self.btn_close.bind("<Button-1>", lambda e: self.quit())
        self.btn_close.bind("<Enter>", lambda e: self.btn_close.config(fg=THEME.up))
        self.btn_close.bind("<Leave>", lambda e: self.btn_close.config(fg=THEME.fg3))

        self.t_time = tk.Label(self.title_bar, text="--:--", fg=THEME.fg3, bg=THEME.bg, font=F_SMALL)
        self.t_time.pack(side="right", padx=(0, 6))

        self.btn_theme = tk.Label(self.title_bar, text="☼", fg=THEME.fg3, bg=THEME.bg,
                                  font=("Segoe UI Symbol", 10), cursor="hand2")
        self.btn_theme.pack(side="right", padx=(0, 2))
        self.btn_theme.bind("<Button-1>", lambda e: self._toggle_theme())
        self.btn_theme.bind("<Enter>", lambda e: self.btn_theme.config(fg=THEME.up))
        self.btn_theme.bind("<Leave>", lambda e: self.btn_theme.config(fg=THEME.fg3))

        # 眼睛按钮（主题切换按钮左侧）：点击切换数据掩码（明文 <-> "****"）。
        # pack side="right" 按打包顺序从右往左排，晚于 btn_theme 打包即落在其左侧。
        self.btn_eye = tk.Label(self.title_bar, text="👁", fg=THEME.fg3, bg=THEME.bg,
                                font=("Segoe UI Symbol", 10), cursor="hand2")
        self.btn_eye.pack(side="right", padx=(0, 4))
        self.btn_eye.bind("<Button-1>", lambda e: self._toggle_hide_data())
        self.btn_eye.bind("<Enter>", lambda e: self.btn_eye.config(fg=THEME.up))
        self.btn_eye.bind("<Leave>", lambda e: self._update_eye_btn())

        # 搜索入口已下移到金价下方的常驻紧凑搜索条（见 _build_body）

    def _build_body(self):
        self.body = tk.Frame(self.inner, bg=THEME.bg)
        self.body.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        # 主价格行（金价，迷你 / 标准都显示）
        self.m_name = tk.Label(self.body, text="京东24h金价", fg=THEME.fg3, bg=THEME.bg, font=F_NAME)
        self.m_name.pack(anchor="w")

        # 注意必须挂到 self：_restyle_widgets 按属性遍历刷色，局部变量会漏刷，
        # 表现为切主题后价格行中段残留旧主题色块（白底残留白块 / 暗底残留黑块）。
        self.price_row = tk.Frame(self.body, bg=THEME.bg)
        self.price_row.pack(fill="x", pady=(1, 0))
        # 跟 m_chg 同样的问题：Windows tkinter 的 22pt 大字 Label 裸区域会保留一层
        # system 默认浅色（即使 bg=THEME.bg），必须用 Frame 包裹兜底，否则切到 dark
        # 后 952.97 数字右侧会出现明显白色块。
        self.m_price_box = tk.Frame(self.price_row, bg=THEME.bg)
        self.m_price_box.pack(side="left")
        self.m_price = tk.Label(self.m_price_box, text="—", fg=THEME.fg, bg=THEME.bg,
                                font=F_BIG, borderwidth=0, relief="flat", padx=0, pady=0)
        self.m_price.pack()
        self.m_chg_box = tk.Frame(self.price_row, bg=THEME.bg)
        self.m_chg_box.pack(side="right", pady=(10, 0))
        self.m_chg = tk.Label(self.m_chg_box, text="", fg=THEME.fg3, bg=THEME.bg,
                              font=("Microsoft YaHei UI", 12, "bold"),
                              borderwidth=0, relief="flat")
        self.m_chg.pack()

        # ── 搜索条：Canvas 圆角椭圆长条（常驻，单态）──
        # ── 分隔线：金价区 / 股票区的分界（纯视觉）──
        self.divider = tk.Frame(self.body, bg=THEME.line, height=1)
        self.divider.pack(fill="x", pady=(6, 4))

        # 收起/展开开关：紧贴分隔线正下方的小箭头按钮（右对齐）。
        # ︽ = 点击收起金价区（箭头向上，内容上收）；︾ = 点击展开。
        # 双箭头字形取自 CJK 竖排符号（U+FE3D/U+FE3E），雅黑原生单色渲染。
        # padx/pady 清零：与股票/板块区的同款按钮右缘严格垂直对齐。
        self.gold_toggle = tk.Label(self.body, text="︽", fg=THEME.fg3, bg=THEME.bg,
                                    font=("Microsoft YaHei UI", 8), cursor="hand2",
                                    anchor="e", padx=0, pady=0)
        self.gold_toggle.pack(fill="x")
        self.gold_toggle.bind("<Button-1>", lambda e: self._toggle_gold())
        self.gold_toggle.bind("<Enter>", lambda e: self.gold_toggle.config(fg=THEME.up))
        self.gold_toggle.bind("<Leave>", lambda e: self._update_gold_toggle())

        # 圆角胶囊：tkinter 原生控件做不了圆角，用 Canvas 画。
        # Entry 的 bg 与胶囊底色一致（THEME.pill），视觉上融为一体。
        self.search_bar = tk.Canvas(self.body, height=SEARCH_PILL_H,
                                    highlightthickness=0, bd=0, bg=THEME.bg)
        self.search_bar.pack(fill="x", pady=(2, 0))
        self.search_bar.bind("<Configure>", lambda e: self._draw_pill())

        self.search_entry = tk.Entry(self.search_bar, bg=THEME.pill, fg=THEME.fg,
                                     insertbackground=THEME.fg,
                                     selectbackground=THEME.pill,
                                     selectforeground=THEME.fg,
                                     relief="flat", bd=0, font=F_SEARCH,
                                     highlightthickness=0,
                                     takefocus=0)  # 禁止 Tab/click 自动抢焦：只在搜索框内点击时主动 focus
        # 放大镜图标：Label widget 嵌进去，bg 与胶囊同色融入，fg 用 fg2 兜底可见。
        self._search_icon_lbl = tk.Label(self.search_bar, text="🔍",
                                         bg=THEME.pill, fg=THEME.fg2,
                                         font=("Segoe UI Emoji", 9))
        # placeholder Label：作为 Canvas 的子控件（place 定位，不用 create_window）。
        # 原因：Canvas 内 create_text 总被 create_window(Entry) 覆盖（widget 层在 item 层之上），
        # 所以改为 Canvas 子 Label，渲染层级在嵌入 window 之上方。
        self._search_ph_lbl = tk.Label(self.search_bar, text="搜索股票名称/代码",
                                        bg=THEME.pill, fg=THEME.fg3,
                                        font=F_SEARCH, cursor="xterm")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_change())
        self.search_entry.config(textvariable=self._search_var)
        self.search_entry.bind("<Escape>", lambda e: self._clear_search())
        self.search_entry.bind("<Return>", lambda e: self._on_search_enter())
        self.search_entry.bind("<FocusIn>", lambda e: self._on_search_focus(True))
        self.search_entry.bind("<FocusOut>", lambda e: self._on_search_focus(False))
        # 搜索框内任意位置点击 → 主动 focus Entry（takefocus=0 后 click 不再自动 focus）
        self._search_icon_lbl.bind("<Button-1>",
                                   lambda e: self.search_entry.focus_set(), add="+")
        self.search_bar.bind("<Button-1>",
                             lambda e: self.search_entry.focus_set(), add="+")
        # placeholder Label 点击也进入搜索
        self._search_ph_lbl.bind("<Button-1>",
                                 lambda e: self.search_entry.focus_set(), add="+")
        # 注：不再用 bind_all("<Button-1>") 全局抢焦。原因：bind_all 在 widget 级 <Button-1>
        # 之前触发，调用 root.focus_set() 会干扰子 widget（如删除按钮 🗑）的点击处理。
        # 搜索框外点击是否取消搜索，改由 Entry 自身的 <FocusOut> 控制（见 _on_search_focus）：
        # 有内容则保持下拉，空则恢复占位符——与“搜索中下拉必须保持”的需求一致。

        self._search_ph_on = False  # placeholder 当前是否显示在 Entry 内
        self._show_ph()

        # 股票 / 搜索结果 二选一展示区
        self.stocks_area = tk.Frame(self.body, bg=THEME.bg)
        self.stocks_area.pack(fill="x", pady=(6, 0))

        # 列标题行（股票名称/实时价格/涨幅/成交额）：独立 Frame 固定在滚动画布
        # 上方——滚轮滚动股票行时标题保持不动（只滚股票部分）。
        # 宽度对齐：header 与 stocks_box 各自配置相同的 columnconfigure
        # uniform 分配，两个容器同宽 → 列宽严格一致。
        self.stocks_header = tk.Frame(self.stocks_area, bg=THEME.bg)
        self._build_stocks_header()
        # 股票区展开/收起按钮：与金价区同款双箭头，place 在表头最右侧
        # （成交额列右方的空白带），右缘与上方金价区按钮严格垂直对齐。
        self.stock_toggle = self._make_area_toggle(
            self.stocks_header, self._toggle_stocks, self._update_stock_toggle)

        # 股票区滚动画布：≤3 只时高度=实测内容高度（窗口随之向下扩展，不预留空白）；
        # >3 只时锁定 3 行高度，其余股票通过滚轮滚动查看（窗口高度不再增长）。
        # 初始 height=0：空态下不给下方留任何空白。
        self.stocks_canvas = tk.Canvas(self.stocks_area, bg=THEME.bg, height=0,
                                       highlightthickness=0, bd=0)
        self.stocks_canvas.pack(fill="x")
        self.stocks_box = tk.Frame(self.stocks_canvas, bg=THEME.bg)
        self._stocks_win = self.stocks_canvas.create_window(
            0, 0, window=self.stocks_box, anchor="nw")
        # stocks_box 宽度跟随画布宽度（列宽 uniform 分配依赖外宽）
        self.stocks_canvas.bind(
            "<Configure>",
            lambda e: self.stocks_canvas.itemconfig(self._stocks_win, width=e.width))
        # 股票行重建/内容变化 → 重新实测可视高度并联动窗口尺寸
        self.stocks_box.bind("<Configure>", lambda e: self._layout_stocks())
        self._stocks_view_h = None   # 股票区可视高度（列标题 + 可见行，实测）
        self._stocks_layout_n = None # 上次布局时的股票数（用于保留滚动位置）
        self._stocks_scroll_on = False
        self._in_layout = False

        # 搜索结果容器（默认隐藏）
        self.search_box = tk.Frame(self.stocks_area, bg=THEME.bg)
        self.search_list = tk.Frame(self.search_box, bg=THEME.bg)
        self.search_list.pack(fill="x")
        self._search_box_visible = False  # 当前是否在显示搜索结果

        # ── 板块区（"下"段）：细线分隔 + 固定表头 + 滚动画布 ──
        # 与股票区完全同构：表头固定不滚动，>2 个板块滚轮滚动。
        self.sect_divider = tk.Frame(self.body, bg=THEME.line, height=1)
        self.sect_area = tk.Frame(self.body, bg=THEME.bg)
        self.sect_header = tk.Frame(self.sect_area, bg=THEME.bg)
        self._build_sect_header()
        # 板块区展开/收起按钮：同款双箭头，place 在表头最右侧（概念强度列
        # 右方的空白带），右缘与上方两个按钮严格垂直对齐。
        self.sect_toggle = self._make_area_toggle(
            self.sect_header, self._toggle_sectors, self._update_sect_toggle)
        self.sect_canvas = tk.Canvas(self.sect_area, bg=THEME.bg, height=0,
                                     highlightthickness=0, bd=0)
        self.sect_canvas.pack(fill="x")
        self.sect_box = tk.Frame(self.sect_canvas, bg=THEME.bg)
        self._sect_win = self.sect_canvas.create_window(
            0, 0, window=self.sect_box, anchor="nw")
        self.sect_canvas.bind(
            "<Configure>",
            lambda e: self.sect_canvas.itemconfig(self._sect_win, width=e.width))
        self.sect_box.bind("<Configure>", lambda e: self._layout_sectors())
        self._sect_view_h = None    # 板块区可视高度（表头 + 可见行，实测）
        self._sect_layout_n = None
        self._sect_scroll_on = False

    def _make_area_toggle(self, parent, on_click, on_leave_update):
        """区块展开/收起按钮（股票区/板块区共用，与金价区箭头同款字形）。
        place 在表头行最右侧空白带（列宽总和 < 窗口宽，右缘与金价区按钮对齐）；
        place 不参与几何传播，不影响表头实测高度。"""
        lbl = tk.Label(parent, text="︽", fg=THEME.fg3, bg=THEME.bg,
                       font=("Microsoft YaHei UI", 8), cursor="hand2",
                       anchor="e", padx=0, pady=0)
        lbl.place(relx=1.0, rely=0.5, anchor="e")
        lbl.bind("<Button-1>", lambda e: on_click())
        lbl.bind("<Enter>", lambda e: lbl.config(fg=THEME.up))
        lbl.bind("<Leave>", lambda e: on_leave_update())
        return lbl

    def _area_glyph(self, collapsed):
        """内容在按钮**下方**的区块（股票/板块区）箭头方向：
        展开中显示 ︾（点击收起，内容向下收拢）；收起中显示 ︽（点击展开）。
        金价区内容在按钮上方，方向相反（展开中 ︽），同一套"箭头指向内容
        收拢方向"的逻辑。"""
        return "︽" if collapsed else "︾"

    def _update_stock_toggle(self):
        self.stock_toggle.config(
            text=self._area_glyph(self.conf.get("stocks_collapsed")), fg=THEME.fg3)

    def _update_sect_toggle(self):
        self.sect_toggle.config(
            text=self._area_glyph(self.conf.get("sectors_collapsed")), fg=THEME.fg3)

    def _build_sect_header(self):
        """板块区列标题（板块名称/资金流入(亿)/涨幅/换手率/概念强度）。
        结构与股票区表头一致：col 0 用 Label 贴左，col 1-4 用 Canvas 画文字
        锚定 x=3，与下方数值 Label 左对齐一致。初始不 pack。"""
        hdr = self.sect_header
        for i, m in enumerate(SECT_COL_WIDTHS):
            hdr.columnconfigure(i, weight=0, minsize=m)
        hdr.columnconfigure(5, weight=0, minsize=18)
        hdr_font = ("Microsoft YaHei UI", 8)
        self._sect_hdr_canvases = []  # [(canvas, text)]，主题切换时重画
        lbl = tk.Label(hdr, text="板块名称", fg=THEME.fg3, bg=THEME.bg,
                       font=hdr_font, anchor="w")
        lbl.grid(row=0, column=0, sticky="nswe", padx=0, pady=(2, 0))
        for col, text in [(1, "资金流入(亿)"), (2, "涨幅"), (3, "换手率"), (4, "概念强度")]:
            c = tk.Canvas(hdr, bg=THEME.bg, width=10, height=14,
                          highlightthickness=0, bd=0)
            c.grid(row=0, column=col, sticky="nswe", padx=0, pady=(2, 0))
            c.bind("<Configure>", lambda e, cv=c, t=text: self._draw_sect_hdr(cv, t))
            self._sect_hdr_canvases.append((c, text))

    def _draw_sect_hdr(self, c, text):
        """板块表头 Canvas 文字：x=3 贴左（与下方数值 Label 左对齐一致）。"""
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.create_text(3, h / 2, text=text, font=("Microsoft YaHei UI", 8),
                      fill=THEME.fg3, anchor="w")

    def _build_stocks_header(self):
        """列标题行只构建一次（内容是静态文字，无需随数据刷新）。
        widget refs（_hdr_widgets / _hdr_col2 / _hdr_col3 / _hdr_col4）供高度实测与主题刷新用。
        初始不 pack：_render_stocks 按是否有自选股决定显隐。"""
        hdr = self.stocks_header
        # 5 个数据列固定像素宽（col 0-4，见 STOCK_COL_WIDTHS），col 5 固定 18px 放 🗑
        for i, m in enumerate(STOCK_COL_WIDTHS):
            hdr.columnconfigure(i, weight=0, minsize=m)
        hdr.columnconfigure(5, weight=0, minsize=18)
        hdr_font = ("Microsoft YaHei UI", 8)
        widgets = []
        # col 0, 1 用 Label 贴左；col 2, 3, 4 用 Canvas 精准控制文字 x（避开 Label
        # 因 anchor="w" 但实际渲染 cell 内 IPADX 受字体影响不一致的坑——8pt
        # 小字 cell 内偏移 4px，而 11pt bold 大字 cell 内偏移 16px，标题与
        # 数据值文字不对齐。"涨幅"/"换手率" 用 Canvas 画文字锚定在 cell 内 x=3，
        # 与下方数值 cell 内左对齐完全一致；"成交额" 贴右 x=w-4）。
        for col, text in [(0, "股票名称"), (1, "实时价格")]:
            lbl = tk.Label(hdr, text=text, fg=THEME.fg3, bg=THEME.bg,
                           font=hdr_font, anchor="w")
            lbl.grid(row=0, column=col, sticky="nswe", padx=0, pady=(2, 0))
            widgets.append(lbl)
        # col 2: Canvas 画"涨幅"（贴左 x=3，与下方 pct_l cell 内偏移对齐）
        self._hdr_col2 = tk.Canvas(hdr, bg=THEME.bg, width=10, height=14,
                                   highlightthickness=0, bd=0)
        self._hdr_col2.grid(row=0, column=2, sticky="nswe", padx=0, pady=(2, 0))
        self._hdr_col2.bind("<Configure>", self._draw_hdr_col2)
        widgets.append(self._hdr_col2)
        # col 3: Canvas 画"换手率"（贴左 x=3，与下方 tr_l cell 内偏移对齐）
        self._hdr_col3 = tk.Canvas(hdr, bg=THEME.bg, width=10, height=14,
                                   highlightthickness=0, bd=0)
        self._hdr_col3.grid(row=0, column=3, sticky="nswe", padx=0, pady=(2, 0))
        self._hdr_col3.bind("<Configure>", self._draw_hdr_col3)
        widgets.append(self._hdr_col3)
        # col 4: Canvas 画"成交额"（贴右 x=w-4）
        self._hdr_col4 = tk.Canvas(hdr, bg=THEME.bg, width=10, height=14,
                                   highlightthickness=0, bd=0)
        self._hdr_col4.grid(row=0, column=4, sticky="nswe", padx=0, pady=(2, 0))
        self._hdr_col4.bind("<Configure>", self._draw_hdr_col4)
        widgets.append(self._hdr_col4)
        self._hdr_widgets = widgets

    def _show_stocks_header(self, show):
        """表头显隐：有自选股且非搜索态时显示，位置固定在画布上方。
        收起态下画布处于 unpack 状态，before= 引用会失效 → 降级为直接 pack
        （表头在前，画布展开时 pack 追加在其后，顺序仍正确）。"""
        try:
            if show:
                if not self.stocks_header.winfo_ismapped():
                    try:
                        self.stocks_header.pack(fill="x", before=self.stocks_canvas)
                    except Exception:
                        self.stocks_header.pack(fill="x")
            else:
                self.stocks_header.pack_forget()
        except Exception:
            pass

    def _draw_hdr_col4(self, _evt=None):
        """col 4 列标题"成交额"用 Canvas 画，文字 x = 3 精准贴左（与其余 4 列
        标题对齐方式统一）。Canvas bind <Configure> 自动触发，不依赖外部 grid 几何。"""
        c = self._hdr_col4
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.create_text(3, h / 2, text="成交额", font=("Microsoft YaHei UI", 8),
                      fill=THEME.fg3, anchor="w")

    def _draw_hdr_col3(self, _evt=None):
        """col 3 列标题"换手率"用 Canvas 画，文字 x = 3 精准贴左（与下方 tr_l
        cell 内左对齐保持一致）。Canvas bind <Configure> 自动触发。"""
        c = getattr(self, "_hdr_col3", None)
        if not c:
            return
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.create_text(3, h / 2, text="换手率", font=("Microsoft YaHei UI", 8),
                      fill=THEME.fg3, anchor="w")

    def _draw_hdr_col2(self, _evt=None):
        """col 2 列标题"涨幅"用 Canvas 画，文字 x = 3 精准贴左（与下方 pct_l
        cell 内左对齐保持一致）。Canvas bind <Configure> 自动触发。"""
        c = getattr(self, "_hdr_col2", None)
        if not c:
            return
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.create_text(3, h / 2, text="涨幅", font=("Microsoft YaHei UI", 8),
                      fill=THEME.fg3, anchor="w")

    # ── 搜索胶囊绘制 ──
    def _draw_pill(self):
        """在 Canvas 上画圆角胶囊 + 🔍 图标 + 内嵌 Entry。
        placeholder "搜索股票名称/代码" 用 Canvas 子 Label（place 定位），
        渲染层级在 Canvas 内嵌 Entry 之上，不会被遮住。
        窗口尺寸变化 / 换主题时重画。"""
        c = self.search_bar
        c.delete("all")
        w = c.winfo_width()
        h = SEARCH_PILL_H
        if w < 40:
            # 尚未布局完成，等下次 <Configure> 再画
            return
        r = h / 2
        # 圆角矩形：多点 polygon + smooth
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h,
               0, h, 0, h - r, 0, r, 0, 0]
        c.create_polygon(pts, smooth=True, fill=THEME.pill, outline="", tags=("pill",))
        # 放大镜图标：Label widget 嵌进去，emoji 字体也能正确上色
        c.create_window(18, h / 2, window=self._search_icon_lbl,
                        anchor="center", tags=("pill",))
        # Entry 居中嵌入胶囊（anchor="center"）：光标起点在 Canvas 正中 (x=w/2)
        # 宽度 w-60 保证 Entry 不超出胶囊右边界，留出足够输入空间
        c.create_window(w / 2, h / 2, window=self.search_entry,
                        anchor="center", width=w - 60, height=h - 4, tags=("pill",))
        # placeholder Label：作为 Canvas 子 widget，渲染层级在 create_window 之上
        if self._search_ph_on:
            # 居中（relx=0.5）显示，与左侧 🔍（x=18）和右侧 Entry 都错开
            self._search_ph_lbl.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self._search_ph_lbl.place_forget()

    # ── 位置与尺寸 ──
    def _place(self):
        # 窗口尚未映射时，winfo_screen* 可能返回 0。用 ctypes 直接读系统度量。
        try:
            user32 = windll.user32
            sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        mini = bool(self.conf["mini"])
        if mini:
            w, h = SIZE_MINI
        else:
            w = SIZE_STD_BASE[0]
            h = self._std_height()
        cx, cy = self.conf.get("x"), self.conf.get("y")
        if cx is None or cy is None:
            cx, cy = sw - w - 18, sh - h - 62
        cx = max(0, min(int(cx), sw - w))
        cy = max(0, min(int(cy), sh - h))
        self._pos = (cx, cy)
        self.root.geometry(f"{w}x{h}+{cx}+{cy}")

    # ── 标准模式窗口高度（实测驱动） ──
    def _gold_block_h(self):
        """金价区（名称行 + 价格行 + 行距）实际占用高度，收起时从窗口高度中扣减。"""
        try:
            return self.m_name.winfo_reqheight() + self.price_row.winfo_reqheight() + 1
        except Exception:
            return 60  # 兜底估算值

    def _gold_toggle_h(self):
        """分隔线下方收起/展开箭头按钮的固定占用高度。"""
        try:
            return self.gold_toggle.winfo_reqheight()
        except Exception:
            return 14

    def _sect_block_h(self):
        """板块区总占用高度：分隔线 + 表头 + 画布（实测），未就绪时估算。
        sectors 为空时板块区整体隐藏，返回 0；收起时只保留表头行（收起按钮在表头上）。"""
        if not (self.conf.get("sectors") or []):
            return 0
        if self.conf.get("sectors_collapsed"):
            return 9 + self._stocks_header_h_of(
                getattr(self, "_sect_hdr_canvases", []))
        if self._sect_view_h:
            view = self._sect_view_h
        else:
            n = len(self.conf["sectors"])
            view = SECTORS_HEADER_H + 2 + min(n, SECTORS_VISIBLE) * STOCK_ROW_H
        return 9 + view  # 分隔线 pady(8,0) + 1px 线 + sect_area pady(0,4)

    def _std_height(self):
        """标准模式窗口高度。搜索展开时按结果行数估算；股票态：
        空态 164（实测基准，含搜索条下沿到窗底的全部留白），
        有股票时 = 164 + 股票区实测可视高度（≤3 只实高；>3 只锁定 3 行 + 滚动）。
        板块区（"下"段）配置了 sectors 时追加其总高度。
        金价区收起时（gold_collapsed）扣减金价块高度。
        base 内不含分隔线下方箭头按钮，统一在末尾加上。"""
        base = 100 + SEARCH_PILL_H + 4
        if self._search_box_visible:
            search_n = max(1, len(self._search_results))
            h = max(SIZE_STD_BASE[1], base + 6 + search_n * SEARCH_ROW_H + 4)
        else:
            n = len(self.conf.get("watchlist") or [])
            if n == 0:
                # 空态：浮窗截止到搜索框下沿，不预留下方空白（实测 163px + 1 余量）
                h = 164 + self._sect_block_h()
            elif self.conf.get("stocks_collapsed"):
                # 股票区收起：只保留表头行（收起按钮在表头上），高度=基准+表头
                h = 164 + self._stocks_header_h() + self._sect_block_h()
            else:
                view_h = self._stocks_view_h
                if not view_h:
                    # 首次渲染完成前的兜底估算，_layout_stocks 实测后会立即修正
                    view_h = STOCKS_HEADER_H + min(n, STOCKS_VISIBLE) * STOCK_ROW_H
                h = 164 + view_h + self._sect_block_h()
        if self.conf.get("gold_collapsed"):
            h -= self._gold_block_h()
        return max(SIZE_MINI[1], h) + self._gold_toggle_h()

    def _apply_size(self):
        mini = bool(self.conf["mini"])
        if mini:
            w, h = SIZE_MINI
        else:
            w = SIZE_STD_BASE[0]
            h = self._std_height()
        # 注意：窗口未映射时 winfo_x() 会返回 0，必须用缓存坐标，否则窗口会跳到 (0,0)
        cx, cy = getattr(self, "_pos", (self.root.winfo_x(), self.root.winfo_y()))
        self.root.geometry(f"{w}x{h}+{cx}+{cy}")
        if mini:
            # 迷你模式：搜索条、股票区、分隔线都隐藏
            try: self.search_bar.pack_forget()
            except Exception: pass
            try: self.divider.pack_forget()
            except Exception: pass
            try: self.gold_toggle.pack_forget()
            except Exception: pass
            try: self.stocks_area.pack_forget()
            except Exception: pass
            try: self.sect_divider.pack_forget()
            except Exception: pass
            try: self.sect_area.pack_forget()
            except Exception: pass
        else:
            try: self.divider.pack(fill="x", pady=(6, 4))
            except Exception: pass
            try: self.gold_toggle.pack(fill="x", before=self.search_bar)
            except Exception: pass
            try: self.search_bar.pack(fill="x", pady=(2, 0))
            except Exception: pass
            try: self.stocks_area.pack(fill="x", pady=(6, 0))
            except Exception: pass
            # 板块区（"下"段）：细分隔线 + 板块列表（sectors 为空时整区不出现）
            if self.conf.get("sectors"):
                try: self.sect_divider.pack(fill="x", pady=(8, 0))
                except Exception: pass
                try: self.sect_area.pack(fill="x", pady=(0, 4))
                except Exception: pass
            # 金价区按收起状态归位（before=divider 保证 pack 顺序恢复原布局）
            self._apply_gold_visibility()
            # 股票/板块区按各自收起状态归位（表头保留，内容画布显隐）
            self._apply_stocks_visibility()
            self._apply_sects_visibility()
            # 布局就绪后重画胶囊（<Configure> 兜底，这里主动一次）
            self._draw_pill()
        self.dot.config(fg=THEME.blue)

    # ── 金价区收起 / 展开（分隔线下方箭头按钮触发）──
    def _update_gold_toggle(self):
        """箭头状态：展开中显示 ︽（点击收起）；收起中显示 ︾（点击展开）。"""
        self.gold_toggle.config(text="︾" if self.conf.get("gold_collapsed") else "︽",
                                fg=THEME.fg3)

    def _apply_gold_visibility(self):
        """按 gold_collapsed 状态显示/隐藏金价区（名称行 + 价格行）。
        重新展开时用 before=self.divider 插回原位置，避免 pack 顺序错乱。"""
        if self.conf.get("gold_collapsed"):
            try: self.m_name.pack_forget()
            except Exception: pass
            try: self.price_row.pack_forget()
            except Exception: pass
        else:
            try: self.m_name.pack(anchor="w", before=self.divider)
            except Exception: pass
            try: self.price_row.pack(fill="x", pady=(1, 0), before=self.divider)
            except Exception: pass
        self._update_gold_toggle()

    def _toggle_gold(self):
        if self.conf.get("mini"):
            return  # 迷你模式本就无金价区，分隔线也不可见
        self.conf["gold_collapsed"] = not self.conf.get("gold_collapsed", False)
        save_conf(self.conf)
        print(f"[gold] collapsed = {self.conf['gold_collapsed']}", flush=True)
        self._apply_gold_visibility()
        self._apply_size()
        self._place_keep_corner()

    # ── 股票区 / 板块区收起 / 展开（表头右侧箭头按钮触发，同金价区机制）──
    def _apply_stocks_visibility(self):
        """按 stocks_collapsed 状态显隐股票区内容画布。
        表头始终保留（有自选股时）——收起按钮就在表头上，藏了就展开不了。
        搜索展开时由 _show/_hide_search_results 全权管理，此处不插手。"""
        if self._search_box_visible:
            return
        if self.conf.get("stocks_collapsed"):
            try: self.stocks_canvas.pack_forget()
            except Exception: pass
        else:
            try:
                if not self.stocks_canvas.winfo_ismapped():
                    self.stocks_canvas.pack(fill="x")
            except Exception: pass
        self._show_stocks_header(bool(self.conf.get("watchlist")))
        self._update_stock_toggle()

    def _apply_sects_visibility(self):
        """按 sectors_collapsed 状态显隐板块区内容画布。表头保留（同理）。"""
        if self._search_box_visible:
            return
        if self.conf.get("sectors_collapsed"):
            try: self.sect_canvas.pack_forget()
            except Exception: pass
        else:
            try:
                if not self.sect_canvas.winfo_ismapped():
                    self.sect_canvas.pack(fill="x")
            except Exception: pass
        self._update_sect_toggle()

    def _toggle_stocks(self):
        if self.conf.get("mini"):
            return
        if not (self.conf.get("watchlist") or []):
            return  # 无自选股时表头整体隐藏，按钮不可见，无从触发
        self.conf["stocks_collapsed"] = not self.conf.get("stocks_collapsed", False)
        save_conf(self.conf)
        self._apply_stocks_visibility()
        self._apply_size()
        self._place_keep_corner()

    def _toggle_sectors(self):
        if self.conf.get("mini"):
            return
        if not (self.conf.get("sectors") or []):
            return
        self.conf["sectors_collapsed"] = not self.conf.get("sectors_collapsed", False)
        save_conf(self.conf)
        self._apply_sects_visibility()
        self._apply_size()
        self._place_keep_corner()

    def toggle_mini(self):
        self.conf["mini"] = not self.conf["mini"]
        self._apply_size()
        self._place_keep_corner()
        save_conf(self.conf)
        self._render()

    def _place_keep_corner(self):
        """切换尺寸后保持右上角不动，避免窗口跳位。"""
        self.root.update_idletasks()
        mini = bool(self.conf["mini"])
        if mini:
            w, h = SIZE_MINI
        else:
            w = SIZE_STD_BASE[0]
            h = self._std_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, min(self.root.winfo_x(), sw - w))
        y = max(0, min(self.root.winfo_y(), sh - h))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── 主题切换 ──
    def _apply_theme(self, mode, persist=True):
        """切换到指定主题：更新全局 THEME 持有器，并遍历所有 widget 重设颜色。
        Tk widget 创建时颜色已固化，必须显式 config 才会更新。"""
        if mode not in THEMES:
            mode = "light"
        THEME.set(mode)
        # 快照旧主题全部角色色（供末尾兜底清扫做「旧色 → 新色」映射）
        old_colors = {k: str(v).lower() for k, v in THEMES[
            "dark" if mode == "light" else "light"].items()}
        # 切换按钮图标：light 时显示月亮（点击切到 dark），dark 时显示太阳
        try:
            self.btn_theme.config(text="☼" if mode == "light" else "☾")
        except Exception:
            pass
        # 重新设置 outer (border) / inner / title / body
        try:
            self.root.configure(bg=THEME.border)
        except Exception:
            pass
        for w in (self.outer, self.inner, self.title_bar, self.body):
            try: w.config(bg=THEME.bg)
            except Exception: pass
        # 颜色角色映射：当前颜色 → 新主题对应颜色
        # 旧值可能在 light 也可能在 dark（重切），所以用 THEME 的当前值匹配
        old_to_new = {
            THEME.bg:    THEME.bg,      # 占位（widget 自己保留旧 BG，会被后面刷掉）
            THEME.fg:    THEME.fg,
            THEME.fg2:   THEME.fg2,
            THEME.fg3:   THEME.fg3,
            THEME.line:  THEME.line,
            THEME.up:    THEME.up,
            THEME.down:  THEME.down,
            THEME.blue:  THEME.blue,
        }
        # 重建映射：以「上一个值」为 key。模式切换前我们需要先记录每 widget 的"角色"再刷。
        # 但更简单：直接按 widget 类型 + 已知角色列表全量刷一次
        # ── 兜底清扫必须先于显式刷色执行 ──
        # 否则显式刷色已把 widget 设成新主题色后，清扫会把其中恰好与"旧主题
        # 某角色色"同值的新色二次映射（实测：dark fg #F2F4F7 == light hover
        # #F2F4F7，搜索框白字被二次映射成 hover 深灰，深底下几乎不可见）。
        # 先清扫：所有 widget 仍持旧主题色，旧色 → 新色映射无歧义；
        # 后显式刷色：按角色再刷一遍，幂等且覆盖清扫语义。
        self._sweep_theme_colors(old_colors)
        self._restyle_widgets(mode)
        if persist:
            self.conf["theme"] = mode
            save_conf(self.conf)

    def _restyle_widgets(self, mode):
        """对所有受主题影响的 widget 重新设色。"""
        # 标题栏
        for w, role in (
            (self.dot, "blue"),
            (self.t_label, "fg2"),
            (self.t_time, "fg3"),
            (self.btn_close, "fg3"),
            (self.btn_theme, "fg3"),
        ):
            try: w.config(bg=THEME.bg, fg=THEME.get(role))
            except Exception: pass
        # 眼睛按钮颜色由状态决定（掩码中 = 蓝），_render 开头统一刷新
        try: self.btn_eye.config(bg=THEME.bg)
        except Exception: pass
        # 箭头按钮（收起/展开金价区）同样由 _render 开头统一刷新 fg/文字
        try: self.gold_toggle.config(bg=THEME.bg)
        except Exception: pass
        # 股票/板块区的同款收起/展开按钮
        for t in (getattr(self, "stock_toggle", None), getattr(self, "sect_toggle", None)):
            try: t.config(bg=THEME.bg)
            except Exception: pass
        # 主价格
        try: self.m_name.config(bg=THEME.bg, fg=THEME.fg3)
        except Exception: pass
        # 主价格行容器（局部变量会漏刷，导致切主题后残留旧色块）
        try: self.price_row.config(bg=THEME.bg)
        except Exception: pass
        try: self.m_price_box.config(bg=THEME.bg)
        except Exception: pass
        try: self.m_price.config(bg=THEME.bg, fg=THEME.fg)
        except Exception: pass
        try: self.m_chg_box.config(bg=THEME.bg)
        except Exception: pass
        try: self.m_chg.config(bg=THEME.bg, fg=THEME.fg3)
        except Exception: pass
        # 分隔线（搜索条上沿）
        try: self.divider.config(bg=THEME.line)
        except Exception: pass
        # 搜索条：Canvas 胶囊 + Entry + 放大镜 Label + placeholder Label（重画即可换主题色）
        try:
            self.search_bar.config(bg=THEME.bg)
        except Exception: pass
        try:
            self._search_icon_lbl.config(bg=THEME.pill, fg=THEME.fg2)
        except Exception: pass
        try:
            self._search_ph_lbl.config(bg=THEME.pill, fg=THEME.fg3)
        except Exception: pass
        try:
            self.search_entry.config(
                bg=THEME.pill,
                fg=THEME.fg,  # placeholder 由 Canvas 子 Label 渲染，Entry 始终是主色
                insertbackground=THEME.fg,
                selectbackground=THEME.pill,
                selectforeground=THEME.fg)
        except Exception: pass
        self._draw_pill()
        # 股票区 / 搜索层容器
        for w in (self.stocks_area, self.stocks_header, self.stocks_canvas,
                  self.stocks_box, self.search_box, self.search_list):
            try: w.config(bg=THEME.bg)
            except Exception: pass
        # 列标题行
        self._restyle_stocks_header()
        # 板块区：表头 Canvas 刷 bg + 重画；容器与分隔线刷 bg
        for cv, text in getattr(self, "_sect_hdr_canvases", []):
            try: cv.config(bg=THEME.bg)
            except Exception: pass
            try: self._draw_sect_hdr(cv, text)
            except Exception: pass
        for w in (self.sect_header, self.sect_area, self.sect_canvas, self.sect_box):
            try: w.config(bg=THEME.bg)
            except Exception: pass
        try: self.sect_divider.config(bg=THEME.line)
        except Exception: pass
        # 已有股票行
        self._restyle_stock_rows()
        # 已有搜索结果行（如果搜索展开）
        self._restyle_search_rows()
        # 重渲数据以让价格/涨跌色按新主题上色
        if self.data:
            self._render()

    def _sweep_theme_colors(self, old_colors):
        """遍历所有子控件，凡 bg/fg 等仍为旧主题任一角色色，替换为新主题对应角色色。
        Canvas 内的图形项（胶囊/文字）不在此处理，由各自的 _draw_* 按当前 THEME 重画。"""
        # 角色 → 角色 直接映射（同角色换色）；key/value 均为小写 hex
        color_map = {old_hex: str(THEME.get(role)).lower()
                     for role, old_hex in old_colors.items()}
        # 同一 hex 在新旧主题可能对应不同角色时以旧角色为准（dict 推导已保证）
        def sweep(w):
            for child in w.winfo_children():
                sweep(child)
            try:
                bg = str(w.cget("bg")).lower()
            except Exception:
                return  # 无 bg 选项的控件（如 Menu）跳过
            hits = {}
            new_bg = color_map.get(bg)
            if new_bg:
                hits["bg"] = new_bg
            for opt in ("fg", "insertbackground", "selectbackground",
                        "selectforeground", "activeforeground", "activebackground"):
                try:
                    v = str(w.cget(opt)).lower()
                except Exception:
                    continue
                nv = color_map.get(v)
                if nv:
                    hits[opt] = nv
            if hits:
                try: w.config(**hits)
                except Exception: pass
        sweep(self.root)

    def _restyle_stocks_header(self):
        """列标题行颜色跟随主题（与下方股票行 uniform="stock" 等宽对齐）。
        col 2/3/4 是 Canvas（画"涨幅"/"换手率"/"成交额"），需要单独刷 bg + 重画。"""
        hdr = getattr(self, "stocks_header", None)
        if not hdr:
            return
        try: hdr.config(bg=THEME.bg)
        except Exception: pass
        for child in hdr.winfo_children():
            try: child.config(bg=THEME.bg, fg=THEME.fg3)
            except Exception: pass
        # col 2, 3, 4 Canvas：刷 bg + 重画（文字 fill 颜色随主题）
        for attr in ("_hdr_col2", "_hdr_col3", "_hdr_col4"):
            hdr_canvas = getattr(self, attr, None)
            if hdr_canvas:
                try: hdr_canvas.config(bg=THEME.bg)
                except Exception: pass
                try: getattr(self, f"_draw_{attr.lstrip('_')}")()
                except Exception: pass

    def _restyle_stock_rows(self):
        """刷新已渲染的股票行颜色（不重建结构，只改颜色）。"""
        for entry in getattr(self, "stock_rows", []):
            if len(entry) < 11:  # 旧版 entry 长度 8（无 amt canvas 引用）
                continue
            code, frame, name_l, price_l, pct_l, amt_l, del_btn, code_l, amt_tid, amt_draw, amt_text = entry
            if code == "__empty__":
                continue
            d = self.stock_data.get(code, {})
            pct = d.get("change_pct")
            price = d.get("price")
            pct_col = THEME.up if (pct or 0) > 0 else (THEME.down if (pct or 0) < 0 else THEME.fg3)
            price_col = pct_col if price is not None else THEME.fg
            try: frame.config(bg=THEME.bg)
            except Exception: pass
            try: name_l.config(bg=THEME.bg, fg=THEME.fg)
            except Exception: pass
            try: code_l.config(bg=THEME.bg, fg=THEME.fg3)
            except Exception: pass
            try: price_l.config(bg=THEME.bg, fg=price_col)
            except Exception: pass
            try: pct_l.config(bg=THEME.bg, fg=pct_col)
            except Exception: pass
            # amt_l 现在是 Canvas：刷 bg + 重画（text 颜色随主题）
            try: amt_l.config(bg=THEME.bg)
            except Exception: pass
            try: amt_draw()  # 触发重画并刷新 fill 颜色
            except Exception: pass
            try: del_btn.config(bg=THEME.bg, fg=THEME.fg3)
            except Exception: pass

    def _restyle_search_rows(self):
        """刷新搜索结果行颜色。行内层级：row → left(嵌套) → name/code 标签，
        必须递归遍历，只刷一层会漏掉嵌套标签（切主题后文字/背景残留旧主题色）。"""
        def rec(w, depth=0):
            try:
                w.config(bg=THEME.bg)
            except Exception:
                pass
            if depth == 0:
                return  # 顶层 row 容器无文字色
            try:
                txt = str(w.cget("text"))
                has_text = True
            except Exception:
                has_text = False
            if has_text:
                # 按角色补刷文字色："+"按钮 up 色，代码/提示 fg3，其余 fg
                try:
                    if txt == "+":
                        w.config(fg=THEME.up)
                    elif "(" in txt or "（" in txt:  # 代码 (600487) / （无匹配结果）
                        w.config(fg=THEME.fg3)
                    else:
                        w.config(fg=THEME.fg)
                except Exception:
                    pass
            for sub in w.winfo_children():
                rec(sub, depth + 1)
        for row in getattr(self, "search_list", tk.Frame).winfo_children():
            rec(row)

    def _toggle_theme(self):
        cur = self.conf.get("theme", "light")
        nxt = "dark" if cur == "light" else "light"
        self._apply_theme(nxt)

    # ── 数据掩码（隐私模式）──
    def _mask(self, txt):
        """掩码开关打开时，所有行情数据统一显示为 "****"。"""
        return "****" if self._hide_data else txt

    def _update_eye_btn(self):
        """眼睛图标状态色：明文 = 常规灰；掩码中 = 主题蓝（明确提示"隐藏已激活"）。"""
        self.btn_eye.config(fg=THEME.blue if self._hide_data else THEME.fg3)

    def _toggle_hide_data(self):
        self._hide_data = not self._hide_data
        print(f"[eye] hide_data = {self._hide_data}", flush=True)
        self._update_eye_btn()
        if self.data:
            self._render()
        # 股票区 / 搜索下拉（若展开）都立即按新状态重绘
        self._render_stocks()
        self._render_search_results()

    # ── 右键菜单：自绘浮层 ──
    # 不用 tk.Menu 的原因（两个实打实的坑）：
    # 1) Windows 对 Menu 的 -fg 支持不可靠——bg 生效、文字色被系统覆盖成黑色，
    #    浅色主题恰好系统文字也是黑的看不出问题，深色主题下黑字深底几乎不可见；
    # 2) 菜单文案在构建时固化，主题切换后（rebuild 早于 conf 更新）永远显示旧文案。
    # 自绘 Toplevel + Label 行：颜色完全走 THEME，文案每次右键现场计算，hover 高亮可控。

    def _close_menu(self):
        w = getattr(self, "_menu_win", None)
        self._menu_win = None
        if w is not None:
            try: w.destroy()
            except Exception: pass
        # 菜单（topmost 浮层）的创建/销毁会触发 Windows 对 z-order 的重新排布，
        # 可能顺手把宿主浮窗从 topmost 层拽下来（表现为"浮窗被别的窗口盖住"）。
        # 关菜单时按配置把置顶态压实回去。
        try:
            t = bool(self.conf.get("topmost", True))
            if t and not bool(self.root.attributes("-topmost")):
                self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

    # ── 菜单关闭的三个全局清扫处理器（__init__ 里一次性注册，菜单开着才生效） ──
    # 设计原则：不抢焦点（focus_force 是"菜单自发关闭"的根源——真实机器上任何
    # 前台焦点变化都会触发 FocusOut 误杀菜单）、不设 grab（系统钩子有风险）。
    # 关闭只依赖明确信号：点击菜单外 / Esc / 点击菜单项。

    def _menu_sweep_click(self, ev):
        """点击落在菜单矩形之外 → 关闭菜单。bind_all 一次性注册，菜单关闭时自哑。"""
        m = getattr(self, "_menu_win", None)
        if m is None:
            return
        # 呼出菜单的那次右键本身也会流经 bind_all（bindtags: widget→class→toplevel→all），
        # 同一事件直接放行，否则菜单刚弹出就被自己关掉
        if getattr(ev, "time", 0) and ev.time <= getattr(self, "_menu_open_ev_time", 0):
            return
        try:
            if not m.winfo_exists():
                self._menu_win = None
                return
            wx, wy = m.winfo_rootx(), m.winfo_rooty()
            ww, wh = m.winfo_width(), m.winfo_height()
            if wx - 2 <= ev.x_root < wx + ww + 2 and wy - 2 <= ev.y_root < wy + wh + 2:
                return  # 点击在菜单内（行/边距），交给菜单自身处理
            self._close_menu()
        except Exception:
            pass

    def _menu_sweep_esc(self, ev):
        """Esc 关闭菜单（菜单未开时自哑）。"""
        if getattr(self, "_menu_win", None) is not None:
            self._close_menu()

    # 透明度档位（从不透明到更透明，含 68%）
    _ALPHA_LEVELS = (1.0, 0.95, 0.88, 0.78, 0.68, 0.58)

    def _set_alpha(self, v):
        """设定透明度并持久化（菜单百分比选项点击后调用）。"""
        try:
            self.root.attributes("-alpha", float(v))
            self.conf["alpha"] = float(v)
            save_conf(self.conf)
        except Exception:
            pass

    def _popup_menu(self, e, alpha_expanded=False, at=None):
        """alpha_expanded: 透明度子选项是否展开；at: 重开菜单时沿用原坐标 (x, y)。"""
        self._close_menu()
        # 呼出菜单前先压实浮窗自己的置顶态：若它已被拽下 topmost 层，
        # 菜单的同层置顶就失去了参照，仍可能被别的窗口隔在中间。
        try:
            if bool(self.conf.get("topmost", True)):
                self.root.attributes("-topmost", True)
                self.root.lift()
        except Exception:
            pass
        m = tk.Toplevel(self.root)
        self._menu_win = m
        self._menu_open_ev_time = getattr(e, "time", 0) or 0
        m.overrideredirect(True)
        # 先藏住再定位：严禁在默认位置(0,0)映射一帧再挪走——那正是
        # "屏幕左上角快速闪出菜单"的来源（首次映射必须发生在正确坐标上）。
        # 注意：不要调用 m.transient()。Windows 下 transient 会重建底层 HWND，
        # 把 geometry() 请求的位置一并丢掉，菜单会被钉死在左上角。
        m.withdraw()
        m.configure(bg=THEME.border)

        topmost = bool(self.root.attributes("-topmost"))
        try:
            cur_alpha = float(self.root.attributes("-alpha"))
        except Exception:
            cur_alpha = 1.0
        # 文案每次现场计算：永远反映当前状态（修复主题切换后菜单文案不更新的问题）
        # ("alpha",) 为特殊段：透明度行（点击展开/收起百分比子选项）
        rows = [
            ("立即刷新", self._refresh_all),
            None,
            (f"窗口置顶{'  ✓' if topmost else ''}", self._toggle_topmost),
            ("切换浅色" if self.conf.get("theme") == "dark" else "切换深色",
             self._toggle_theme),
            ("展开金价区" if self.conf.get("gold_collapsed") else "收起金价区",
             self._toggle_gold),
            ("alpha",),
            None,
            ("打开网页看板", self._open_web),
            None,
            ("退出", self.quit),
        ]
        for item in rows:
            if item is None:
                tk.Frame(m, bg=THEME.line, height=1).pack(fill="x", padx=10, pady=(3, 2))
                continue
            if item[0] == "alpha":
                # 透明度行：点击展开/收起百分比子选项（内嵌展开，不另开浮层，
                # 规避第二个 topmost 浮层的 z-order/定位坑）
                arrow = "▾" if alpha_expanded else "▸"
                a = tk.Label(m, text=f"透明度 {cur_alpha:.0%}  {arrow}",
                             fg=THEME.fg, bg=THEME.bg, font=F_SMALL,
                             anchor="w", padx=14, pady=3, cursor="hand2")
                a.pack(fill="x")
                a.bind("<Button-1>", lambda ev, ex=not alpha_expanded: (
                    self._close_menu(),
                    self._popup_menu(ev, alpha_expanded=ex, at=getattr(self, "_menu_xy", None))))
                a.bind("<Enter>", lambda ev, l=a: l.config(bg=THEME.hover))
                a.bind("<Leave>", lambda ev, l=a: l.config(bg=THEME.bg))
                if alpha_expanded:
                    for v in self._ALPHA_LEVELS:
                        pct = round(v * 100)
                        mark = "✓ " if abs(cur_alpha - v) < 0.005 else "   "
                        p = tk.Label(m, text=f"{mark}{pct}%",
                                     fg=THEME.fg2 if abs(cur_alpha - v) >= 0.005 else THEME.fg,
                                     bg=THEME.bg, font=F_SMALL,
                                     anchor="w", padx=30, pady=3, cursor="hand2")
                        p.pack(fill="x")
                        p.bind("<Button-1>", lambda ev, vv=v: (self._set_alpha(vv), self._close_menu()))
                        p.bind("<Enter>", lambda ev, l=p: l.config(bg=THEME.hover))
                        p.bind("<Leave>", lambda ev, l=p: l.config(bg=THEME.bg))
                continue
            text, cmd = item
            lbl = tk.Label(m, text=text, fg=THEME.fg, bg=THEME.bg,
                           font=F_SMALL, anchor="w", padx=14, pady=3, cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda ev, c=cmd: (self._close_menu(), c()))
            lbl.bind("<Enter>", lambda ev, l=lbl: l.config(bg=THEME.hover))
            lbl.bind("<Leave>", lambda ev, l=lbl: l.config(bg=THEME.bg))

        # 定位：光标处（重开时沿用原坐标），整体夹在屏幕内
        m.update_idletasks()
        w_, h_ = m.winfo_reqwidth(), m.winfo_reqheight()
        try:
            sw = windll.user32.GetSystemMetrics(0)
            sh = windll.user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ex, ey = at if at is not None else (e.x_root, e.y_root)
        x = max(0, min(ex, sw - w_ - 4))
        y = max(0, min(ey, sh - h_ - 4))
        self._menu_xy = (x, y)
        m.geometry(f"+{x}+{y}")
        m.attributes("-topmost", True)
        m.deiconify()  # 在正确坐标上首次映射（withdraw→deiconify 全程无 0,0 闪现）
        # Windows 对 overrideredirect 窗口首次映射时可能重置位置/重排 z-order：
        # reposition 会等到 viewable 后再压实坐标并补 lift，双次兜底。
        m.after(10, lambda: self._reposition_menu(m, x, y))
        m.after(60, lambda: self._reposition_menu(m, x, y))
        # 最终 raise：不重设坐标，只保证菜单压在浮窗之上
        m.after(250, lambda: self._raise_menu(m))
        m.lift()
        # 刻意不调用 focus_force：不抢焦点就没有 FocusOut 自发关闭的链条。
        # 关闭依赖 __init__ 里一次性注册的全局清扫（点击菜单外 / Esc）。

    def _reposition_menu(self, w, x, y, tries=0):
        """映射后二次压实菜单位置（等 viewable 后 geometry+lift）；菜单已关闭则跳过。"""
        try:
            if w is not getattr(self, "_menu_win", None):
                return
            if not w.winfo_viewable():
                # 关键：压实必须在映射之后做。Windows 对 overrideredirect 窗口
                # 首次映射时会重排 z-order，映射前压实会被冲掉（实测复现）。
                if tries < 60:  # 最多等 300ms
                    w.after(5, lambda: self._reposition_menu(w, x, y, tries + 1))
                else:
                    # 仍不可见（个别环境 withdraw→deiconify 未重映射）：强制映射
                    w.deiconify()
                    w.geometry(f"+{x}+{y}")
                    w.attributes("-topmost", True)
                    w.lift()
                return
            w.geometry(f"+{x}+{y}")
            # geometry 重配置会把窗口在 topmost 层内排到宿主之下，必须补 lift
            w.lift()
        except Exception:
            pass

    def _raise_menu(self, w):
        """把菜单压实到浮窗之上（重设 topmost + lift，用于对抗 z-order 重排）。"""
        try:
            if w is getattr(self, "_menu_win", None) and w.winfo_viewable():
                w.attributes("-topmost", True)
                w.lift()
        except Exception:
            pass

    def _ensure_menu_on_top(self):
        """菜单守护：菜单开着时确保它压在浮窗之上，被盖住立即抬起。
        真实机器实测链路：菜单 topmost 会把浮窗拽下 topmost 层 → _poll 置顶自愈
        把浮窗压实回 topmost 并 lift → 浮窗反超到菜单之上，菜单"很快被藏到浮窗背后"。
        该守护在每个 _poll 心跳里对账，无论哪一环把菜单压下去都立刻纠正。"""
        m = getattr(self, "_menu_win", None)
        if m is None:
            return
        try:
            if not m.winfo_exists():
                self._menu_win = None
                return
            if not m.winfo_viewable():
                return  # 未映射/已隐藏：交给 _reposition_menu 的压实链处理
            if (not bool(m.attributes("-topmost"))
                    or not int(self.root.tk.call("wm", "stackorder", m, "isabove", self.root))):
                self._raise_menu(m)
        except Exception:
            pass

    def _toggle_topmost(self):
        # 直接读窗口真实置顶态取反（原 tk.Menu checkbutton 的 variable 自动翻转，
        # 自绘菜单下没有这个机制，读 var 会永远得到同一个值）
        v = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", v)
        self.conf["topmost"] = v
        save_conf(self.conf)

    def _open_web(self):
        import webbrowser
        try:
            webbrowser.open("http://127.0.0.1:8848")
        except Exception:
            pass

    # ── 拖动 ──
    def _start_move(self, e):
        self.dragging = True
        self._dx, self._dy = e.x, e.y

    def _do_move(self, e):
        if not self.dragging:
            return
        x = self.root.winfo_pointerx() - self._dx
        y = self.root.winfo_pointery() - self._dy
        self.root.geometry(f"+{x}+{y}")

    def _stop_move(self, e):
        if self.dragging:
            self.dragging = False
            self.conf["x"], self.conf["y"] = self.root.winfo_x(), self.root.winfo_y()
            save_conf(self.conf)

    def fetch(self):
        # 防重叠：上次拉取线程还在跑就跳过，避免并发子进程堆积
        if getattr(self, "_fetching", False):
            return
        self._fetching = True
        self.dot.config(fg=THEME.fg3)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        """金价轨：只拉京东金价，不再附带股票（股票已拆到 _stock_worker 独立快轨）。"""
        try:
            # 浮窗只看行情，不拉资讯/走势，缩短刷新耗时
            d = gold_data.collect(with_news=False, with_trend=False)
            self.q.put(("ok", d))
            self._fail_streak = 0
        except gold_data.QuotaError as e:
            # 配额用尽 ≠ 网络故障：识别后走专用长退避，避免烧掉次日的恢复配额
            self.q.put(("quota", str(e)))
        except Exception as e:
            self.q.put(("err", str(e)))
        finally:
            self._fetching = False

    # ── 股票快轨（与金价解耦）──
    def _refresh_all(self):
        """右键「立即刷新」：金价 + 股票双轨同时发车。"""
        self.fetch()
        self._stock_last = 0.0
        self.fetch_stock()

    def fetch_stock(self):
        """立即拉一次股票行情（独立线程 + 独立防重叠锁，不阻塞金价轨）。"""
        if getattr(self, "_stock_fetching", False):
            return
        self._stock_fetching = True
        threading.Thread(target=self._stock_worker, daemon=True).start()

    def _stock_worker(self):
        try:
            codes = self.conf.get("watchlist") or []
            stock_data = gold_data.quote_stocks(codes) if codes else {}
            sect_codes = self.conf.get("sectors") or []
            sect_new = gold_data.quote_sectors(sect_codes) if sect_codes else {}
            prev = getattr(self, "sect_data", {}) or {}
            if sect_new is None:
                # 整次请求失败（网络抖动，重试后仍不通）：沿用上一轮数据，
                # 不让板块区闪成"裸代码 + ---"，等下一轮自动恢复。
                sect_out = prev
            else:
                # 请求成功但个别代码偶发缺失：名称沿用旧值（避免退化成裸代码），
                # 数值字段如实显示 "---"。
                for c in sect_codes:
                    if (c not in sect_new and c in prev
                            and isinstance(prev.get(c), dict) and prev[c].get("name")):
                        sect_new[c] = {"name": prev[c]["name"]}
                sect_out = sect_new
            self.q.put(("stocks", stock_data, sect_out))
            self._stock_fail_streak = 0
        except Exception as e:
            self.q.put(("stocks_err", str(e)))
        finally:
            self._stock_fetching = False

    def _gold_window_active(self, now=None):
        """金价自动轮询是否处于刷新时段窗口内（工作日 9:30~18:00，本地时间）。"""
        now = now or datetime.now()
        if now.weekday() not in GOLD_WIN_DAYS:
            return False
        m = now.hour * 60 + now.minute
        s = GOLD_WIN_START[0] * 60 + GOLD_WIN_START[1]
        e = GOLD_WIN_END[0] * 60 + GOLD_WIN_END[1]
        return s <= m < e

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "ok":
                    _, payload = item
                    self.data = payload
                    self._quota_mode = False
                    self._render()
                elif kind == "stocks":
                    # 股票/板块快轨数据：只重绘对应区（搜索展开时 _render_stocks 内部直接跳过）
                    self.stock_data = item[1] or {}
                    self.sect_data = item[2] if len(item) > 2 else getattr(self, "sect_data", {})
                    self._render_stocks()
                    self._render_sectors()
                elif kind == "stocks_err":
                    self._stock_fail_streak = min(
                        getattr(self, "_stock_fail_streak", 0) + 1, 8)
                    if self._stock_fail_streak == 1:  # 只在"由好变坏"时记一次，避免刷日志
                        glog.warn(f"股票/板块取数失败: {item[1]}")
                elif kind == "hotkey":
                    self._toggle_visible()
                elif kind == "search":
                    _, kw, results = item
                    self._on_search_results(kw, results)
                elif kind == "search_err":
                    glog.warn(f"搜索失败: {item[1]}")
                    self._on_search_err(item[1])
                else:  # "err"
                    self._fail_streak += 1
                    if self._fail_streak == 1:  # 状态翻转才记录，避免每次重试都刷一行
                        glog.warn(f"金价取数失败: {item[1]}")
                    self.dot.config(fg=THEME.up)
                if kind == "quota":
                    # 配额用尽：红点提示 + 时间位显示恢复提示；长退避由下方间隔计算处理
                    self._fail_streak = max(getattr(self, "_fail_streak", 0), 3)
                    self._quota_mode = True
                    self.dot.config(fg=THEME.up)
                    try:
                        self.t_time.config(text="额度恢复中", fg=THEME.fg3)
                    except Exception as e:
                        # 这里是"配额已用尽"的唯一用户可见提示；静默失败会让用户
                        # 只看到金价不动却不知道原因。debug 级别（默认不落盘，零开销）。
                        glog.debug(f"配额恢复提示刷新失败: {e}")
        except queue.Empty:
            pass
        # 搜索状态自愈：任何未知路径把下拉藏了/Entry 与下拉状态不同步，1s 内恢复
        try: self._sync_search_state()
        except Exception: pass
        # 置顶自愈：topmost 浮层（右键菜单等）的创建/销毁会触发 Windows 重排
        # z-order，可能把浮窗从 topmost 层拽下去。每秒对账一次，配置要求置顶
        # 而实际没置顶时压实回去，保证"永远浮在其他应用之上"不被意外打破。
        try:
            want = bool(self.conf.get("topmost", True))
            if want and not bool(self.root.attributes("-topmost")):
                self.root.attributes("-topmost", True)
                self.root.lift()
        except Exception:
            pass
        # 菜单守护：自愈抬起浮窗后，菜单可能被反超盖住——同一心跳内立刻纠正
        try: self._ensure_menu_on_top()
        except Exception: pass
        self.root.after(1000, self._poll)
        if not hasattr(self, "_last"):
            self._last = 0
        # 失败退避：连续失败后实际间隔翻倍（上限 300s），成功即复位。
        # 配额用尽时额外托底 ≥300s：接口当天必然失败，慢点重试等 0 点重置即可，
        # 高频重试只会把恢复后的新配额也烧光。
        eff = self.interval * (2 ** min(getattr(self, "_fail_streak", 0), 4))
        if getattr(self, "_quota_mode", False):
            eff = max(eff, 300)
        if time.time() - self._last > eff:
            if self._gold_window_active():
                self._last = time.time()
                self.fetch()
            else:
                # 刷新时段窗口外：自动轮询静默（0 配额消耗），已有数据保持展示。
                # 不动 _last → 窗口开启瞬间差值巨大，立即补发一次。
                self.dot.config(fg=THEME.fg3)
                if not self.data:
                    try:
                        self.t_time.config(text="非刷新时段", fg=THEME.fg3)
                    except Exception as e:
                        glog.debug(f"非刷新时段提示刷新失败: {e}")
        # 股票快轨：独立计时，不受金价 3s 下限与金价失败退避影响。
        # 无关注股票时完全不发车（省请求）；新增/删除股票会主动触发一次即时拉取。
        if self.conf.get("watchlist"):
            stock_eff = self.stock_interval * (2 ** min(
                getattr(self, "_stock_fail_streak", 0), 3))
            if time.time() - self._stock_last > stock_eff:
                self._stock_last = time.time()
                self.fetch_stock()

    # ── 渲染 ──
    def _render(self):
        self._update_eye_btn()
        self._update_gold_toggle()
        try: self._update_stock_toggle()
        except Exception: pass
        try: self._update_sect_toggle()
        except Exception: pass
        d = self.data
        if not d:
            return
        m = d.get("main")
        if m:
            self.m_name.config(text=self._mask(m["name"].replace("（元/克）", "")))
            self.m_price.config(text=self._mask(f'{m["price"]:.2f}') if m.get("price") is not None else "—")
            col = THEME.up if m.get("up") else (THEME.down if m.get("down") else THEME.fg3)
            pct = m.get("pct")
            self.m_chg.config(text=self._mask(f'{sign(pct)}{pct:.2f}%') if pct is not None else "—", fg=col)
            self.m_price.config(fg=col)
        # 配置损坏提示：优先占用时间位展示一次（10s），之后恢复正常时间显示。
        # 详细原因/备份文件名已落日志；这里只给用户一个"不是无缘无故重置"的交代。
        if self._conf_notice and time.time() < self._conf_notice_until:
            self.t_time.config(text="配置已重置", fg=THEME.up)
        else:
            self._conf_notice = None  # 只提示一次
            self.t_time.config(text=(d["updated_at"][11:16]), fg=THEME.fg3)
        self.dot.config(fg=THEME.blue)

        if not self.conf["mini"] and not self._search_box_visible:
            # 搜索结果展开时不重绘股票区：否则周期刷新 _render 会触发
            # _render_stocks → search_box.pack_forget()，把下拉结果“自己吃掉”。
            self._render_stocks()
            self._render_sectors()

    def _fit_name(self, name):
        """按名称列（col 0）宽度截断过长股票名，超出部分以 … 结尾。
        列宽固定方案下列宽不可被内容撑大，否则删除按钮会被推出窗口外。"""
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

    def _render_stocks(self):
        """渲染关注列表的股票行。每只股票**双行布局**（参考示意图）：
          第 1 行：股票名（10pt 粗体）                🗑 删除
          第 2 行：股票代码  实时价格  涨幅%  成交额
        整体用 grid 做 4 列对齐：列 0=名称/代码、列 1=价格、列 2=涨跌幅、列 3=成交额、列 4=🗑
        列标题行：股票名称 / 实时价格 / 涨幅 / 成交额
        """
        codes = self.conf.get("watchlist") or []
        # 搜索结果展开时（_search_box_visible=True），绝不碰股票区/搜索框的 pack 状态，
        # 否则周期刷新 _render 会把下拉结果 pack_forget 掉（下拉“自己消失”的根因）。
        if self._search_box_visible:
            return
        try: self.search_box.pack_forget()
        except Exception: pass

        # ── 彻底清掉 stocks_box 里的旧 grid 内容 ──
        # 必须在 `if not codes: return` 之前执行：删掉最后一只股票后 watchlist 为空，
        # 若先 return，旧股票行/列标题会残留在界面上 → 表现为“点🗑没反应”。
        # （旧代码先 return 后清理，且 row[1] 恒为 None 的 destroy 循环永远 no-op）
        for child in list(self.stocks_box.pack_slaves()):
            child.pack_forget()
        for child in list(self.stocks_box.grid_slaves()):
            child.destroy()
        self.stock_rows = []
        # 表头显隐必须赶在空列表 early return 之前：删光自选股时表头也要跟着隐藏
        self._show_stocks_header(bool(codes))

        if not codes:
            # watchlist 空：不渲染任何内容（无状态栏、无提示文案，保持极简）
            self.root.after_idle(self._layout_stocks)
            return

        # ── 共享 grid：所有股票行都直接 grid 到 self.stocks_box ──
        # 列标题在独立的 stocks_header（固定不滚动），两容器配置相同的
        # 固定像素列宽（weight=0 + minsize），列边界严格一致。
        for i, m in enumerate(STOCK_COL_WIDTHS):
            self.stocks_box.columnconfigure(i, weight=0, minsize=m)
        self.stocks_box.columnconfigure(5, weight=0, minsize=18)

        # ── 股票行（row 0..N，列标题已在独立 stocks_header）──
        # 关键：所有 widget 都直接 grid 到 self.stocks_box（不创建 row_frame 中间层），
        # col 0-3 宽度由 stocks_box 的 columnconfigure uniform="stock" 一次分配，
        # 与 header 容器的列宽严格等宽。
        # 每只股票占 2 行（base_row 和 base_row+1）：name/code 上下两行，
        # price/pct/amt/del 用 rowspan=2 占两行。
        for idx, code in enumerate(codes[:STOCKS_MAX]):
            base_row = idx * 2
            d = self.stock_data.get(code, {})
            # 超长名称截断加 …（列宽固定，防长名把列撑宽挤出删除按钮）
            name = self._mask(self._fit_name(d.get("name") or code))
            price = d.get("price")
            pct = d.get("change_pct")
            amount = d.get("amount_yi")
            pct_col = THEME.up if (pct or 0) > 0 else (THEME.down if (pct or 0) < 0 else THEME.fg3)
            price_col = pct_col if price is not None else THEME.fg

            # col 0: 股票名（base_row）+ 代码（base_row+1）
            name_l = tk.Label(self.stocks_box, text=name, fg=THEME.fg, bg=THEME.bg,
                              font=F_STOCK_NAME, anchor="w")
            name_l.grid(row=base_row, column=0, sticky="nswe", padx=0, pady=(4, 0))
            code_l = tk.Label(self.stocks_box, text=self._mask(code), fg=THEME.fg3, bg=THEME.bg,
                              font=("Microsoft YaHei UI", 8), anchor="w")
            code_l.grid(row=base_row + 1, column=0, sticky="nswe", padx=0, pady=(0, 4))
            # col 1: 价格（rowspan=2 跨两行，与股票名同行水平对齐）
            price_l = tk.Label(self.stocks_box,
                               text=self._mask(f"{price:.2f}") if price is not None else "—",
                               fg=price_col, bg=THEME.bg, font=F_STOCK_PRC, anchor="w")
            price_l.grid(row=base_row, column=1, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 2: 涨跌幅（rowspan=2）
            pct_text = self._mask(f"{sign(pct)}{pct:.2f}%") if pct is not None else "—"
            pct_l = tk.Label(self.stocks_box, text=pct_text, fg=pct_col, bg=THEME.bg,
                             font=F_STOCK_PCT, anchor="w")
            pct_l.grid(row=base_row, column=2, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 3: 换手率（rowspan=2，中性数据用 fg2）
            tr = d.get("turnover")
            tr_text = self._mask(f"{tr:.2f}%") if tr is not None else "—"
            tr_l = tk.Label(self.stocks_box, text=tr_text, fg=THEME.fg2, bg=THEME.bg,
                            font=F_STOCK_AMT, anchor="w")
            tr_l.grid(row=base_row, column=3, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 4: 成交额 Canvas（rowspan=2，文字贴 cell 左 x=3，与其他列对齐方式统一）
            amt_text = self._mask(f"{amount:.2f}亿") if amount is not None else "—"
            amt_l = tk.Canvas(self.stocks_box, bg=THEME.bg, width=10, height=44,
                              highlightthickness=0, bd=0)
            amt_l.grid(row=base_row, column=4, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            amt_text_id = amt_l.create_text(0, 0, text=amt_text,
                                            font=F_STOCK_AMT, fill=THEME.fg2, anchor="w")
            def _draw_amt(_evt=None, c=amt_l, tid=amt_text_id, txt=amt_text, fg=THEME.fg2):
                h_ = c.winfo_height()
                if c.winfo_width() < 4:
                    return
                c.coords(tid, 3, h_ / 2)
                c.itemconfig(tid, text=txt, fill=fg)
            amt_l.bind("<Configure>", _draw_amt)
            # col 5: 🗑 删除（rowspan=2，跨两行垂直居中；padx/pady 清零压掉
            # 隐式内边距，避免 reqwidth 超过列 minsize 撑宽末列）
            del_btn = tk.Label(self.stocks_box, text="🗑", fg=THEME.fg3, bg=THEME.bg,
                               font=("Segoe UI Emoji", 10), cursor="hand2",
                               padx=0, pady=0, borderwidth=0, highlightthickness=0)
            del_btn.grid(row=base_row, column=5, rowspan=2, sticky="nse", padx=(2, 0), pady=(4, 4))
            # 只绑按下（Button-1）：若再绑 ButtonRelease-1，一次点击会触发两次删除——
            # 滚动状态下按下滑删掉最后一只后列表重建、滚动复位，松开时 Release 会落进
            # 复位后同一屏幕位置的另一只股票的 🗑，造成连带删除。
            del_btn.bind("<Button-1>", lambda e, c=code: self._remove_stock(c))
            del_btn.bind("<Enter>", lambda e, b=del_btn: b.config(fg=THEME.up))
            del_btn.bind("<Leave>", lambda e, b=del_btn: b.config(fg=THEME.fg3))

            # stock_rows tuple: (code, frame=None, name_l, price_l, pct_l, amt_l, del_btn, code_l, amt_tid, _draw_amt, amt_text)
            # frame=None 因为所有 widget 都在 self.stocks_box，destroy 时按 widget 自身处理
            self.stock_rows.append((code, None, name_l, price_l, pct_l, amt_l, del_btn, code_l,
                                    amt_text_id, _draw_amt, amt_text))

        # 行高实测 + 可视高度/窗口尺寸联动（≤3 只实高展示，>3 只锁定 3 行 + 滚动）
        self.root.after_idle(self._layout_stocks)

    # ── 股票区高度自适应 / 滚动 ──
    def _stocks_header_h(self):
        """列标题行实际高度（含 pady (2, 0)）。"""
        hs = []
        for w in getattr(self, "_hdr_widgets", []):
            try:
                if w.winfo_exists():
                    hs.append(w.winfo_reqheight())
            except Exception:
                pass
        return (max(hs) if hs else STOCKS_HEADER_H) + 2

    def _layout_stocks(self):
        """按股票数设定股票区（Canvas）可视高度：
        ≤3 只 → 画布高度 = 实测股票行总高（列标题在画布外固定），窗口随之扩展；
        >3 只 → 锁定 3 行高度，其余股票滚轮滚动查看，窗口高度不再增长。
        _stocks_view_h = 表头高度 + 画布高度（股票区整体可视高度，供窗口尺寸计算）。
        实测完成后若可视高度变化，同步刷新窗口尺寸，保证布局稳定。"""
        if getattr(self, "_in_layout", False):
            return
        if self.conf.get("mini") or self._search_box_visible:
            return
        self._in_layout = True
        try:
            c = self.stocks_canvas
            n = len(self.conf.get("watchlist") or [])
            if self.conf.get("stocks_collapsed"):
                # 收起态：画布隐藏（高度归零），可视高度只含表头行（按钮在表头上）
                new_h = self._stocks_header_h()
                c.configure(height=0)
                self._stocks_scroll_on = False
            elif n == 0:
                new_h = 0
                c.configure(height=0)
                self._stocks_scroll_on = False
                self._stocks_layout_n = 0
            else:
                self.stocks_box.update_idletasks()
                total = self.stocks_box.winfo_reqheight()  # 只含股票行（表头在画布外）
                if total < n:
                    return  # 布局尚未就绪，等下一次 <Configure>
                hdr = self._stocks_header_h()
                row = total / float(n)
                visible = min(n, STOCKS_VISIBLE)
                new_h = int(round(hdr + row * visible))
                # 同股票数时保留滚动位置（周期刷新会重建行，不应把用户滚到的位置重置）
                frac = c.yview()[0] if getattr(self, "_stocks_layout_n", None) == n else 0.0
                c.configure(height=int(round(row * visible)),
                            yscrollincrement=max(30, int(round(row))))
                c.configure(scrollregion=(0, 0, 0, total))
                self._stocks_scroll_on = n > STOCKS_VISIBLE
                self._stocks_layout_n = n
                c.yview_moveto(frac)
            if self._stocks_view_h != new_h:
                self._stocks_view_h = new_h
                self._apply_size()
                self._place_keep_corner()
        finally:
            self._in_layout = False

    def _on_stocks_wheel(self, e):
        """滚轮滚动：股票区 >3 只或板块区 >2 个时，指针落在对应画布上即滚动，
        其他区域不受影响。"""
        if self.conf.get("mini"):
            return
        step = -1 if getattr(e, "delta", 0) > 0 else 1

        def _inside(c):
            try:
                px, py = c.winfo_pointerx(), c.winfo_pointery()
                rx, ry = c.winfo_rootx(), c.winfo_rooty()
                return rx <= px < rx + c.winfo_width() and ry <= py < ry + c.winfo_height()
            except Exception:
                return False

        # 板块区（指针在板块画布上且滚动已启用）
        sc = getattr(self, "sect_canvas", None)
        if (sc is not None and getattr(self, "_sect_scroll_on", False)
                and not self._search_box_visible and _inside(sc)):
            sc.yview_scroll(step, "units")
            return
        # 股票区
        if self._search_box_visible:
            return
        if not getattr(self, "_stocks_scroll_on", False):
            return
        c = self.stocks_canvas
        if not _inside(c):
            return  # 指针不在股票区，不处理
        c.yview_scroll(step, "units")

    # ── 板块区（"下"段）渲染 / 高度自适应 ──
    def _render_sectors(self):
        """渲染板块列表。与股票区同构的双行布局：
          第 1 行：板块名（10pt 粗体）              🗑 删除
          第 2 行：板块代码  资金流入  涨幅  换手率  概念强度
        数据缺失的字段统一显示 "---"。sectors 为空时整区（含分隔线）隐藏。"""
        if self.conf.get("mini"):
            return
        codes = self.conf.get("sectors") or []
        # 空板块：整区隐藏（分隔线一并收起），窗口高度联动收缩
        if not codes:
            try: self.sect_divider.pack_forget()
            except Exception: pass
            try: self.sect_area.pack_forget()
            except Exception: pass
            if getattr(self, "_sect_view_h", None) != 0:
                self._sect_view_h = 0
                self.root.after_idle(self._apply_size)
            return
        # 有板块但整区还藏着（曾被清空）→ 重新 pack（_apply_size 顺序与初始一致）
        if not self.sect_divider.winfo_ismapped() and self.root.winfo_viewable():
            try: self.sect_divider.pack(fill="x", pady=(8, 0))
            except Exception: pass
            try: self.sect_area.pack(fill="x", pady=(0, 4))
            except Exception: pass

        # 彻底清掉旧 grid 内容
        for child in list(self.sect_box.grid_slaves()):
            child.destroy()
        self._sect_rows = []
        # 表头显隐：有板块才显示（固定在画布上方；画布收起时 before= 失效 → 降级直接 pack）
        try:
            if codes and not self.sect_header.winfo_ismapped():
                try:
                    self.sect_header.pack(fill="x", before=self.sect_canvas)
                except Exception:
                    self.sect_header.pack(fill="x")
            elif not codes:
                self.sect_header.pack_forget()
        except Exception:
            pass

        for i, m in enumerate(SECT_COL_WIDTHS):
            self.sect_box.columnconfigure(i, weight=0, minsize=m)
        self.sect_box.columnconfigure(5, weight=0, minsize=18)

        MISS = "---"  # 数据缺失统一占位
        for idx, code in enumerate(codes[:SECTORS_MAX]):
            base_row = idx * 2
            d = self.sect_data.get(code, {})
            name = self._mask(self._fit_name(d.get("name") or code))
            inflow = d.get("inflow_yi")
            pct = d.get("change_pct")
            tr = d.get("turnover")
            strength = d.get("strength")

            # col 0: 板块名 + 代码（双行）
            name_l = tk.Label(self.sect_box, text=name, fg=THEME.fg, bg=THEME.bg,
                              font=F_STOCK_NAME, anchor="w")
            name_l.grid(row=base_row, column=0, sticky="nswe", padx=0, pady=(4, 0))
            code_l = tk.Label(self.sect_box, text=self._mask(code), fg=THEME.fg3, bg=THEME.bg,
                              font=("Microsoft YaHei UI", 8), anchor="w")
            code_l.grid(row=base_row + 1, column=0, sticky="nswe", padx=0, pady=(0, 4))
            # col 1: 资金流入(亿)，正红负绿（中国惯例），缺失 ---
            if inflow is None:
                inflow_text, inflow_col = MISS, THEME.fg3
            else:
                inflow_text = self._mask(f"{inflow:.2f}")
                inflow_col = THEME.up if inflow > 0 else (THEME.down if inflow < 0 else THEME.fg2)
            inflow_l = tk.Label(self.sect_box, text=inflow_text, fg=inflow_col, bg=THEME.bg,
                                font=F_STOCK_AMT, anchor="w")
            inflow_l.grid(row=base_row, column=1, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 2: 涨幅
            pct_col = THEME.up if (pct or 0) > 0 else (THEME.down if (pct or 0) < 0 else THEME.fg3)
            pct_text = self._mask(f"{sign(pct)}{pct:.2f}%") if pct is not None else MISS
            pct_l = tk.Label(self.sect_box, text=pct_text, fg=pct_col, bg=THEME.bg,
                             font=F_STOCK_PCT, anchor="w")
            pct_l.grid(row=base_row, column=2, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 3: 换手率
            tr_text = self._mask(f"{tr:.2f}%") if tr is not None else MISS
            tr_l = tk.Label(self.sect_box, text=tr_text, fg=THEME.fg2, bg=THEME.bg,
                            font=F_STOCK_AMT, anchor="w")
            tr_l.grid(row=base_row, column=3, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 4: 概念强度（今日涨幅在全部行业+概念板块中的名次，1=最强；
            # 排名拉不到时 ---；有值时红色 第XX名）
            if strength is None:
                st_text, st_col = MISS, THEME.fg3
            else:
                st_text, st_col = self._mask(f"第{strength}名"), THEME.up
            st_l = tk.Label(self.sect_box, text=st_text, fg=st_col, bg=THEME.bg,
                            font=F_STOCK_AMT, anchor="w")
            st_l.grid(row=base_row, column=4, rowspan=2, sticky="nswe", padx=0, pady=(4, 4))
            # col 5: 🗑 删除（内边距清零防撑宽末列，与股票区同款）
            del_btn = tk.Label(self.sect_box, text="🗑", fg=THEME.fg3, bg=THEME.bg,
                               font=("Segoe UI Emoji", 10), cursor="hand2",
                               padx=0, pady=0, borderwidth=0, highlightthickness=0)
            del_btn.grid(row=base_row, column=5, rowspan=2, sticky="nse", padx=(2, 0), pady=(4, 4))
            del_btn.bind("<Button-1>", lambda e, c=code: self._remove_sector(c))
            del_btn.bind("<Enter>", lambda e, b=del_btn: b.config(fg=THEME.up))
            del_btn.bind("<Leave>", lambda e, b=del_btn: b.config(fg=THEME.fg3))

        self.root.after_idle(self._layout_sectors)

    def _remove_sector(self, code):
        sl = self.conf.get("sectors") or []
        if code in sl:
            sl.remove(code)
            self.conf["sectors"] = sl
            save_conf(self.conf)
            self.sect_data.pop(code, None)
            self._render_sectors()

    def _layout_sectors(self):
        """按板块数设定板块区（Canvas）可视高度：≤2 个实高展示，>2 个锁定
        2 行 + 滚轮滚动。实测后可视高度变化时联动窗口尺寸。"""
        if getattr(self, "_sect_in_layout", False):
            return
        if self.conf.get("mini") or self._search_box_visible:
            return
        self._sect_in_layout = True
        try:
            c = self.sect_canvas
            n = len(self.conf.get("sectors") or [])
            if self.conf.get("sectors_collapsed"):
                # 收起态：画布隐藏，可视高度只含表头行（按钮在表头上）
                new_h = self._stocks_header_h_of(self._sect_hdr_canvases)
                c.configure(height=0)
                self._sect_scroll_on = False
            elif n == 0:
                new_h = 0
                c.configure(height=0)
                self._sect_scroll_on = False
                self._sect_layout_n = 0
            else:
                self.sect_box.update_idletasks()
                total = self.sect_box.winfo_reqheight()
                if total < n:
                    return  # 布局尚未就绪，等下一次 <Configure>
                hdr = self._stocks_header_h_of(self._sect_hdr_canvases)
                row = total / float(n)
                visible = min(n, SECTORS_VISIBLE)
                frac = c.yview()[0] if getattr(self, "_sect_layout_n", None) == n else 0.0
                c.configure(height=int(round(row * visible)),
                            yscrollincrement=max(30, int(round(row))))
                c.configure(scrollregion=(0, 0, 0, total))
                self._sect_scroll_on = n > SECTORS_VISIBLE
                self._sect_layout_n = n
                c.yview_moveto(frac)
                new_h = int(round(hdr + row * visible))
            if self._sect_view_h != new_h:
                self._sect_view_h = new_h
                self._apply_size()
                self._place_keep_corner()
        finally:
            self._sect_in_layout = False

    def _stocks_header_h_of(self, canvases):
        """通用表头行高实测（含 pady (2, 0)），股票区/板块区共用逻辑。"""
        hs = []
        for w in canvases:
            try:
                if w.winfo_exists():
                    hs.append(w.winfo_reqheight())
            except Exception:
                pass
        return (max(hs) if hs else SECTORS_HEADER_H) + 2

    # ── 搜索交互（单态胶囊 + focus + 文本驱动）──
    def _show_ph(self):
        """placeholder 用 Canvas text 渲染（_draw_pill 内做），这里只翻状态。
        guard：ph_on / var 非空 / 聚焦中 时不动。"""
        if self._search_ph_on or self._search_var.get():
            return
        try:
            if self.root.focus_get() is self.search_entry:
                return
        except Exception:
            pass
        self._search_ph_on = True
        self._draw_pill()  # 重画让 canvas text 出现

    def _hide_ph(self):
        if not self._search_ph_on:
            return
        self._search_ph_on = False
        self._draw_pill()  # 重画让 canvas text 消失

    def _on_search_change(self):
        if self._suppress_trace:
            return  # 兼容老 trace 抑制（保留以防外部代码改 _search_var）
        if self._search_ph_on:
            # 用户开始输入：立刻收起 placeholder 文字
            self._hide_ph()
        if self._search_after_id is not None:
            try: self.root.after_cancel(self._search_after_id)
            except Exception: pass
            self._search_after_id = None
        self._search_retry = 0
        try:
            kw = self.search_entry.get().strip()
        except Exception:
            kw = self._search_var.get().strip()
        if not kw:
            # 清空：恢复 placeholder + 收起结果
            self._show_ph()
            self._search_results = []
            self._hide_search_results()
            return
        # 有内容：展开结果（只要还在搜索中就不自动收起）
        self._show_search_results()
        self._search_after_id = self.root.after(220, lambda k=kw: self._do_search(k))

    def _on_search_focus(self, focused):
        """聚焦 → 清掉 placeholder；失焦 → 200ms 后检查。"""
        if focused:
            self._hide_ph()
            try:
                kw = self.search_entry.get().strip()
            except Exception:
                kw = self._search_var.get().strip()
            if kw:
                self._show_search_results()
        else:
            self.root.after(200, self._maybe_hide_search_results)

    def _maybe_hide_search_results(self):
        """失焦 200ms 后检查：Entry 有内容 → 保持结果展开（用户还要继续点选下拉）；
        空 → 恢复 placeholder 并收起结果。
        用 Entry 实际内容判断（输入法组合期 StringVar 可能与显示不同步）。"""
        try:
            if self.search_entry.get().strip():
                return  # 内容非空，保持展开
        except Exception:
            if self._search_var.get().strip():
                return
        self._show_ph()
        self._search_results = []
        self._hide_search_results()

    def _sync_search_state(self):
        """每秒自愈 watchdog：Entry 有内容但下拉被隐藏 → 重新展开；
        无内容但下拉还在 → 收起。兜底一切未知路径导致的“下拉消失/输入无反应”。"""
        if self.conf.get("mini"):
            return
        try:
            has_text = bool(self.search_entry.get().strip())
        except Exception:
            return
        if has_text and not self._search_box_visible:
            self._show_search_results()
        elif not has_text and self._search_box_visible:
            self._search_results = []
            self._hide_search_results()
            self._show_ph()

    def _clear_search(self):
        """Esc / 选中下拉项后：清空 + 收起结果 + 恢复 placeholder。"""
        self._hide_ph()
        self._search_var.set("")
        self._search_results = []
        self._hide_search_results()
        self._show_ph()

    def _show_search_results(self):
        # 只要还在搜索中，搜索结果框必须保持可见（即使之前被异常 pack_forget 过）：
        # 收起股票区（滚动画布）、确保搜索结果区 packed，再渲染。
        try: self.stocks_canvas.pack_forget()
        except Exception: pass
        try: self.stocks_header.pack_forget()
        except Exception: pass
        try: self.search_box.pack(fill="x")
        except Exception: pass
        self._search_box_visible = True
        self._render_search_results()
        self._apply_size()
        self._place_keep_corner()

    def _hide_search_results(self):
        if not self._search_box_visible:
            return
        try: self.search_box.pack_forget()
        except Exception: pass
        try:
            if (not self.conf.get("stocks_collapsed")
                    and not self.stocks_canvas.winfo_ismapped()):
                self.stocks_canvas.pack(fill="x")
        except Exception: pass
        self._show_stocks_header(bool(self.conf.get("watchlist")))
        self._search_box_visible = False
        self._apply_size()
        self._place_keep_corner()

    def _on_search_enter(self):
        if not self._search_results:
            self._do_search(self._search_var.get().strip())
            return
        target = self._search_results[0]
        # 板块/概念结果（BK 代码）回车 → 添加进板块区，不进股票区
        if target.get("sector") or str(target["code"]).upper().startswith("BK"):
            self._add_sector(target["code"], target["name"])
        else:
            self._add_stock(target["code"], target["name"])

    def _do_search(self, kw):
        self._search_after_id = None
        if not kw:
            return
        threading.Thread(target=self._search_worker, args=(kw,), daemon=True).start()

    def _search_worker(self, kw):
        try:
            results = gold_data.search_stock(kw, limit=SEARCH_MAX_ROWS)
        except Exception:
            results = None
        if results is None:
            # 网络失败（区别于确实无匹配）：通知 UI 保留旧结果并重试
            self.q.put(("search_err", kw))
            return
        self.q.put(("search", kw, results))

    def _on_search_results(self, kw, results):
        # 用 Entry 实际内容（而非 StringVar）比对，规避输入法组合期 var 不同步
        try:
            cur = self.search_entry.get().strip()
        except Exception:
            cur = self._search_var.get().strip()
        if kw != cur:
            return
        self._search_results = results
        self._search_retry = 0
        if not self._search_box_visible:
            # 自愈：下拉被意外隐藏时重新展开（_show_search_results 内部会 render + resize）
            self._show_search_results()
        else:
            self._render_search_results()
            self._apply_size()
            self._place_keep_corner()

    def _on_search_err(self, kw):
        """搜索请求网络失败：保留旧结果（下拉不消失），800ms 后自动重试，最多 2 次。"""
        try:
            cur = self.search_entry.get().strip()
        except Exception:
            return
        if kw != cur:
            return
        self._search_retry = getattr(self, "_search_retry", 0) + 1
        if self._search_retry <= 2 and self._search_box_visible:
            self._search_after_id = self.root.after(
                800, lambda k=kw: self._do_search(k))

    def _render_search_results(self):
        for child in list(self.search_list.winfo_children()):
            try: child.destroy()
            except Exception: pass
        if not self._search_results:
            hint = tk.Label(self.search_list, text="（无匹配结果）",
                            fg=THEME.fg3, bg=THEME.bg, font=("Microsoft YaHei UI", 9))
            hint.pack(anchor="w", pady=(2, 0))
            return
        for r in self._search_results:
            row = tk.Frame(self.search_list, bg=THEME.bg)
            row.pack(fill="x", pady=1)
            left = tk.Frame(row, bg=THEME.bg)
            left.pack(side="left", fill="x", expand=True)
            name_l = tk.Label(left, text=self._mask(r["name"]), fg=THEME.fg, bg=THEME.bg,
                              font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
            name_l.pack(side="left")
            code_l = tk.Label(left, text=f" ({self._mask(r['code'])})", fg=THEME.fg3, bg=THEME.bg,
                              font=("Microsoft YaHei UI", 9), anchor="w")
            code_l.pack(side="left")
            # 板块/概念结果（BK 代码）：加"板块"标签提示归属，点击添加进板块区
            is_sect = bool(r.get("sector")) or str(r["code"]).upper().startswith("BK")
            add_fn = self._add_sector if is_sect else self._add_stock
            if is_sect:
                tag_l = tk.Label(left, text=" 板块", fg=THEME.blue, bg=THEME.bg,
                                 font=("Microsoft YaHei UI", 8), anchor="w")
                tag_l.pack(side="left")
            add_btn = tk.Label(row, text="+", fg=THEME.up, bg=THEME.bg,
                               font=("Microsoft YaHei UI", 12, "bold"), cursor="hand2")
            add_btn.pack(side="right", padx=(4, 0))
            add_btn.bind("<Button-1>", lambda e, c=r["code"], n=r["name"], f=add_fn: f(c, n))
            add_btn.bind("<Enter>", lambda e, b=add_btn: b.config(fg=THEME.blue))
            add_btn.bind("<Leave>", lambda e, b=add_btn: b.config(fg=THEME.up))
            for w in (row, left, name_l, code_l, *( (tag_l,) if is_sect else () )):
                w.bind("<Button-1>", lambda e, c=r["code"], n=r["name"], f=add_fn: f(c, n))
                w.config(cursor="hand2")

    def _add_stock(self, code, name=None):
        code = str(code).strip()
        if not code:
            return
        # 防御性分流：BK 代码是东财板块/概念，股票接口拉不到行情，
        # 误加进股票区会永远显示 "—"——一律转投板块区。
        if code.upper().startswith("BK"):
            self._add_sector(code, name)
            return
        wl = self.conf.get("watchlist") or []
        if code in wl:
            return
        wl.append(code)
        self.conf["watchlist"] = wl
        # 收起态下加股票 → 自动展开（否则新股票行被藏着，用户以为没加上）
        self.conf["stocks_collapsed"] = False
        save_conf(self.conf)
        # 加完清空搜索 → 回到股票区，并按新股票数重算窗口高度
        # （空态是紧凑高度 164，不加股票后必须拉回，否则新股票行被裁掉）
        self._clear_search()
        # 新增股票立即发车（走股票快轨，不等下一个周期）：新行先占位，数据 1 次 RTT 后填上
        self._stock_last = 0.0
        self.fetch_stock()
        self._render_stocks()
        self._apply_size()
        self._place_keep_corner()

    def _add_sector(self, code, name=None):
        """添加板块/概念到板块区（conf["sectors"]），与 _add_stock 对称。"""
        code = str(code).strip().upper()
        if not code:
            return
        sl = self.conf.get("sectors") or []
        if code in sl:
            return
        sl.append(code)
        self.conf["sectors"] = sl
        # 收起态下加板块 → 自动展开（与 _add_stock 对称）
        self.conf["sectors_collapsed"] = False
        save_conf(self.conf)
        # 加完清空搜索 → 回到各区常态，并按板块数重算窗口高度
        self._clear_search()
        # 立即发车（股票/板块共用一个快轨 worker）：新行先占位，数据 1 次 RTT 后填上
        self._stock_last = 0.0
        self.fetch_stock()
        self._render_sectors()
        self._apply_size()
        self._place_keep_corner()

    def _remove_stock(self, code):
        # 防重入兜底：同一次物理点击的多个事件路径（按下/松开）可能在极短间隔内
        # 各触发一次删除，300ms 内的第二次调用一律忽略（人手不可能 300ms 内连删两只）。
        now = time.time()
        if now - getattr(self, "_last_remove_t", 0.0) < 0.3:
            return
        self._last_remove_t = now
        wl = self.conf.get("watchlist") or []
        if code in wl:
            wl.remove(code)
            self.conf["watchlist"] = wl
            save_conf(self.conf)
        # 无条件重建（即使 code 已不在列表）：保证 UI 与配置强制一致，杜绝“点了没反应”。
        # 延迟到当前事件处理完成后重建 UI，避免销毁正在处理点击事件的 del_btn 自身。
        self.root.after(0, self._render_stocks)
        self.root.after(0, self._apply_size)
        self.root.after(0, self._place_keep_corner)

    def quit(self):
        self.conf["x"], self.conf["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_conf(self.conf)
        self.root.destroy()

    def run(self):
        print("[init] 进入 mainloop", flush=True)
        self.root.mainloop()


if __name__ == "__main__":
    try:
        import argparse
        ap = argparse.ArgumentParser(description="黄金盯盘浮窗")
        ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"金价刷新间隔（秒），最小 {MIN_INTERVAL}，默认 {DEFAULT_INTERVAL}")
        ap.add_argument("--stock-interval", type=int, default=DEFAULT_STOCK_INTERVAL,
                        help=f"股票刷新间隔（秒），最小 {MIN_STOCK_INTERVAL}，"
                             f"默认 {DEFAULT_STOCK_INTERVAL}（与金价解耦的独立快轨）")
        args = ap.parse_args()
        glog.info(f"盯盘 v{__version__} 启动 interval={args.interval} "
                  f"stock_interval={args.stock_interval} frozen={getattr(sys, 'frozen', False)}")
        Widget(interval=args.interval, stock_interval=args.stock_interval).run()
    except Exception:
        glog.exception("主流程未捕获异常，退出")
        raise
