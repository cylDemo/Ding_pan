# -*- mode: python ; coding: utf-8 -*-
"""盯盘 浮窗 · onedir 构建配置（v2.0.1，推荐交付形态）。

背景（实测）：onefile 形态下每次启动都要把 ~990 个文件 / 25.7MB 释放到
%TEMP%\_MEIxxxxxx，实测冷启动解压 ≈8.6s（且杀软还会逐个实时扫描放大），
异常退出还会残留目录。onedir 形态只需在安装时铺一次文件，之后启动
直接读盘，冷启动 <1s。

用法：
  .build_venv\\Scripts\\pyinstaller.exe 盯盘-onedir.spec --noconfirm --distpath dist_onedir --workpath build_onedir
产出：
  dist_onedir\\盯盘\\盯盘.exe  +  dist_onedir\\盯盘\\_internal\\...

P1-A（v2.0.1）：jdgold 依赖闭包不再以 .py 明文随包分发，改为经
pathex + hiddenimports 收进 PYZ（字节码）；运行时 gold_data 用
importlib.import_module + 直调 main(argv) 调用。盘面不再有可读源码。
"""
import os

SPEC_DIR = SPECPATH
ICON = os.path.join(SPEC_DIR, "盯盘.ico")
VERSION_FILE = os.path.join(SPEC_DIR, "version_info.txt")

SKILL_DIR = os.environ.get("JDGOLD_SCRIPTS") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "jdgold", "scripts")
if not os.path.isdir(SKILL_DIR):
    raise SystemExit("找不到 jdgold 脚本目录: %s\n可用环境变量 JDGOLD_SCRIPTS 指定。" % SKILL_DIR)

# 构建期存在性校验（闭包本体由 hiddenimports + PYZ 承载，不再 datas）
CLOSURE = ["query_price_jhub.py", "jos.py", "bff_client.py", "secure_store.py"]
_missing = [f for f in CLOSURE if not os.path.isfile(os.path.join(SKILL_DIR, f))]
if _missing:
    raise SystemExit("jdgold 依赖闭包缺少文件: %s" % ", ".join(_missing))

a = Analysis(
    ['gold_widget.py'],
    # SKILL_DIR 进 pathex，PyInstaller 才能解析到 hiddenimports 里的 query_price_jhub
    pathex=[SPEC_DIR, SKILL_DIR],
    binaries=[],
    # P1-A：闭包改为经 hiddenimports 收进 PYZ，不再以明文 .py 随包分发
    datas=[],
    hiddenimports=['query_price_jhub',   # P1-A：运行期动态 import，必须显式声明
                   # Tier 0.2 拆出的三个纯逻辑模块（同 盯盘.spec 说明）
                   'gold_theme', 'gold_config', 'gold_util',
                   'secrets', 'base64', 'hashlib', 'socket', 'webbrowser', 'signal',
                   'http.server', 'subprocess', 'datetime', 'typing', 'argparse'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'test', 'tests', 'unittest', 'doctest', 'pydoc', 'lib2to3', 'idlelib',
        'ensurepip', 'venv', 'distutils', 'setuptools', 'pip', 'pkg_resources',
        'sqlite3', 'asyncio', 'concurrent', 'multiprocessing', 'xml', 'xmlrpc',
        'pdb', 'difflib', 'curses', 'numpy', 'pandas', 'matplotlib', 'PIL',
        'scipy', 'requests', 'bs4', 'lxml',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='盯盘',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='盯盘',
)
