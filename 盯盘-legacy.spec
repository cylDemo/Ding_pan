# -*- mode: python ; coding: utf-8 -*-
# 旧版构建配置留档（v1，onefile + 整目录打包 jdgold 21 个脚本 + upx=True + 无元数据）。
# 仅用于回滚对照，不要用于新发布。现行配置见 盯盘.spec。
# 已知问题：整目录打包导致 jdjr_config.py（API Key）/ autotrade.launchd.plist /
# sim_autotrade.py 随包分发，是杀软误报与凭据扩散的直接来源。


a = Analysis(
    ['gold_widget.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/Admin/.workbuddy/skills/jdgold/scripts', 'jdgold')],
    hiddenimports=['secrets', 'base64', 'hashlib', 'hmac', 'socket', 'webbrowser', 'signal', 'http.server', 'subprocess', 'datetime', 'typing', 'argparse'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
