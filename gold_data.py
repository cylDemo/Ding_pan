#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金盯盘 · 数据层（免登录）

复用已安装 jdgold Skill 的公开数据接口（京东金融），对外只暴露 collect()。
纯标准库，Python 3.9+ 均可运行；被 gold_watch.py（网页看板）与
gold_widget.py（桌面浮窗）共用。
"""

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import glog  # 统一日志（utf-8 / 轮转 / 路径脱敏），替代散落的 print(stderr)

PYTHON = sys.executable
FROZEN = getattr(sys, "frozen", False)  # PyInstaller 打包模式


def _resolve_skill_dir():
    """jdgold 脚本目录解析：打包资源 → 项目 vendor → 本机 skill 目录。"""
    if FROZEN:
        cand = os.path.join(getattr(sys, "_MEIPASS", ""), "jdgold")
        if os.path.isdir(cand):
            return cand
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "jdgold")
    if os.path.isdir(local):
        return local
    return os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "jdgold", "scripts")


SKILL_SCRIPTS = _resolve_skill_dir()

# jdgold skill 的内部脚本依赖：skill 升级/改名会导致金价链路断供，
# 这里显式声明 + 启动检查，缺失时立即抛可定位的错误，而不是静默返回空。
#
# 按需分组：浮窗（gold_widget）只取行情（with_news/with_trend 均为 False），
# 因此打包集只需行情闭包，资讯/走势脚本不再随浮窗分发（精简体积与特征面）。
# 资讯/走势仅网页看板（gold_watch）在用，源码运行时仍会校验。
CORE_SCRIPTS = ("query_price_jhub.py",)
NEWS_SCRIPTS = ("jdjr_query_news.py",)
TREND_SCRIPTS = ("jdjr_query_stock.py",)

# 向后兼容：默认（全量）依赖清单 = 行情 + 资讯 + 走势
REQUIRED_SCRIPTS = CORE_SCRIPTS + NEWS_SCRIPTS + TREND_SCRIPTS


def _script_modname(script_name):
    """jdgold 脚本文件名 → 模块名（query_price_jhub.py → query_price_jhub）。"""
    return os.path.splitext(os.path.basename(str(script_name)))[0]


def _script_available(script_name):
    """判断某 jdgold 脚本在**当前运行形态**下是否可用。

    源码模式：脚本以真实文件存在，subprocess 执行，需校验文件在盘。
    打包模式：脚本以字节码收在 PYZ 内，盘面已无可读 .py，只能校验模块可导入性。
    """
    if FROZEN:
        try:
            return importlib.util.find_spec(_script_modname(script_name)) is not None
        except (ImportError, ValueError, AttributeError):
            return False
    return os.path.isfile(os.path.join(SKILL_SCRIPTS, script_name))


def check_skill(with_news=False, with_trend=False):
    """检查本次调用真正需要的 jdgold 脚本是否齐全，缺失抛 RuntimeError。

    只校验"将要被用到"的脚本：浮窗路径不需要资讯/走势脚本，
    因此精简打包（只含行情闭包）不会因缺 jdjr_query_* 而误报失败。
    """
    need = list(CORE_SCRIPTS)
    if with_news:
        need += NEWS_SCRIPTS
    if with_trend:
        need += TREND_SCRIPTS
    missing = [s for s in need if not _script_available(s)]
    if missing:
        if FROZEN:
            raise RuntimeError(
                "打包资源缺少 jdgold 模块: "
                + ", ".join(_script_modname(s) for s in missing)
                + "。构建期 hiddenimports 未收集到该闭包，请核对 盯盘.spec 的 "
                "pathex/hiddenimports 配置。"
            )
        raise RuntimeError(
            f"jdgold skill 脚本缺失: {', '.join(missing)}"
            f"（期望目录 {SKILL_SCRIPTS}）。"
            "skill 可能已升级或改名，请核对 gold_data.REQUIRED_SCRIPTS 或重装 jdgold。"
        )


# ────────────────────────── 脚本调用 ──────────────────────────

def run_script(args, timeout=90):
    """执行 jdgold 脚本并返回其 stdout。
    源码模式：subprocess 调本机 Python（有超时保护）。
    打包模式：对方机器没有 Python，改为按模块 import 后进程内直调 main()
    （脚本以字节码收在 PYZ 内，脚本自身网络调用均带 timeout）。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if FROZEN:
        return _run_inproc(args)
    try:
        r = subprocess.run(
            [PYTHON] + args,
            cwd=SKILL_SCRIPTS,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, env=env,
        )
        return r.stdout or ""
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        glog.warn(f"run {args} failed: {e}")
        return ""


