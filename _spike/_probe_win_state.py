# -*- coding: utf-8 -*-
"""枚举本机顶层窗口，定位浮窗进程并输出其真实窗口状态。

为什么要写这个脚本（而不是用 PowerShell 一行命令）：
本环境的命令文本里**手写中文会被编码破坏**（项目已知陷阱），用
`Get-Process | Where-Object { $_.ProcessName -match '盯盘' }` 可能一个都匹配不到，
从而得出"进程已退出"的错误结论。本脚本把中文写进 .py 文件（UTF-8 安全），
命令行只传纯 ASCII 参数。

输出同时写到 _spike/_win_state.txt（UTF-8），便于用 Read 工具无损查看。

用法：
  <py312>\\python.exe _spike\\_probe_win_state.py
"""
import ctypes
import os
import sys
from ctypes import wintypes

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

u32.EnumWindows.argtypes = [
    ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = ctypes.c_long
u32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u32.GetWindow.restype = wintypes.HWND
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

TARGET_EXE = "\u76ef\u76d8.exe"          # 盯盘.exe（避免源码里的中文被显示编码破坏）
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_VISIBLE = 0x10000000
WS_MINIMIZE = 0x20000000
WS_MINIMIZEBOX = 0x00020000
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_win_state.txt")
lines = []


def say(msg=""):
    lines.append(msg)


def exe_of(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(2048)
        size = wintypes.DWORD(2048)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def text_of(hwnd, fn):
    buf = ctypes.create_unicode_buffer(512)
    fn(hwnd, buf, 512)
    return buf.value


def style_flags(style, exstyle):
    f = []
    if style & WS_VISIBLE:
        f.append("VISIBLE")
    if style & WS_MINIMIZE:
        f.append("WS_MINIMIZE")
    if style & WS_MINIMIZEBOX:
        f.append("MINIMIZEBOX")
    if style & WS_CAPTION:
        f.append("CAPTION")
    if exstyle & WS_EX_TOOLWINDOW:
        f.append("EX_TOOLWINDOW")
    if exstyle & WS_EX_APPWINDOW:
        f.append("EX_APPWINDOW")
    return ",".join(f) or "-"


found = []


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def cb(hwnd, lparam):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    p = exe_of(pid.value)
    if not p or os.path.basename(p).lower() != TARGET_EXE.lower():
        return True
    style = u32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    exstyle = u32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    owner = u32.GetWindow(hwnd, 4)      # GW_OWNER
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    # Windows 任务栏是否显示该窗口的判定（Taskbar 的实际规则）：
    #   非 TOOLWINDOW  且  (无 owner 或 有 APPWINDOW)
    on_taskbar = (not (exstyle & WS_EX_TOOLWINDOW)) and (
        not owner or bool(exstyle & WS_EX_APPWINDOW))
    found.append({
        "pid": pid.value, "hwnd": hwnd, "cls": text_of(hwnd, u32.GetClassNameW),
        "title": text_of(hwnd, u32.GetWindowTextW),
        "visible": bool(u32.IsWindowVisible(hwnd)), "iconic": bool(u32.IsIconic(hwnd)),
        "style": style, "exstyle": exstyle, "owner": owner,
        "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top),
        "on_taskbar": on_taskbar, "exe": p,
    })
    return True


say("=" * 74)
say("浮窗窗口状态探测（进程镜像名 = %s）" % TARGET_EXE)
say("=" * 74)
u32.EnumWindows(cb, 0)

if not found:
    say("未发现属于该 exe 的顶层窗口。")
    say("")
    say("可能原因：")
    say("  a) 进程确实已退出")
    say("  b) 进程仍在，但窗口被 withdraw() 彻底移除（Tk 会销毁其顶层窗口）")
    say("先看下面进程级判定。")
else:
    for w in found:
        say("")
        say("PID %d   HWND 0x%08X" % (w["pid"], w["hwnd"]))
        say("  类名/标题 : %s / %r" % (w["cls"], w["title"]))
        say("  exe       : %s" % w["exe"])
        say("  visible=%s  iconic=%s  owner=0x%X"
            % (w["visible"], w["iconic"], w["owner"] or 0))
        say("  style     : 0x%08X  [%s]" % (w["style"], style_flags(w["style"], w["exstyle"])))
        say("  exstyle   : 0x%08X" % w["exstyle"])
        say("  位置/尺寸 : x=%d y=%d w=%d h=%d" % w["rect"])
        say("  ★ 会被任务栏显示: %s" % w["on_taskbar"])

# 进程级判定：搜所有进程的镜像名（不依赖命令行中文）
say("")
say("-" * 74)
say("进程扫描（按镜像名匹配，遍历全部进程，不依赖命令行传参）")
say("-" * 74)
TH32 = 0x2
snap = k32.CreateToolhelp32Snapshot(TH32, 0)
hit = 0


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


pe = PROCESSENTRY32W()
pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
ok = k32.Process32FirstW(snap, ctypes.byref(pe))
while ok:
    if pe.szExeFile.lower() == TARGET_EXE.lower():
        hit += 1
        say("  进程存在: PID=%d  名称=%s" % (pe.th32ProcessID, pe.szExeFile))
        say("           路径=%s" % (exe_of(pe.th32ProcessID) or "(读不到)"))
    ok = k32.Process32NextW(snap, ctypes.byref(pe))
k32.CloseHandle(snap)
if hit == 0:
    say("  未发现该进程 → 进程确实已退出（不是被隐藏）")

say("")
say("结论汇总：窗口数=%d  进程数=%d" % (len(found), hit))

body = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(body + "\n")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
print(body)
