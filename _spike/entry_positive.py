# -*- coding: utf-8 -*-
"""P1-A spike 阳性对照入口：故意导入 jdjr_query_news。

jdjr_query_news 在第 30 行 `from jdjr_config import ...`，而 jdjr_config.py
含有硬编码的网关 API Key。若打包后能在产物里扫到该凭据，说明扫描方法有效，
则"真实闭包扫不到凭据"的结论才成立（否则只是扫描器失灵造成的假阴性）。

本文件仅用于 spike，不属于交付产物。
"""
import jdjr_query_news

if __name__ == "__main__":
    print("positive control ok:", getattr(jdjr_query_news, "__name__", "?"))
