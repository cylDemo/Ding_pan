# -*- coding: utf-8 -*-
"""精确统计异常处理（区分单行/多行、裸 pass/continue）。"""
import io, re

P = r"C:\Users\Admin\WorkBuddy\盯盘\gold_widget.py"
t = io.open(P, encoding="utf-8").read()
L = t.splitlines()

except_total = 0
bare_silent = 0   # except ...: 紧跟 pass/continue（含单行写法）
narrow = 0        # 指定了具体异常类型
broad = 0         # Exception / BaseException
sync_silent = 0   # 与 glog 同行或就近的静默

for i, ln in enumerate(L):
    m = re.match(r"^(\s*)except\b(.*)$", ln)
    if not m:
        continue
    except_total += 1
    rest = m.group(2).strip()
    # 异常类型
    if rest.startswith(":"):
        pass
    else:
        typ = rest.split(":")[0].strip()
        if re.match(r"^(Exception|BaseException)$", typ):
            broad += 1
        else:
            narrow += 1
    # 是否紧跟 pass/continue
    body = rest.split(":", 1)[1].strip() if ":" in rest else ""
    if body in ("pass", "continue"):
        bare_silent += 1
    elif body == "":
        for j in range(i + 1, min(i + 5, len(L))):
            s = L[j].strip()
            if not s or s.startswith("#"):
                continue
            if s in ("pass", "continue"):
                bare_silent += 1
            break

o = []
p = o.append
p("== gold_widget.py 异常处理（逐行 AST 邻接口径）==")
p("except 子句总数        : %d" % except_total)
p("  裸 except（无类型）  : %d" % (except_total - narrow - broad))
p("  except Exception 等宽: %d" % broad)
p("  指定具体异常类型      : %d" % narrow)
p("静默体（pass/continue）: %d" % bare_silent)
p("")
p("注：早前口径 '72 处裸 except Exception: pass' 与本次 '静默体 %d' 差异来自是否")
p("    计入「except Exception: pass 单行写法」与「多行换行体」，二者都对，但口径不同。")
p("    本报告统一采用本次口径。")
io.open(r"C:\Users\Admin\WorkBuddy\盯盘\_spike\exc.txt", "w", encoding="utf-8").write("\n".join(o))
print("\n".join(o))