def _run_inproc(args):
    """打包模式：import 目标模块并直调其 main(argv)，捕获 stdout。

    改造前用 runpy.run_path(script, run_name="__main__")，前提是脚本以 .py
    明文随包分发到 _MEIPASS/jdgold；改为按模块名 import 后直调 main 后，脚本
    以字节码收进 PYZ，盘面不再留可读源码（安全审查 S2 的完整修法）。

    语义等价性：runpy 以 __main__ 执行时，入口脚本的 argparse 读到的就是
    sys.argv[1:]，即本次调用传入的 args[1:]；这里把同一列表显式交给 main(argv)，
    并同步 sys.argv 以覆盖脚本内直接读 sys.argv 的写法。
    """
    import contextlib
    import io
    mod_name = _script_modname(args[0])
    cli_args = [str(a) for a in args[1:]]
    out, err = io.StringIO(), io.StringIO()
    old_argv = sys.argv
    old_path = sys.path[:]
    # 兜底：某些形态（如 vendor 目录随包分发）下模块仍需从盘加载，
    # 保证同目录 import（bff_client/jos/...）可见。
    # 打包模式下 PyInstaller 的冻结导入器优先于路径查找，故此插入无害。
    if SKILL_SCRIPTS and os.path.isdir(SKILL_SCRIPTS):
        sys.path.insert(0, SKILL_SCRIPTS)
    sys.argv = [mod_name] + cli_args
    try:
        # import 必须在 redirect 块内执行：脚本模块级若有 print，
        # 在 GUI 形态（console=False）下真实 stdout 为 None 会直接抛错；
        # 原 runpy.run_path 亦是在 redirect 块内执行，此处保持语义等价。
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            mod = importlib.import_module(mod_name)
            entry = getattr(mod, "main", None)
            if not callable(entry):
                glog.warn(f"inproc {args}: 模块 {mod_name} 无可调用的 main()")
                return ""
            entry(cli_args)
    except SystemExit:
        pass  # 脚本内部 sys.exit(main()) 的正常路径
    except Exception as e:
        glog.warn(f"inproc {args} failed: {e}\n{err.getvalue()}")
    finally:
        sys.argv = old_argv
        sys.path = old_path
    return out.getvalue()


# ────────────────────────── 解析 ──────────────────────────

def _cell_num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", (s or "").replace(",", "").strip())
    return float(m.group()) if m else None


def parse_overview(text):
    """解析「黄金行情速览」Markdown，返回两个分组的结构化行情。"""
    groups, cur = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if re.match(r"^[一二三四]、", line):
            cur = {"title": re.sub(r"^[一二三四]、", "", line).strip(), "rows": []}
            groups.append(cur)
            continue
        if not line.startswith("|") or cur is None:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8 or set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in ("品种", ""):
            continue
        pct_raw = cells[3]
        cur["rows"].append({
            "name": cells[0],
            "price": _cell_num(cells[1]),
            "change": _cell_num(cells[2]),
            "pct": _cell_num(pct_raw),
            "open": _cell_num(cells[4]),
            "prev_close": _cell_num(cells[5]),
            "high": _cell_num(cells[6]),
            "low": _cell_num(cells[7]),
            "up": "🔴" in pct_raw,
            "down": "🟢" in pct_raw,
        })
    return groups


def parse_trend(text):
    """解析近 N 日走势摘要。"""
    if not (text or "").strip():
        return None
    def g(pattern):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None
    verdict = ""
    m = re.search(r"^\s*[^一-龥\w]*([一-龥]{2,8})\s*$", text, re.M)
    if m:
        verdict = m.group(1)
    return {
        "range": g(r"近\d+天走势（([^）]+)）"),
        "verdict": verdict,
        "start": _cell_num(g(r"起始价:\s*([\d.]+)") or ""),
        "end": _cell_num(g(r"收盘价:\s*([\d.]+)") or ""),
        "chg": _cell_num(g(r"累计涨跌:\s*(-?[\d.]+)") or ""),
        "chg_pct": _cell_num(g(r"累计涨跌:.*?\((-?[\d.]+)%\)") or ""),
        "high": _cell_num(g(r"最高:\s*([\d.]+)") or ""),
        "low": _cell_num(g(r"最低:\s*([\d.]+)") or ""),
        "amplitude": _cell_num(g(r"波动幅度:\s*([\d.]+)") or ""),
    }


