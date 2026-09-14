# -*- coding: utf-8 -*-
"""板块数据稳定性回归测试（修"有时有数据有时没数据/名称退化成裸代码"）：
1) quote_sectors 网络抖动：重试后成功 → 正常返回；3 次全失败 → 返回 None（非 {}）；
2) 响应不可解析 → None；成功但代码真不存在 → {}；
3) _stock_worker 整次失败(None) → 沿用上一轮 sect_data（不闪 "---"）；
4) 成功但个别代码缺失 → 该代码保住旧名称（不退化为裸代码）；
5) 未配置 sectors → 空字典，不影响股票轨。
"""
import json, os, sys, tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_data as gd

_tmp = os.path.join(tempfile.mkdtemp(), "conf.json")
json.dump({"topmost": True, "alpha": 1.0, "mini": False, "theme": "dark",
           "watchlist": ["600487"], "sectors": ["BK1660", "BK1136"]},
          open(_tmp, "w", encoding="utf-8"))

import gold_widget as gw
gw.CONF_PATH = _tmp
gw.Widget._worker = lambda self: None
gw.Widget.fetch = lambda self, *a, **k: None
gw.Widget.fetch_stock = lambda self: None

fails = []

# ── 1. quote_sectors：抖动重试 ──
_real_http = gd._http_get
calls = {"n": 0}

class _Resp:
    def __init__(self, payload): self._p = payload
    def read(self): return json.dumps(self._p).encode("utf-8")

_OK = {"data": {"diff": [
    {"f12": "BK1660", "f14": "光纤概念", "f3": 0.25, "f8": 2.82, "f62": -3.07e9},
    {"f12": "BK1136", "f14": "光通信模块", "f3": -0.16, "f8": 4.72, "f62": 1.24e9},
]}}

def _flaky(url, headers=None, timeout=10):
    calls["n"] += 1
    if calls["n"] <= 2:          # 前 2 次抖动，之后成功（含排名链路）
        raise urllib.error.URLError("timeout")
    return _Resp(_OK)

gd._http_get = _flaky
r = gd.quote_sectors(["BK1660", "BK1136"])
if calls["n"] < 3: fails.append(f"失败后未重试: {calls['n']}")
if not isinstance(r, dict) or r.get("BK1660", {}).get("name") != "光纤概念":
    fails.append(f"重试后未恢复: {r}")

# 3 次全失败 → None（关键断言：不能是 {}，否则 UI 会当成"成功但无数据"）
def _dead(url, headers=None, timeout=10):
    raise urllib.error.URLError("conn reset")
gd._http_get = _dead
r = gd.quote_sectors(["BK1660"])
if r is not None: fails.append(f"全失败应返回 None: {r}")

# 响应不可解析 → None
class _BadResp:
    def read(self): return b"<html>502</html>"
gd._http_get = lambda url, headers=None, timeout=10: _BadResp()
r = gd.quote_sectors(["BK1660"])
if r is not None: fails.append(f"不可解析响应应返回 None: {r}")

# 成功但代码真不存在 → {}（诚实空，UI 保名逻辑兜底）
gd._http_get = lambda url, headers=None, timeout=10: _Resp({"data": {"diff": []}})
r = gd.quote_sectors(["BK9999"])
if r != {}: fails.append(f"无匹配代码应返回空字典: {r}")

gd._http_get = _real_http

# ── 2. _stock_worker 合并逻辑（同步直调，不走线程） ──
gd.quote_stocks = lambda codes: {}   # 隔离：股票轨不联网
w = gw.Widget()
root = w.root
root.withdraw()

PREV = {
    "BK1660": {"name": "光纤概念", "inflow_yi": -30.7, "change_pct": 0.25, "turnover": 2.82, "strength": None},
    "BK1136": {"name": "光通信模块", "inflow_yi": 12.4, "change_pct": -0.16, "turnover": 4.72, "strength": None},
}
w.sect_data = dict(PREV)

def _drain():
    out = None
    while True:
        try:
            item = w.q.get_nowait()
        except Exception:
            break
        if item[0] == "stocks":
            out = item[2]
    return out

# 2a. 整次失败(None) → 沿用旧数据
gd.quote_sectors = lambda codes: None
w._stock_worker()
out = _drain()
if out != PREV: fails.append(f"失败轮应沿用旧数据: {out}")

# 2b. 成功但缺 BK1136 → 名称保旧
gd.quote_sectors = lambda codes: {"BK1660": dict(PREV["BK1660"])}
w._stock_worker()
out = _drain()
if out.get("BK1136", {}).get("name") != "光通信模块":
    fails.append(f"偶发缺失未保住旧名称: {out}")

# 2c. 正常成功 → 全量替换（旧数据不残留）
NEW = {"BK1660": {"name": "光纤概念", "inflow_yi": -1.0, "change_pct": 0.1, "turnover": 2.8, "strength": None},
       "BK1136": {"name": "光通信模块", "inflow_yi": 2.0, "change_pct": 0.2, "turnover": 4.7, "strength": None}}
gd.quote_sectors = lambda codes: json.loads(json.dumps(NEW))
w._stock_worker()
out = _drain()
if out != NEW: fails.append(f"正常轮未全量替换: {out}")

# 2d. sectors 清空 → 空字典
gd.quote_sectors = lambda codes: {}
w.conf["sectors"] = []
w._stock_worker()
out = _drain()
if out != {}: fails.append(f"sectors 清空应为空: {out}")

root.destroy()

if fails:
    print("FAIL")
    for f in fails: print(" -", f)
    sys.exit(1)
print("PASS: 板块数据稳定性全部断言通过")
