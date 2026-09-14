# -*- coding: utf-8 -*-
"""P1-A spike 入口：只做一件事——静态导入 jdgold 的行情脚本。

目的：让 PyInstaller 以「分析(=PYZ 内置)」方式收集 query_price_jhub，
从而暴露它真正的导入闭包，用于判定 jdjr_config（含硬编码网关 Key）
是否会被连带收进产物。

注意：本文件仅用于 spike，不属于交付产物。
"""
import query_price_jhub

if __name__ == "__main__":
    # 不真正发起网络请求，只保证模块被分析到
    print("spike ok:", getattr(query_price_jhub, "__name__", "?"))
