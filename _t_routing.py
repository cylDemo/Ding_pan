# -*- coding: utf-8 -*-
"""回归：搜索结果按类型分流——股票进股票区、板块/概念（BK）进板块区。"""
import json, os, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_widget as gw

fails = []

# ── T0: 真实接口——suggest 对 BK 代码/中文概念名都应打上 sector 标记 ──
import gold_data
r1 = gold_data.search_stock("BK1660", limit=5)
if not any(x["code"] == "BK1660" and x.get("sector") for x in r1):
    fails.append(f"T0 search_stock('BK1660') 未打 sector 标记: {r1}")
r2 = gold_data.search_stock("光纤", limit=8)
if r2 and not any(x.get("sector") for x in r2 if x["code"].startswith("BK")):
    fails.append("T0 中文搜索的 BK 结果未打 sector 标记")
if r2 and not all(not x.get("sector") for x in r2 if not x["code"].startswith("BK")):
    fails.append("T0 股票结果被误标 sector")
print("T0 真实接口:", [f"{x['code']}{'|板块' if x.get('sector') else ''}" for x in r2])

# 隔离配置 + 屏蔽网络线程
_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "watchlist": ["600487"], "sectors": []}, open(_tmp, "w", encoding="utf-8"))
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self, *a, **k: None

w = gw.Widget()
root = w.root
root.geometry("+200+200")
root.deiconify()


def settle(n=30):
    for _ in range(n):
        root.update()
        time.sleep(0.01)


def click_add_at(idx):
    """展开下拉并点击第 idx 条结果的行。"""
    w._search_results = w._search_results_all[idx:idx + 1]
    w._show_search_results()
    settle()
    rows = w.search_list.winfo_children()
    if not rows:
        fails.append("下拉未渲染出结果行")
        return
    rows[0].event_generate("<Button-1>", time=int(time.time() * 1000) % 2**31 + idx)
    settle(40)


# ── T1: 板块结果点击 + → 进 sectors，不进 watchlist ──
w._search_results_all = [{"code": "BK1660", "name": "光纤概念", "market": "", "sector": True}]
click_add_at(0)
if "BK1660" not in (w.conf.get("sectors") or []):
    fails.append(f"T1 板块未进 sectors: {w.conf.get('sectors')}")
if "BK1660" in (w.conf.get("watchlist") or []):
    fails.append("T1 板块被误加进 watchlist")
if not w.sect_area.winfo_ismapped() and not w.conf.get("mini"):
    pass  # 映射态受窗口位置影响，不做强断言，以配置为准
print("T1 sectors =", w.conf["sectors"], "| watchlist =", w.conf["watchlist"])

# ── T2: 股票结果点击 + → 进 watchlist ──
w._search_results_all = [{"code": "002245", "name": "蔚蓝锂芯", "market": "sz", "sector": False}]
click_add_at(0)
if "002245" not in (w.conf.get("watchlist") or []):
    fails.append(f"T2 股票未进 watchlist: {w.conf.get('watchlist')}")
print("T2 watchlist =", w.conf["watchlist"])

# ── T3: _add_stock 兜底——BK 代码直达也会转投板块区 ──
w._add_stock("bk1136")  # 小写也应 .upper() 命中
if "BK1136" not in (w.conf.get("sectors") or []) or "bk1136" in (w.conf.get("watchlist") or []):
    fails.append(f"T3 BK 代码未分流: sectors={w.conf.get('sectors')} wl={w.conf.get('watchlist')}")
print("T3 sectors =", w.conf["sectors"])

# ── T4: 回车添加——第一条是板块时回车进板块区 ──
w._search_results = [{"code": "BK1617", "name": "黄金", "market": "", "sector": True}]
w._on_search_enter()
settle(20)
if "BK1617" not in (w.conf.get("sectors") or []):
    fails.append(f"T4 回车未把板块加进 sectors: {w.conf.get('sectors')}")
# 回车添加股票
w._search_results = [{"code": "601069", "name": "西部黄金", "market": "sh", "sector": False}]
w._on_search_enter()
settle(20)
if "601069" not in (w.conf.get("watchlist") or []):
    fails.append(f"T4 回车未把股票加进 watchlist: {w.conf.get('watchlist')}")
print("T4 sectors =", w.conf["sectors"], "| watchlist =", w.conf["watchlist"])

# ── T5: 重复添加去重 ──
w._add_sector("BK1660")
if (w.conf["sectors"]).count("BK1660") != 1:
    fails.append("T5 板块重复添加未去重")
w._add_stock("002245")
if (w.conf["watchlist"]).count("002245") != 1:
    fails.append("T5 股票重复添加未去重")
print("T5 去重 OK")

root.destroy()

if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("PASS: 搜索分流（板块→板块区 / 股票→股票区 / 回车 / 兜底 / 去重）全部通过")
