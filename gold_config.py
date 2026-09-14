# -*- coding: utf-8 -*-
"""盯盘 · 配置读写（持久化层）。

从 gold_widget.py 迁出（Tier 0.2）。本模块只做"路径 → 数据"的纯持久化，
不持有窗口状态、不依赖 Tk，因此可以脱开 GUI 单测。

与迁出前的差异（唯一一处，属缺陷修复，非等价重构）：
  原 `load_conf` 在外层 `except Exception as e` 内又写了内层
  `except Exception as e`。Python 3 对内层绑定名做**隐式 del**，会把外层名
  一并删除——于是"损坏配置且改名失败"这条路径上，末尾的
  `glog.error(f"...: {e}")` 会抛 NameError，把"配置损坏"升级成"程序起不来"。
  现内层改名 `as _rename_err` 并在修复后仍按原语义记录。
  触发条件：配置文件损坏 **且** `.corrupt` 改名失败（占用/权限），
  到达概率低但正是用户最需要兜底的时刻。
"""

import json
import os
import tempfile
import time

import glog
from gold_theme import THEMES

# 默认配置落用户主目录（~/.gold_widget.json）。
# 调用方（gold_widget）仍持有自己的 CONF_PATH 并显式传入——保留该间接层，
# 使"改 CONF_PATH 指向临时文件"的测试手法继续有效。
DEFAULT_CONF_PATH = os.path.join(os.path.expanduser("~"), ".gold_widget.json")


def atomic_write_json(path, obj):
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


def load_conf(path):
    """读取并归一化配置。

    返回 `(conf, error)`：error 为 None 表示无损坏提示，否则是给 UI 一次性
    展示的文案（不持久化）。**归一化规则与迁出前逐条一致**：
      · 根节点非 JSON 对象 → 视为损坏；
      · theme 非法 → 回退 light；
      · gold_collapsed 强制 bool；
      · watchlist 去重保序（原样字符串）；sectors 去重保序（转大写）；
      · 首次启动 / 老用户升级（缺 watchlist 或 sectors）→ 立即回写默认值。
    """
    d = {"x": None, "y": None, "mini": True, "alpha": 0.97, "topmost": True,
         "theme": "light", "watchlist": ["601069", "002738", "600487"],
         "sectors": ["BK1136", "BK1617"],  # 光通信模块 / 黄金（东财板块代码）
         "gold_collapsed": False}
    err = None
    raw = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("配置根节点不是 JSON 对象")
            d.update(raw)
        except Exception as e:
            # 损坏绝不静默重置（否则用户只会觉得"我的股票莫名没了"）：
            # 备份原文件保留证据 + 落日志 + 由 UI 一次性告知。
            raw = {}
            bak = path + ".corrupt"
            if os.path.exists(bak):
                bak = "%s.%d" % (path + ".corrupt", int(time.time()))
            try:
                os.replace(path, bak)
            except Exception as _rename_err:
                # 备份改名失败（占用/权限）：原文件留在原处，下次启动仍会解析失败 →
                # 必须留痕，否则用户会反复"自选股莫名消失"却查不到原因。
                # 注：内层绑定名不得复写成 e——见模块 docstring 的缺陷说明。
                bak = ""
                glog.warn(f"损坏配置备份失败（原文件保留在原处）: {_rename_err}")
            err = ("配置文件损坏，已重置为默认"
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
            atomic_write_json(path, d)
        except Exception as e:
            glog.warn(f"首次配置写入失败: {e}")
    return d, err


def save_conf(path, c):
    try:
        atomic_write_json(path, c)
    except Exception as e:
        glog.error(f"配置写入失败: {e}")
