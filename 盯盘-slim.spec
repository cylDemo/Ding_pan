# -*- mode: python ; coding: utf-8 -*-
"""瘦身版构建配置（对照实验，不替换 盯盘.spec）。

与现状的差异：
1. datas 只打包浮窗真正用到的 4 个脚本（依赖闭包：query_price_jhub → jos → bff_client/secure_store），
   不再整目录塞入 21 个脚本 —— 移除 jdjr_config.py（内含硬编码网关 API Key）、
   autotrade.launchd.plist（macOS 自启模板）、sim_autotrade.py（自动交易）、3 个 .pyc。
2. upx=False 显式关闭（原 spec 写 upx=True，但构建机无 upx，实为静默跳过；
   显式关掉可避免"哪天装了 upx 反而拉高误报"的隐患）。
3. excludes 排除确认未使用的重量级标准库，压缩体积与导入表面积。
4. 新增版本信息资源（version_info.txt）——商业杀软对无元数据的裸 exe 评分更差。

用法：
  .build_venv\\Scripts\\pyinstaller.exe 盯盘-slim.spec --noconfirm --distpath dist_slim --workpath build_slim
"""
import os

SK = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "jdgold", "scripts")
# 浮窗最小依赖闭包（A股/板块走腾讯+东财，不经此目录）
KEEP = ["query_price_jhub.py", "jos.py", "bff_client.py", "secure_store.py"]

a = Analysis(
    ['gold_widget.py'],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(SK, f), 'jdgold') for f in KEEP],
    hiddenimports=['secrets', 'base64', 'hashlib', 'socket', 'webbrowser', 'signal',
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
    name='盯盘-slim',
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
)
