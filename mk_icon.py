#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 盯盘.ico（纯标准库：zlib + struct，无第三方依赖）。

设计：深色圆角方块底 + 金色上升折线 + 末端高亮点 —— 16px 下仍可辨识为"上行行情"。
多尺寸（256/128/64/48/32/24/16）PNG 内嵌，超采样抗锯齿。
仅供构建期生成，不参与运行时打包。
"""

import math
import os
import struct
import zlib

BG = (30, 36, 51)        # #1E2433 深色底
GOLD = (224, 184, 76)    # #E0B84C 主金色
GOLD_HI = (245, 214, 120)  # #F5D678 高光

# 归一化折线顶点（0-1 坐标），自左下向右上，末点为高亮圆
PTS = [(0.24, 0.72), (0.44, 0.53), (0.60, 0.63), (0.79, 0.31)]


def _inside_round(x, y, s, rad):
    """圆角矩形内判定（硬边界，AA 交给超采样）。"""
    if x < 0 or y < 0 or x > s or y > s:
        return False
    cx = min(max(x, rad), s - rad)
    cy = min(max(y, rad), s - rad)
    if (x, y) == (cx, cy):
        return True
    return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size, ss):
    """渲染 size×size RGBA 像素，ss 为超采样倍数。"""
    rad = 0.24 * size
    lw = 0.115 * size
    pts = [(x * size, y * size) for x, y in PTS]
    dot_r = 0.105 * size
    ex, ey = pts[-1]
    inv = 1.0 / (ss * ss)
    rows = []
    for j in range(size):
        row = []
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(ss):
                y = j + (sy + 0.5) / ss
                for sx in range(ss):
                    x = i + (sx + 0.5) / ss
                    if not _inside_round(x, y, size, rad):
                        continue
                    col = BG
                    d = min(_seg_dist(x, y, pts[k][0], pts[k][1],
                                      pts[k + 1][0], pts[k + 1][1])
                            for k in range(len(pts) - 1))
                    if d <= lw / 2:
                        col = GOLD
                    if math.hypot(x - ex, y - ey) <= dot_r:
                        col = GOLD_HI
                    acc[0] += col[0]
                    acc[1] += col[1]
                    acc[2] += col[2]
                    acc[3] += 255.0
            row.append(tuple(int(round(v * inv)) for v in acc))
        rows.append(row)
    return rows


def _chunk(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def png_bytes(rgba, size):
    raw = bytearray()
    for j in range(size):
        raw.append(0)  # filter: none
        for i in range(size):
            raw += bytes(rgba[j][i])
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "盯盘.ico")
    sizes = [256, 128, 64, 48, 32, 24, 16]
    blobs = []
    for s in sizes:
        ss = 2 if s >= 128 else 4
        blobs.append((s, png_bytes(render(s, ss), s)))
        print("rendered %dx%d (%d bytes)" % (s, s, len(blobs[-1][1])))
    head = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for s, b in blobs:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    with open(out, "wb") as f:
        f.write(head + entries + b"".join(b for _, b in blobs))
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
