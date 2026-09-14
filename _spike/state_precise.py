# -*- coding: utf-8 -*-
"""精确区分：Widget 的真实状态属性 vs 绑定方法引用。"""
import ast, io, re

P = r"C:\Users\Admin\WorkBuddy\盯盘\gold_widget.py"
t = io.open(P, encoding="utf-8").read()
tree = ast.parse(t)
widget = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Widget"][0]

method_names = {n.name for n in widget.body if isinstance(n, ast.FunctionDef)}

attr_use = {}
for node in ast.walk(widget):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        attr_use[node.attr] = attr_use.get(node.attr, 0) + 1

state = {k: v for k, v in attr_use.items() if k not in method_names}
funcs = {k: v for k, v in attr_use.items() if k in method_names}

o = []
p = o.append
p("self.<name> 引用点总数 : %d" % sum(attr_use.values()))
p("  其中【状态/数据/控件属性】: %d 个名字, %d 次引用" % (len(state), sum(state.values())))
p("  其中【绑定方法引用】      : %d 个名字, %d 次引用  (如 self._apply_size 传给 after/bind)" % (len(funcs), sum(funcs.values())))
p("")
p("==> 真实状态面：%d 个属性，%d 次引用" % (len(state), sum(state.values())))
p("")
p("绑定方法引用明细（这些不是状态，拆分时不用搬）：")
for k, v in sorted(funcs.items(), key=lambda x: -x[1]):
    p("   self.%-32s %2d" % (k, v))

# 控件 vs 数据/开关 粗分（只做两层，避免过度归类）
WIDGET_HINT = re.compile(
    r"(root$|body$|bar$|canvas$|box$|label$|lbl$|btn|button|entry|frame|menu_win|"
    r"toggle|pill|dot|header|_rows$|title_bar|divider$|inner$|area$|ph_lbl|"
    r"price_row|m_name|t_time|btn_|search_entry|dot$)", re.I)
wid = {k: v for k, v in state.items() if WIDGET_HINT.search(k)}
rest = {k: v for k, v in state.items() if k not in wid}
p("")
p("控件引用（tk 控件对象）: %d 个, %d 次" % (len(wid), sum(wid.values())))
p("非控件（数据/开关/缓存/配置）: %d 个, %d 次" % (len(rest), sum(rest.values())))
p("")
p("非控件属性明细 TOP 25：")
for k, v in sorted(rest.items(), key=lambda x: -x[1])[:25]:
    p("   self.%-30s %3d" % (k, v))

io.open(r"C:\Users\Admin\WorkBuddy\盯盘\_spike\state_precise.txt", "w", encoding="utf-8").write("\n".join(o))
print("\n".join(o))