def parse_news(text):
    try:
        return ((json.loads(text).get("data") or {}).get("news") or [])
    except Exception as e:
        # 资讯 JSON 结构变化会表现为"资讯区突然空了"，静默会掩盖接口改版。
        glog.debug(f"资讯解析失败（结构可能已变更）: {e}")
        return []


# ────────────────────────── A 股搜索 / 行情 ──────────────────────────
# 来源：
#   搜索  → 东财 searchapi.eastmoney.com（公开建议接口）
#   行情  → 腾讯 qt.gtimg.cn（不封 IP，HTTP GBK）
# 这两个零鉴权、零依赖；mootdx 走 TCP 不便在沙箱/受限环境跑，浮窗优先选 HTTP。

import urllib.error
import urllib.parse
import urllib.request


def _http_get(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


# 搜索缓存 + 限频保护：连续输入会每键触发一次请求，东财 suggest 接口
# 突发高频调用会被限流（返回空/超时），表现为“下拉突然消失再也搜不出”。
_search_cache = {}          # kw -> (ts, results)
_search_last_call = 0.0
_SEARCH_MIN_GAP = 0.35      # 两次真实请求最小间隔（秒）
_SEARCH_TTL = 60.0          # 缓存有效期（秒）

# 东财公开搜索接口的默认 token（非机密、无用户身份，公开可见，可随时替换）。
# 提为命名常量的目的：一是避免散落的魔法字符串，二是明确它不属于"密钥"，
# 不随配置分发、不写入日志。
_EM_SUGGEST_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
# 优先 HTTPS（防止公共网络下搜索结果被中间人篡改/投毒），异常时回退 HTTP。
_EM_SUGGEST_HOSTS = ("https://searchapi.eastmoney.com",
                     "http://searchapi.eastmoney.com")


def _suggest_raw(keyword, limit):
    """东财 suggest 原始请求，返回 Data 列表；网络失败抛异常。

    走 HTTPS 优先、HTTP 兜底：该域名实测两种协议均可用，HTTPS 可消除
    明文篡改面（搜索关键词与返回标的均不再暴露在明文信道）。
    """
    q = urllib.parse.quote(keyword)
    last_err = None
    for base in _EM_SUGGEST_HOSTS:
        url = (f"{base}/api/suggest/get?input={q}&type=14"
               f"&token={_EM_SUGGEST_TOKEN}&count={limit}")
        try:
            raw = _http_get(
                url, headers={"Referer": "https://quote.eastmoney.com/"}
            ).read().decode("utf-8")
            return json.loads(raw).get("QuotationCodeTable", {}).get("Data", []) or []
        except Exception as e:
            last_err = e
            if base.startswith("https"):
                glog.warn(f"搜索接口 HTTPS 失败，回退 HTTP: {e}")
            continue
    raise last_err if last_err else RuntimeError("suggest 请求失败")


# 同花顺板块指数（885xxx 行业 / 886xxx 概念）名称缓存：名称长期不变 → 24h
_THS_NAME_TTL = 24 * 3600.0
_ths_name_cache = {}


class _NetUnstable(Exception):
    """THS 网关抖动（502/504 等，重试后仍失败）：区别于"代码不存在"。"""


def _ths_board_name(code):
    """同花顺板块指数代码（如 886084）→ 板块名称（如 光纤概念）。
    数据源 d.10jqka.com.cn v4 last.js（免 cookie，JSONP 顶层 name 字段）。
    返回 None = 确认无此代码（404）；THS 网关抖动重试后仍失败 → 抛 _NetUnstable，
    上层据此触发搜索自动重试，而不是把抖动误判成"无匹配"（已实测该接口
    时好时坏：886084 上一分钟能取到名称，下一分钟就 502）。"""
    code = str(code).strip()
    if not re.fullmatch(r"88[56]\d{3}", code):
        return None
    hit = _ths_name_cache.get(code)
    if hit and time.time() - hit[0] < _THS_NAME_TTL:
        return hit[1]
    url = f"https://d.10jqka.com.cn/v4/line/48_{code}/01/last.js"
    headers = {"Referer": "https://q.10jqka.com.cn/", "User-Agent": "Mozilla/5.0"}
    name = None
    last_err = None
    for attempt in range(3):  # 退避重试：0 / 0.8 / 1.6s
        try:
            raw = _http_get(url, headers=headers).read().decode("gbk", "ignore")
            payload = raw[raw.index("(") + 1: raw.rindex(")")]
            # name 在 JSONP 顶层（实测：{"rt":..., "name":"光纤概念", ...}）
            name = ((json.loads(payload) or {}).get("name") or "").strip() or None
            last_err = None
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # THS 无此代码，确定无匹配
            last_err = e
        except Exception as e:
            last_err = e
        if attempt < 2:
            time.sleep(0.8 * (attempt + 1))
    if last_err is not None:
        # last.js 网关抖动（502/504，可持续数分钟）→ 概念列表页兜底：
        # q.10jqka.com.cn/gn/ 页面内嵌全量板块 JSON（platecode+platename），
        # 该页面与行情网关独立、长期稳定（实测 292 条全覆盖）。
        m = _ths_board_map()
        if m is None:
            raise _NetUnstable(str(last_err))
        return m.get(code)
    if name:
        _ths_name_cache[code] = (time.time(), name)
    return name


# 概念列表页全量映射缓存：code -> (ts, {885/886: 名称})
_ths_map_cache = {"ts": 0.0, "map": None}


def _ths_board_map():
    """同花顺 885/886 板块指数代码 → 名称 全量映射（q.10jqka.com.cn/gn/ 页内嵌 JSON）。
    返回 None = 抓取失败（调用方据此判定网络不稳）；成功结果缓存 24h。"""
    now = time.time()
    if _ths_map_cache["map"] is not None and now - _ths_map_cache["ts"] < _THS_NAME_TTL:
        return _ths_map_cache["map"]
    try:
        raw = _http_get("https://q.10jqka.com.cn/gn/",
                        headers={"User-Agent": "Mozilla/5.0"}).read().decode("gbk", "ignore")
        pairs = re.findall(
            r'"platecode"\s*:\s*"(88[56]\d{3})"\s*,\s*"platename"\s*:\s*"([^"]+)"', raw)
        if not pairs:
            return _ths_map_cache["map"]
        m = {}
        for code, nm in pairs:
            # platename 是 \uXXXX 转义，借 json 字符串解码为中文
            try:
                nm = json.loads(f'"{nm}"')
            except Exception:
                pass
            if nm.strip():
                m[code] = nm.strip()
        if m:
            _ths_map_cache["ts"] = now
            _ths_map_cache["map"] = m
        return _ths_map_cache["map"]
    except Exception as e:
        # 抓取失败 → 沿用旧缓存（可能为 None，由调用方判定网络不稳）。
        # 留痕是为了能区分"接口挂了"与"解析规则失效"。
        glog.debug(f"板块名称映射抓取失败，沿用缓存: {e}")
        return _ths_map_cache["map"]


def search_stock(keyword, limit=8):
    """按名称或代码搜索 A 股，返回 [{code, name, market}]。
    market: 'sh' / 'sz' / 'bj'。
    返回 [] = 确实无匹配；返回 None = 网络失败（调用方应保留旧结果重试）。
    空关键词返回 []。"""
    global _search_last_call
    kw = (keyword or "").strip()
    if not kw:
        return []
    now = time.time()
    hit = _search_cache.get(kw)
    if hit and now - hit[0] < _SEARCH_TTL:
        return hit[1]
    gap = now - _search_last_call
    if gap < _SEARCH_MIN_GAP:
        time.sleep(_SEARCH_MIN_GAP - gap)
    _search_last_call = time.time()
    try:
        items = _suggest_raw(kw, limit)
    except Exception as e:
        glog.warn(f"search_stock 失败: {e}")
        return None

    out = []
    for it in items:
        code = (it.get("Code") or "").strip()
        name = (it.get("Name") or "").strip()
        # 东财返回里 SecurityType / MarketType 不可靠，直接按代码前缀判断市场
        if code.startswith(("5", "6", "9")):
            market = "sh"
        elif code.startswith(("0", "1", "2", "3")):
            market = "sz"
        elif code.startswith(("4", "8")):
            market = "bj"
        else:
            market = ""
        if code and name:
            # 东财板块/概念代码固定以 BK 开头（如 BK1660 光纤概念）——
            # 打上 sector 标记，UI 层据此把添加动作分流到板块区而非股票区。
            out.append({"code": code, "name": name, "market": market,
                        "sector": code.startswith("BK")})
    if not out:
        # 兜底：同花顺板块指数代码（885xxx/886xxx，如 886084 光纤概念）。
        # 东财 suggest 不认识这个体系的代码 → 用同花顺公开行情接口把代码
        # 翻译成板块名称，再按名称走 suggest 定位到东财对应 BK 板块。
        out = _ths_board_bridge(kw, limit)
        if out is None:
            # THS 网关抖动：返回 None 触发 UI 保留旧结果并自动重试，
            # 绝不能缓存成"无匹配"（否则抖动窗口内重搜也白搭）。
            return None
    _search_cache[kw] = (time.time(), out)
    return out


def _ths_board_bridge(kw, limit):
    """同花顺板块指数代码桥接：886084 → THS 名称「光纤概念」→ suggest → BK1660。
    返回 [] = 确认无匹配（非 885/886 代码、THS 无此代码、名称未匹配到板块）；
    返回 None = THS 网关抖动（调用方应返回 None 触发重试）。
    名称到东财板块的 suggest 查询失败按无匹配处理（上游 suggest 已成功）。"""
    try:
        name = _ths_board_name(kw)
    except _NetUnstable:
        return None
    if not name:
        return []
    # 名称逐级放宽搜索：THS 与东财概念体系不对齐时精确名可能搜不到。
    # 候选结果的板块名必须与 THS 名核心词有包含关系才接受（如「光纤」
    # ⊆「光纤概念」）；否则宁可不匹配——「兵装重组」绝不能错配成「重组蛋白」。
    base = _name_candidates(name)[0]
    for cand in _name_candidates(name):
        for it in _suggest_bk(cand, limit):
            b = it["name"]
            if base in b or b in base:
                return [it]
    return []


def _name_candidates(name):
    """名称 → 逐级放宽的搜索候选：原名 → 去掉「概念/指数/板块」后缀 →
    再依次去掉头部单字（保留 ≥2 字），最多 4 个候选。"""
    seen, cands = set(), []

    def add(x):
        x = x.strip()
        if len(x) >= 2 and x not in seen:
            seen.add(x)
            cands.append(x)

    cur = name
    for suf in ("概念", "指数", "板块"):
        if cur.endswith(suf):
            cur = cur[: -len(suf)]
    add(cur)
    while len(cur) > 2 and len(cands) < 4:
        cur = cur[1:]
        add(cur)
    return cands


def _suggest_bk(keyword, limit):
    """suggest 搜名称并只保留 BK 板块结果，返回 [{code,name,market,sector,src}]。"""
    try:
        items = _suggest_raw(keyword, limit)
    except Exception as e:
        glog.warn(f"板块桥接 suggest 失败: {e}")
        return []
    for it in items:
        code = (it.get("Code") or "").strip()
        bname = (it.get("Name") or "").strip()
        if code.startswith("BK") and code and bname:
            return [{"code": code, "name": bname, "market": "", "sector": True}]
    return []


def quote_stocks(codes):
    """批量拉取腾讯行情。codes: ["601069", "002738", ...]
    返回: {code: {name, price, change_pct, amount_yi, turnover, last_close}}，查不到的 code 不在结果里。
    amount_yi 单位为「亿元」。
    """
    if not codes:
        return {}
    # 市场前缀：5/6/9 → sh；0/1/2/3 → sz；4/8 → bj
    prefixed = []
    for c in codes:
        c = str(c).strip()
        if not c:
            continue
        if c.startswith(("5", "6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith(("0", "1", "2", "3")):
            prefixed.append(f"sz{c}")
        elif c.startswith(("4", "8")):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sh{c}")
    if not prefixed:
        return {}
    try:
        raw = _http_get(f"https://qt.gtimg.cn/q={','.join(prefixed)}").read().decode("gbk")
    except Exception as e:
        glog.warn(f"quote_stocks 失败: {e}")
        return {}

    out = {}
    for line in raw.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=")[0].split("_")[-1]
            v = line.split('"')[1].split("~")
            if len(v) < 39:
                continue
            code = key[2:]
            price = float(v[3]) if v[3] else None
            last_close = float(v[4]) if v[4] else None
            change_pct = float(v[32]) if v[32] else None
            # 字段 37 是成交额(万)，转亿元
            amount_wan = float(v[37]) if v[37] else None
            amount_yi = round(amount_wan / 10000.0, 2) if amount_wan is not None else None
            # 字段 38 是换手率(%)
            turnover = float(v[38]) if v[38] else None
            out[code] = {
                "name": v[1],
                "price": price,
                "last_close": last_close,
                "change_pct": change_pct,
                "amount_yi": amount_yi,
                "turnover": turnover,
                "time": v[30] if len(v) > 30 else "",  # yyyyMMddHHmmss
            }
        except (ValueError, IndexError):
            continue
    return out


def quote_sectors(codes):
    """东财板块行情（免登录公开接口）。

    返回: {code(大写 BKxxxx): {name, inflow_yi, change_pct, turnover, strength}}。
    inflow_yi = 主力净流入（亿元，正流入/负流出）；strength = 概念强度排名
    （该板块今日涨幅在全部东财行业+概念板块中的名次，1=最强；拉不到排名时为
    None，UI 显示 "---"）。查不到的 code 不在结果里。
    网络不稳（重试 3 次仍失败/响应不可解析）时返回 None —— 区别于"成功但无数据"
    的 {}，调用方可据此沿用上一轮数据，避免一轮抖动把整个板块区打回 "---"。
    """
    if not codes:
        return {}
    secids = ",".join("90." + str(c).strip().upper() for c in codes if str(c).strip())
    if not secids:
        return {}
    url_path = ("/api/qt/ulist.np/get?secids=" + secids
                + "&fields=f3,f8,f12,f14,f62&fltt=2")
    try:
        data = _em_json(url_path)   # 主站 → push2delay 镜像，双主机各重试 2 次
    except Exception as e:
        glog.warn(f"quote_sectors 重试后仍失败: {e}")
        return None

    def _num(v):
        return v if isinstance(v, (int, float)) else None

    out = {}
    for d in (data.get("data") or {}).get("diff") or []:
        code = str(d.get("f12", "")).upper()
        if not code:
            continue
        inflow = _num(d.get("f62"))
        out[code] = {
            "name": d.get("f14") or code,
            "inflow_yi": round(inflow / 1e8, 2) if inflow is not None else None,
            "change_pct": _num(d.get("f3")),
            "turnover": _num(d.get("f8")),
            "strength": None,
        }
    rank = _em_strength_rank()  # 失败返回 {} → strength 保持 None("---")
    for code, v in out.items():
        v["strength"] = rank.get(code)
    return out


# ── 概念强度（全市场板块涨幅排名）──
# 口径：该板块今日涨幅在全部东财行业+概念板块（不含地域）中的名次，1=最强。
# 实测：push2 主站 clist 列表接口在本机网络下握手即断，但 push2delay 镜像
# 稳定（pz 上限 100，约 7 页）；全量行情走 ulist.np 批量（~600 个板块分 2 批，
# 单批 <0.5s）。主站/镜像双主机兜底，主站不通时自动切镜像（排名用延迟行情
# 足够）。板块代码列表长期稳定 → 24h 缓存；排名盘面变化平缓 → 60s 缓存。
_EM_BOARD_TTL = 24 * 3600.0
_EM_RANK_TTL = 60.0
_em_board_cache = {"ts": 0.0, "codes": []}
_em_rank_cache = {"ts": 0.0, "rank": {}}
_EM_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")


def _em_json(path_qs):
    """东财行情 GET：主站 → push2delay 镜像双主机兜底，各重试 2 次。
    全部失败抛最后一个异常。"""
    last = None
    for host in _EM_HOSTS:
        url = f"https://{host}{path_qs}"
        for attempt in range(2):
            try:
                raw = _http_get(url, headers={"Referer": "http://quote.eastmoney.com/"},
                                timeout=8).read().decode("utf-8")
                return json.loads(raw)
            except Exception as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
    raise last


def _em_board_codes():
    """全部东财行业+概念板块 BK 代码（push2delay 分页），24h 缓存。
    失败时沿用旧缓存（可能为空）；空列表表示本轮无排名可用。"""
    c = _em_board_cache
    if c["codes"] and time.time() - c["ts"] < _EM_BOARD_TTL:
        return c["codes"]
    codes = []
    try:
        for fs in ("m:90+t:2", "m:90+t:3"):   # 行业 / 概念（地域 t:1 不参与排名）
            for pn in range(1, 16):
                raw = _http_get("https://push2delay.eastmoney.com/api/qt/clist/get"
                                f"?pn={pn}&pz=100&fs={fs}&fields=f12&fltt=2",
                                headers={"Referer": "http://quote.eastmoney.com/"},
                                timeout=8).read().decode("utf-8")
                diff = (json.loads(raw).get("data") or {}).get("diff") or []
                if isinstance(diff, dict):
                    diff = list(diff.values())
                if not diff:
                    break
                codes += [str(x.get("f12", "")) for x in diff]
    except Exception as e:
        glog.warn(f"板块列表拉取失败: {e}")
        return c["codes"]
    codes = sorted(set(x for x in codes if x.startswith("BK")))
    if codes:
        c["codes"], c["ts"] = codes, time.time()
    return codes


def _em_strength_rank():
    """全部板块按今日涨幅排名 {BKxxxx: 名次(1=最强)}；60s 缓存。
    网络失败沿用旧缓存；从未成功过返回 {}（UI 对应板块显示 "---"）。"""
    c = _em_rank_cache
    if c["rank"] and time.time() - c["ts"] < _EM_RANK_TTL:
        return c["rank"]
    codes = _em_board_codes()
    if not codes:
        return {}
    pct = {}
    try:
        for i in range(0, len(codes), 300):   # 分批防 URL 过长
            batch = codes[i:i + 300]
            secids = ",".join("90." + x for x in batch)
            data = _em_json("/api/qt/ulist.np/get?secids=" + secids
                            + "&fields=f3,f12&fltt=2")
            diff = (data.get("data") or {}).get("diff") or []
            if isinstance(diff, dict):
                diff = list(diff.values())
            for x in diff:
                v = x.get("f3")
                if isinstance(v, (int, float)):
                    pct[str(x.get("f12", ""))] = float(v)
    except Exception as e:
        glog.warn(f"概念强度排名拉取失败: {e}")
        return c["rank"]
    rank = {code: n for n, code in enumerate(
        sorted(pct, key=lambda k: -pct[k]), 1)}
    if rank:
        c["rank"], c["ts"] = rank, time.time()
    return rank


# ────────────────────────── 聚合 ──────────────────────────

def pick(rows, keyword):
    for r in rows:
        if keyword in r["name"]:
            return r
    return None


class QuotaError(RuntimeError):
    """京东开放平台当日调用配额用尽（次日自动重置）。
    与网络抖动不同：继续高频重试只会白白烧掉恢复后的新配额，
    调用方应显著放慢节奏（≥5 分钟/次），UI 需给出明确提示。"""


def collect(with_news=True, with_trend=True):
    """拉取一份完整快照。行情为必需项，资讯/走势失败不影响主流程。"""
    check_skill(with_news=with_news, with_trend=with_trend)
    raw = run_script(["query_price_jhub.py", "--overview"])
    if "频次超出" in raw or "调用频次" in raw:
        raise QuotaError("京东接口当日调用配额已用尽，次日 0 点自动恢复")
    groups = parse_overview(raw)
    if not groups:
        raise RuntimeError("行情数据为空，接口可能暂不可用")

    spot, accum = (groups[0], groups[1]) if len(groups) >= 2 else (groups[0], {"title": "积存金", "rows": []})

    news, trend = [], None
    if with_news:
        news = parse_news(run_script(["jdjr_query_news.py", "黄金", "8"]))
    if with_trend:
        trend = parse_trend(run_script(["jdjr_query_stock.py", "chart", "SGE-Au99.99", "--days", "10"]))

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main": pick(spot["rows"], "京东24h") or (spot["rows"][0] if spot["rows"] else None),
        "spot": spot,
        "accum": accum,
        "trend": trend,
        "news": news,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
