# -*- coding: utf-8 -*-
"""量化 gold_widget.py 的体量与耦合，为拆分评估提供依据。"""
import ast
import io
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gold_widget.py")
text = io.open(SRC, encoding="utf-8").read()
lines = text.splitlines()
total = len(lines)
tree = ast.parse(text)

nonblank = sum(1 for l in lines if l.strip())
comment = sum(1 for l in lines if l.strip().startswith("#"))
docstring_lines = 0
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
        d = ast.get_docstring(node, clean=False)
        if d:
            docstring_lines += d.count("\n") + 1

out = []
p = out.append
p("=" * 78)
p("gold_widget.py 体量")
p("=" * 78)
p("总行数            : %d" % total)
p("非空行            : %d" % nonblank)
p("纯注释行          : %d" % comment)
p("docstring 行(约)  : %d" % docstring_lines)
p("注释+doc 占比     : %.1f%%" % ((comment + docstring_lines) * 100.0 / total))

# ---- 顶层结构 ----
p("")
p("=" * 78)
p("顶层结构")
p("=" * 78)
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        end = node.end_lineno
        p("[class] %-24s %5d-%-5d  共 %4d 行   %d 个方法"
          % (node.name, node.lineno, end, end - node.lineno + 1,
             sum(1 for n in node.body if isinstance(n, ast.FunctionDef))))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        p("[func ] %-24s %5d-%-5d  共 %4d 行"
          % (node.name, node.lineno, node.end_lineno, node.end_lineno - node.lineno + 1))

# ---- 方法体量排名 ----
p("")
p("=" * 78)
p("方法体量 TOP 25（行数）")
p("=" * 78)
methods = []
tk_calls = re.compile(
    r"\b(Label|Frame|Canvas|Entry|Button|Toplevel|Text|Scrollbar|Menu|"
    r"StringVar|IntVar|BooleanVar|After|after|place|pack|grid|config|configure|"
    r"bind|create_text|create_rectangle|create_line|create_image|winfo_|"
    r"geometry|overrideredirect|attributes|photoimage|PhotoImage)\b",
    re.I)
all_methods = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        all_methods.append(node)
for node in all_methods:
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    size = node.end_lineno - node.lineno + 1
    n_self = len(re.findall(r"\bself\.", body))
    n_tk = len(tk_calls.findall(body))
    methods.append((size, node.name, n_self, n_tk))
methods.sort(reverse=True)
p("%-34s %5s %6s %6s" % ("方法", "行数", "self引用", "tk调用"))
for size, name, n_self, n_tk in methods[:25]:
    p("%-34s %5d %6d %6d" % (name, size, n_self, n_tk))
p("")
p("方法总数            : %d" % len(methods))
p("方法行数中位数      : %d" % sorted(m[0] for m in methods)[len(methods) // 2])
p("方法行数均值        : %.1f" % (sum(m[0] for m in methods) / len(methods)))
p(">100 行的方法        : %d 个 -> %s"
  % (sum(1 for m in methods if m[0] > 100),
     ", ".join(m[1] for m in methods if m[0] > 100)))

# ---- 状态耦合：self.xxx 属性总数 ----
p("")
p("=" * 78)
p("状态耦合（Widget 实例属性）")
p("=" * 78)
widget = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Widget"][0]
attrs = {}
assigned = set()
for node in ast.walk(widget):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        attrs[node.attr] = attrs.get(node.attr, 0) + 1
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                assigned.add(t.attr)
p("self.<attr> 引用点总数 : %d" % sum(attrs.values()))
p("不同 self 属性名       : %d" % len(attrs))
p("在 __init__ 外被赋值的 : %d  (跨方法共享可变状态)" % len(assigned))
p("")
p("引用最多的 self 属性 TOP 20：")
for k, v in sorted(attrs.items(), key=lambda x: -x[1])[:20]:
    p("   %-26s %4d 次" % ("self." + k, v))

# ---- tkinter 依赖度：哪些方法几乎不碰 tk ----
p("")
p("=" * 78)
p("tkinter 依赖度（可抽性排序：tk 调用少 + self 引用少 = 越独立）")
p("=" * 78)
pure = [(m[0], m[1], m[2], m[3]) for m in methods if m[3] <= 2]
pure.sort(key=lambda x: (x[3], x[2]))
p("%-34s %5s %6s %6s" % ("方法", "行数", "self引用", "tk调用"))
for size, name, n_self, n_tk in pure:
    p("%-34s %5d %6d %6d" % (name, size, n_self, n_tk))
p("")
p("tk 调用 <=2 的方法数 : %d / %d" % (len(pure), len(methods)))

# ---- 模块级依赖 ----
p("")
p("=" * 78)
p("模块级导入与全局")
p("=" * 78)
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        p("  " + lines[node.lineno - 1].strip())
globals_ = [t.id for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)]
p("")
p("模块级全局名        : %d" % len(globals_))
p("  " + ", ".join(globals_))

# ---- 异常处理统计 ----
p("")
p("=" * 78)
p("异常处理")
p("=" * 78)
bare_pass = len(re.findall(r"except[^\n]*:\s*\n\s*(?:pass|continue)\s*\n", text))
except_all = len(re.findall(r"except\b", text))
p("except 子句总数     : %d" % except_all)
p("except ...: pass    : %d" % bare_pass)

# ---- 测试可覆盖性 ----
p("")
p("=" * 78)
p("测试覆盖映射")
p("=" * 78)
proj = os.path.dirname(SRC)
tests = sorted(f for f in os.listdir(proj) if f.startswith("_t_") and f.endswith(".py"))
p("现有回归脚本 %d 个：%s" % (len(tests), ", ".join(tests)))
for t in tests:
    tp = os.path.join(proj, t)
    try:
        tt = io.open(tp, encoding="utf-8").read()
    except Exception:
        continue
    imports_gw = "gold_widget" in tt
    imports_gd = "gold_data" in tt
    imports_gl = "glog" in tt
    p("  %-26s 引 gold_widget=%-5s gold_data=%-5s glog=%-5s" %
      (t, imports_gw, imports_gd, imports_gl))

# ---- 关键：直接可单测的纯函数在哪 ----
p("")
p("=" * 78)
p("结论摘要")
p("=" * 78)
p("1) Widget 类占 %d 行（%.0f%% 的文件）" %
  (widget.end_lineno - widget.lineno + 1,
   (widget.end_lineno - widget.lineno + 1) * 100.0 / total))
p("2) 模块级纯函数 %d 个：%s" %
  (sum(1 for n in tree.body if isinstance(n, ast.FunctionDef)),
   ", ".join(n.name for n in tree.body if isinstance(n, ast.FunctionDef))))
p("3) self 属性 %d 个、引用 %d 次 -> 单类内高内聚，但也是拆分的最大障碍" %
  (len(attrs), sum(attrs.values())))

io.open(os.path.join(proj, "_spike", "analyze_out.txt"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
