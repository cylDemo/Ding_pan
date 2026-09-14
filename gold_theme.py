# -*- coding: utf-8 -*-
"""盯盘 · 主题与排版常量（零依赖模块）。

从 gold_widget.py 迁出（Tier 0.2）。本模块**不依赖 Tk、不依赖进程状态**，
可被任何层直接 import：颜色表、字体、列宽、尺寸阈值全部集中在此，
避免"改一个字号要在 2000 行里找"。

约束：
  · 本模块只放**常量与只读持有器**，不得放入与窗口生命周期相关的逻辑；
  · `THEME` 是全局单例持有器（可变），`THEME.set(mode)` 后所有读点立即生效。
"""

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
        if k.startswith("_"):
            raise AttributeError(k)
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
