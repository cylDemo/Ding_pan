# -*- coding: utf-8 -*-
"""上传 GitHub 前的敏感信息与入库风险扫描。"""
import os
import re

ROOT = r"C:\Users\Admin\WorkBuddy\盯盘"
OUT = os.path.join(ROOT, "_spike", "_git_scan.txt")

# 只扫源码/文本类文件，跳过二进制与虚拟环境
SKIP_DIRS = {".build_venv", "__pycache__", ".git"}
TEXT_EXT = {".py", ".spec", ".txt", ".md", ".json", ".ini", ".cfg", ".html", ".js"}

PATTERNS = [
    ("硬编码密钥/token", re.compile(r"(?i)\b(api[_-]?key|secret|token|passwd|password|access[_-]?key)\b\s*[:=]\s*['\"][^'\"]{8,}")),
    ("长十六进制串(疑似key)", re.compile(r"['\"][0-9a-fA-F]{32,}['\"]")),
    ("Bearer/Authorization", re.compile(r"(?i)(bearer\s+[A-Za-z0-9._\-]{12,}|authorization\s*[:=])")),
    ("本机绝对路径(用户名)", re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_]+")),
    ("京东/东财敏感串", re.compile(r"(?i)(clawx|jdjr_config|jdjr_query|autotrade|secure_store|openclaw)")),
    ("手机号/邮箱", re.compile(r"(?:\b1[3-9]\d{9}\b|[\w.\-]+@[\w\-]+\.[a-z]{2,})")),
]

lines = []
hits_total = 0

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()
        if ext not in TEXT_EXT:
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, ROOT)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for label, pat in PATTERNS:
            for m in pat.finditer(content):
                ln = content[:m.start()].count("\n") + 1
                snippet = content[m.start():m.end()].replace("\n", " ")[:90]
                if label == "本机绝对路径(用户名)":
                    snippet = re.sub(r"(Users\\+)[A-Za-z0-9_]+", r"\1<USER>", snippet)
                lines.append("[%s] %s:%d  %s" % (label, rel, ln, snippet))
                hits_total += 1

lines.append("")
lines.append("命中总数: %d" % hits_total)
lines.append("扫描范围: %s (已跳过 .build_venv/__pycache__/.git)" % ROOT)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) if lines else "无命中")
print("written", OUT, "hits=", hits_total)
