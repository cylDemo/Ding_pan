# -*- coding: utf-8 -*-
"""把 Widget 的 176 个 self 属性分类：控件引用 / 数据 / 开关 / 交互态 / 回调。"""
import ast, io, os, re

P = r"C:\Users\Admin\WorkBuddy\盯盘\gold_widget.py"
t = io.open(P, encoding="utf-8").read()
tree = ast.parse(t)
widget = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Widget"][0]

attr_use = {}
attr_assigned_in_init = set()
init = None
for n in widget.body:
    if isinstance(n, ast.FunctionDef) and n.name == "__init__":
        init = n
for node in ast.walk(widget):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        attr_use[node.attr] = attr_use.get(node.attr, 0) + 1
if init:
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            for tg in node.targets:
                if isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id == "self":
                    attr_assigned_in_init.add(tg.attr)

WIDGET_HINT = re.compile(
    r"(root|body|bar|canvas|box|label|lbl|btn|button|entry|frame|menu|win|"
    r"toggle|pill|dot|header|rows?|title|place|ph|scroll|sep|line|icon|img)$", re.I)
DATA_HINT = re.compile(r"(data|conf|q$|queue|results|list|items|map|cache|text|arr)", re.I)
FLAG_HINT = re.compile(r"^(_|)(is_|has_|suppress|collapsed|visible|active|busy|loading|hide|show|topmost|mini|mask|_suppress)", re.I)

buckets = {"控件引用": [], "数据/配置": [], "布尔/开关": [], "其他": []}
for k, v in attr_use.items():
    if FLAG_HINT.search(k) or isinstance(attr_use[k], bool):
        buckets["布尔/开关"].append((k, v))
    elif WIDGET_HINT.search(k):
        buckets["控件引用"].append((k, v))
    elif DATA_HINT.search(k):
        buckets["数据/配置"].append((k, v))
    else:
        buckets["其他"].append((k, v))

o = []
p = o.append
p("Widget 的 self 属性分类（共 %d 个，引用 %d 次）" % (len(attr_use), sum(attr_use.values())))
p("=" * 70)
for name, items in buckets.items():
    tot = sum(v for _, v in items)
    p("")
    p("【%s】%d 个属性，引用 %d 次（占 %.0f%%）" % (name, len(items), tot, tot * 100.0 / sum(attr_use.values())))
    for k, v in sorted(items, key=lambda x: -x[1])[:18]:
        p("   %-30s %3d" % ("self." + k, v))
p("")
p("=" * 70)
p("在 __init__ 内被首次赋值的属性: %d 个" % len(attr_assigned_in_init))
p("在 __init__ 外被赋值的属性  : %d 个（跨方法共享可变状态）" % (len(attr_use) - len(attr_assigned_in_init)))
p("")
p("==> 拆分手法含义 ==")
p("  控件引用占比高 -> 用「组合 + 传控件/父容器」而非「传整个 self」")
p("  数据/开关占比高 -> 需要显式 state 对象或回调，不能靠裸 self 传递")

io.open(r"C:\Users\Admin\WorkBuddy\盯盘\_spike\attr.txt", "w", encoding="utf-8").write("\n".join(o))
print("\n".join(o))
