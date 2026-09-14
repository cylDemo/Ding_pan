# -*- mode: python ; coding: utf-8 -*-
"""盯盘 浮窗 · 生产构建配置（v2.0.1，onefile 兼容版）。

用法：
  .build_venv\\Scripts\\pyinstaller.exe 盯盘.spec --noconfirm --distpath . --workpath build

相对旧配置（留档于 盯盘-legacy.spec）的关键差异：
1. jdgold 依赖闭包不再以 .py 明文随包分发（P1-A 完整修法）。
   旧做法：datas 打包 4 个脚本到 _MEIPASS/jdgold，运行时
           runpy.run_path(script, run_name="__main__") 执行；
           缺点是用户解包即可读到脚本源码。
   新做法：闭包经 pathex + hiddenimports 收进 PYZ（字节码），运行时
           importlib.import_module + 直调 main(argv)。盘面无源码。
   已移除项及原因：
     · jdjr_config.py          —— 内含硬编码第三方网关 API Key（凭据随包分发）
     · autotrade.launchd.plist —— macOS 自启模板，Windows 完全无用，且是"持久化"杀软特征
     · sim_autotrade.py        —— 自动交易托管（合规风险 + 杀软特征）
     · 其余未用脚本与全部 .pyc
   注：jos.py 在函数体内 import holdings_entry / query_news_flash 等，PyInstaller
       的字节码分析会连带收集，实测闭包 9 个模块、**到 jdjr_config 零路径**
       （已用阳性对照产物验证：故意引入 jdjr_config 时 clawx_def 必然出现，而
       真实闭包的 clawx_def 计数为 0）。
2. upx=False 显式关闭（旧配 upx=True 只因构建机没装 upx 才未生效；
   显式关闭可避免"哪天装了 upx 反而把误报拉高"）。
3. excludes 排除确认未使用的重量级标准库，压缩体积与导入表面积。
4. 注入 version_info.txt + 应用图标，补齐 PE 元数据（云查杀信誉评分关键项）。
5. 不再写死作者本机绝对路径：skill 目录优先取环境变量 JDGOLD_SCRIPTS。
"""
import os

SPEC_DIR = SPECPATH  # PyInstaller 注入：spec 所在目录
ICON = os.path.join(SPEC_DIR, "盯盘.ico")
VERSION_FILE = os.path.join(SPEC_DIR, "version_info.txt")

# jdgold 脚本目录：优先环境变量，缺省取当前用户的标准安装位置（不写死用户名）
SKILL_DIR = os.environ.get("JDGOLD_SCRIPTS") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "jdgold", "scripts")
if not os.path.isdir(SKILL_DIR):
    raise SystemExit("找不到 jdgold 脚本目录: %s\n可用环境变量 JDGOLD_SCRIPTS 指定。" % SKILL_DIR)

# 浮窗最小依赖闭包（A股/板块走腾讯 + 东财，不经过本目录）：
# query_price_jhub → jos → bff_client / secure_store
# 这里只做**构建期存在性校验**，闭包本体由 hiddenimports + PYZ 承载（不再 datas）。
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
    a.binaries,
    a.datas,
    [],
    name='盯盘',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION_FILE,
)
