#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一日志（纯标准库）。

解决的问题（对应安全/质量审查 S6、S7）：
- 静默异常导致故障无痕 → 统一落盘，关键路径可观测；
- 日志无轮转、中文乱码、泄漏本机绝对路径 → 按大小轮转 + 统一 utf-8 + 主目录脱敏。

（注：审查报告里的"47 处 except Exception: pass"是当时的快照。后续分诊结论为：
 配置/取数/轮询/搜索等**关键路径已全部接入 glog**；剩余裸 pass 绝大多数是
 UI 销毁与几何设置，静默是**预期行为**——它们以 1~2s 频率执行，
 若改成 warn 会刷爆日志。这些位置如确有观测需要，用 glog.debug（默认
 INFO 阈值下零开销），不要再逐处改 warn。）

设计要点：
- 路径：默认 ~/.gold_widget.log，可用环境变量 GOLD_WIDGET_LOG 覆盖；
- 轮转：单文件 1MB，保留 3 份备份（.1/.2/.3）；
- 脱敏：把用户主目录替换为 "~"，避免排障时把日志发出去泄漏本机路径；
- 分级：DEBUG/INFO/WARN/ERROR，阈值由 GOLD_WIDGET_LOG_LEVEL 控制（默认 INFO）；
- 冻结模式：--noconsole 下没有控制台，print 全部丢失 → 提供
  redirect_std_streams() 把 stdout/stderr 落到日志（由入口显式调用，
  不在 import 时自动接管，避免污染测试的输出捕获）。

线程安全：写盘与轮转都在模块级锁内完成（浮窗有多条取数线程）。
"""

import os
import sys
import threading
import time
import traceback

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

LOG_PATH = (os.environ.get("GOLD_WIDGET_LOG")
            or os.path.join(os.path.expanduser("~"), ".gold_widget.log"))
MAX_BYTES = 1_000_000          # 单文件上限 1MB
BACKUPS = 3                    # 保留 .1 / .2 / .3
_HOME = os.path.expanduser("~")

try:
    _MIN = _LEVELS.get((os.environ.get("GOLD_WIDGET_LOG_LEVEL") or "INFO").upper(), 20)
except Exception:              # pragma: no cover - 环境变量异常不应影响启动
    _MIN = 20

_lock = threading.Lock()

# 导入时固化的"原始"标准流：回显必须写到这里，绝不能写当前 sys.stderr。
# 原因（实测踩坑）：redirect_std_streams() 会把 sys.stderr 换成 _Tee，而 _Tee
# 的 write 又回调 log()；若 log() 再往 sys.stderr 回显，就形成
#   log → sys.stderr(_Tee) → log → …
# 的无限自激循环，瞬间刷爆日志文件并吃满 CPU（浮窗表现为"启动极慢"）。
_ORIG_STDOUT = sys.stdout
_ORIG_STDERR = sys.stderr
_echo_state = threading.local()


def _echo(line):
    """把日志回显到原始 stderr（有控制台时可见）。带同线程重入护栏。"""
    if getattr(_echo_state, "busy", False):
        return
    s = _ORIG_STDERR
    if s is None:
        return
    _echo_state.busy = True
    try:
        s.write(line)
        s.flush()
    except Exception:
        pass
    finally:
        _echo_state.busy = False



def scrub_paths(s):
    """把本机绝对路径（用户主目录）替换为 ~，降低日志外发时的信息泄漏。"""
    if not s:
        return s
    try:
        return str(s).replace(_HOME, "~")
    except Exception:
        return s


def _rotate_locked():
    """调用方须持有 _lock。超出上限时滚动备份，最多 BACKUPS 份。"""
    try:
        if os.path.getsize(LOG_PATH) < MAX_BYTES:
            return
    except OSError:
        return
    for i in range(BACKUPS - 1, 0, -1):
        src, dst = "%s.%d" % (LOG_PATH, i), "%s.%d" % (LOG_PATH, i + 1)
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except OSError:
                pass
    try:
        os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass


def log(level, msg):
    """写一行日志。任何失败都被吞掉——日志系统本身绝不能拖垮主流程。"""
    if _LEVELS.get(level, 20) < _MIN:
        return
    line = "%s [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level,
                             scrub_paths(msg))
    with _lock:
        try:
            _rotate_locked()
            with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
                f.write(line)
        except Exception:
            pass
    _echo(line)


def debug(m):
    log("DEBUG", m)


def info(m):
    log("INFO", m)


def warn(m):
    log("WARN", m)


def error(m):
    log("ERROR", m)


def exception(m):
    """记录当前异常栈（在 except 块内调用）。"""
    log("ERROR", "%s\n%s" % (m, traceback.format_exc()))


def install_excepthook():
    """未捕获异常（主线程）落盘，避免静默退出后无从排查。"""
    def _hook(exc_type, exc, tb):
        try:
            log("ERROR", "未捕获异常:\n" + "".join(
                traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
    sys.excepthook = _hook


def redirect_std_streams():
    """冻结模式：把 stdout/stderr 接到日志（--noconsole 下 print 无处可去）。

    按行缓冲，只写非空行，避免高频空行刷盘。
    """
    class _Tee:
        def __init__(self, level):
            self._level = level
            self._buf = ""

        def write(self, s):
            try:
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line.strip():
                        log(self._level, line)
            except Exception:
                pass

        def flush(self):
            try:
                if self._buf.strip():
                    log(self._level, self._buf)
                    self._buf = ""
            except Exception:
                pass

        def isatty(self):
            return False

    try:
        sys.stdout = _Tee("INFO")
        sys.stderr = _Tee("WARN")
    except Exception:
        pass
