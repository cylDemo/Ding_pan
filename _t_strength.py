# -*- coding: utf-8 -*-
"""概念强度（板块涨幅排名）回归测试：
1) _em_board_codes：push2delay 分页拉取 + 24h 缓存（二次调用不发请求）；
2) _em_strength_rank：按涨幅降序名次 + 60s 缓存 + 失败沿用旧缓存；
3) quote_sectors：strength 正确填充；排名失败时 None 不影响其他字段；
4) UI：第N名 红色渲染、缺失 "---"、列宽不被撑爆。
"""
import json, os, re, sys, tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_data as gd

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "watchlist": [], "sectors": ["BK1660"]},
          open(_tmp, "w", encoding="utf-8"))

fails = []

# ── mock：路由 clist（分页板块列表）与 ulist.np（行情）──
_cnt = {"clist": 0, "ulist": 0}
_fail_ulist = {"v": False}
_BOARDS = [f"BK{i:04d}" for i in range(1, 11)]      # BK0001..BK0010

class _Resp:
    def __init__(self, payload): self._p = payload
    def read(self): return json.dumps(self._p).encode("utf-8")

def _ulist_diff():
    diff = [{"f12": "BK1660", "f14": "光纤概念", "f3": 9.9, "f8": 2.82, "f62": -3.0e9}]
    diff += [{"f12": c, "f14": c, "f3": float(c[2:]), "f8": 1.0, "f62": 1.0e8}
             for c in _BOARDS]                       # 涨幅 1.0 .. 10.0
    return diff

def _fake_http(url, headers=None, timeout=10):
    if "/clist/" in url:
        _cnt["clist"] += 1
        pn = int(re.search(r"pn=(\d+)", url).group(1))
        return _Resp({"data": {"diff": [] if pn > 1 else
                               [{"f12": c} for c in _BOARDS], "total": len(_BOARDS)}})
    if "ulist.np" in url:
        if _fail_ulist["v"] and url.endswith("fields=f3,f12&fltt=2"):
            raise OSError("conn reset")   # 只让排名批量请求失败，行情请求正常
        _cnt["ulist"] += 1
        return _Resp({"data": {"diff": _ulist_diff()}})
    raise AssertionError(f"意外 URL: {url}")

_real_http = gd._http_get
gd._http_get = _fake_http
gd._em_board_cache = {"ts": 0.0, "codes": []}
gd._em_rank_cache = {"ts": 0.0, "rank": {}}

# ── 1. 板块代码列表：拉取 + 缓存 ──
codes = gd._em_board_codes()
if sorted(codes) != _BOARDS: fails.append(f"板块列表不对: {codes}")
c1 = _cnt["clist"]
if gd._em_board_codes() != codes or _cnt["clist"] != c1:
    fails.append("板块列表 24h 缓存未生效")

# ── 2. 排名：涨幅降序 ──
rank = gd._em_strength_rank()
expect = {"BK0010": 1, "BK1660": 2, "BK0009": 3, "BK0001": 11}
for k, v in expect.items():
    if rank.get(k) != v: fails.append(f"排名 {k}={rank.get(k)} 期望 {v}")
if len(rank) != 11: fails.append(f"排名条数 {len(rank)} 期望 11")
u1 = _cnt["ulist"]
if gd._em_strength_rank() != rank or _cnt["ulist"] != u1:
    fails.append("排名 60s 缓存未生效")

# ── 3. quote_sectors：strength 填充 ──
r = gd.quote_sectors(["BK1660"])
if r.get("BK1660", {}).get("strength") != 2:
    fails.append(f"quote_sectors strength 未填充: {r}")
if r.get("BK1660", {}).get("name") != "光纤概念":
    fails.append(f"quote_sectors 名称不对: {r}")

# ── 4. 排名失败：沿用旧缓存；从未成功过(空缓存+失败) → {}，行情其他字段不受影响 ──
gd._em_rank_cache = {"ts": 0.0, "rank": dict(rank)}
_fail_ulist["v"] = True
r2 = gd._em_strength_rank()
if r2 != rank: fails.append("排名失败未沿用旧缓存")
gd._em_rank_cache = {"ts": 0.0, "rank": {}}
r3 = gd.quote_sectors(["BK1660"])
if r3.get("BK1660", {}).get("strength") is not None:
    fails.append(f"排名失败时 strength 应为 None: {r3}")
if r3.get("BK1660", {}).get("name") != "光纤概念":
    fails.append(f"排名失败影响其他字段: {r3}")
_fail_ulist["v"] = False

# ── 5. UI 渲染 ──
import gold_widget as gw
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self: None
gd._http_get = _real_http   # UI 部分不联网

w = gw.Widget()
root = w.root
root.withdraw()
w.conf["sectors"] = ["BK1660"]
w.sect_data = {"BK1660": {"name": "光纤概念", "inflow_yi": -30.7,
                          "change_pct": 9.9, "turnover": 2.82, "strength": 8}}
w._render_sectors()
for _ in range(30):
    root.update()
    import time as _t; _t.sleep(0.01)
texts = [c.cget("text") for c in w.sect_box.winfo_children() if isinstance(c, tk.Label)]
if "第8名" not in texts: fails.append(f"UI 缺 第8名: {texts}")
st_l = [c for c in w.sect_box.winfo_children() if isinstance(c, tk.Label)
        and c.cget("text") == "第8名"]
if st_l and str(st_l[0].cget("fg")) != str(gw.THEME.up):
    fails.append("第8名 未用红色(涨)渲染")
if st_l and st_l[0].winfo_width() > gw.SECT_COL_WIDTHS[4]:
    fails.append(f"强度列被内容撑宽: {st_l[0].winfo_width()} > {gw.SECT_COL_WIDTHS[4]}")
w.sect_data = {"BK1660": {"name": "光纤概念", "inflow_yi": None,
                          "change_pct": None, "turnover": None, "strength": None}}
w._render_sectors(); root.update()
texts2 = [c.cget("text") for c in w.sect_box.winfo_children() if isinstance(c, tk.Label)]
if texts2.count("---") < 4: fails.append(f"strength 缺失未显示 ---: {texts2}")

root.destroy()

if fails:
    print("FAIL")
    for f in fails: print(" -", f)
    sys.exit(1)
print("PASS: 概念强度全部断言通过")
