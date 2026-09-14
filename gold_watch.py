#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金盯盘 · 网页看板服务（免登录）

数据由 gold_data.collect() 提供（京东金融公开接口），全程无需登录京东账号。
启动后访问 http://127.0.0.1:8848
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gold_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.getenv("GOLD_WATCH_PORT", "8848"))
REFRESH_SEC = 45

_lock = threading.Lock()
_cache = {"updated_at": "", "data": None, "error": ""}


def refresh():
    t0 = time.monotonic()
    try:
        data = gold_data.collect()
        with _lock:
            _cache["data"] = data
            _cache["updated_at"] = data["updated_at"]
            _cache["error"] = ""
        print(f"[ok] 数据已更新 {data['updated_at']}", flush=True)
    except Exception as e:
        with _lock:
            _cache["error"] = str(e)
        print(f"[error] 刷新失败: {e}", file=sys.stderr, flush=True)
    finally:
        # 固定节拍：扣除本轮耗时再排下一跳，collect 卡顿时不会累积漂移。
        # 若单轮耗时已超 REFRESH_SEC，则 delay=0 立即补刷。
        delay = max(0.0, REFRESH_SEC - (time.monotonic() - t0))
        t = threading.Timer(delay, refresh)
        t.daemon = True
        t.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE_DIR, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, b"index.html not found", "text/plain; charset=utf-8")
        elif path == "/api/data":
            with _lock:
                payload = json.dumps({
                    "updated_at": _cache["updated_at"],
                    "error": _cache["error"],
                    "data": _cache["data"],
                    "refresh_sec": REFRESH_SEC,
                }, ensure_ascii=False)
            self._send(200, payload.encode("utf-8"), "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")


if __name__ == "__main__":
    print(f"黄金盯盘网页看板启动中… 访问 http://127.0.0.1:{PORT}", flush=True)
    refresh()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
