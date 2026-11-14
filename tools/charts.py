"""看板里的图。脚本直接写 SVG，不用图表库（Yu 2026-11-14 定）。

画图的规矩照《设计方案》6.1：
- 证据类型用形状（和页面图例同一套）；核验状态用实心和空心：专业已复核的实心，还没复核的空心。
- 颜色不单独表示含义：基准、只作参考、图上读数，都在点旁边或点的提示里用字写明。
- 原文给了范围或误差就画出来。不可比的不连线：只有调用的人明说要连的一组点才连（同一批测试里的同一个样品）。
- 每个点是一个链接，点得进它的证据。
图的样式写在属性里，不靠页面的样式表：单独存成 .svg 文件也是完整的，可以直接放进报告。
颜色和字体跟页面的样式表是一套（tools/dashboard/style.css）：墨色、一种蓝、几档灰。网格和坐标轴是细的实线，颜色浅，不抢数据。
同样的数据画出来逐字节相同：坐标一律保留一位小数，不用随机数和时间。
"""
import math

from display import MARKS, MARK_UNKNOWN, SUPERSCRIPT, fmt_num
from htmlgen import Raw, el

# 墨色画基准，蓝色画参与比较的，灰色画只作参考的和参考线；MUTED 是图上的小字；GRID、AXIS 是网格和坐标轴
INK, BLUE, GREY, MUTED, GRID, AXIS = "#1D1D1F", "#0066CC", "#8E8E93", "#636366", "#E8E8ED", "#D2D2D7"
SURFACE = "#FFFFFF"   # 图的底色。空心的记号里面填的就是它
FONT = ('-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",'
        '"Noto Sans CJK SC",system-ui,sans-serif')
ROLE_COLOR = {"baseline": INK, "reference": GREY}


def n(v):
    return f"{v:.1f}"


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def nice_step(raw):
    """把步长取成 1、2、5 乘以 10 的整数次方。"""
    exponent = math.floor(math.log10(raw))
    fraction = raw / 10 ** exponent
    nice = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return nice * 10 ** exponent


INSET = 18   # 两头各留出这么多像素：落在最小、最大刻度上的点不会压在坐标轴和边框上


class Scale:
    """数值到像素：值域 [lo, hi] 对到 [a, b] 往里各收 INSET 像素。log 为真时按对数。ticks 是刻度的数值。"""

    def __init__(self, lo, hi, a, b, log, ticks):
        inset = INSET if b > a else -INSET
        self.lo, self.hi, self.a, self.b, self.log, self.ticks = lo, hi, a + inset, b - inset, log, ticks

    def label(self, tick):
        """刻度上的字。对数轴上只要有一个刻度太大或太小，就整根轴都写成 10 的几次方，不混着写。"""
        if self.log:
            exponents = [round(math.log10(t)) for t in self.ticks]
            if min(exponents) < -3 or max(exponents) > 4:
                return "10" + str(round(math.log10(tick))).translate(SUPERSCRIPT)
        return fmt_num(tick)

    def __call__(self, v):
        if self.log:
            t = (math.log10(v) - math.log10(self.lo)) / (math.log10(self.hi) - math.log10(self.lo))
        else:
            t = (v - self.lo) / (self.hi - self.lo)
        return self.a + t * (self.b - self.a)


def scale_for(values, a, b, log="auto"):
    """给一组数定坐标轴：刻度取整，两头留到刻度上。全是正数、最大最小差到一百倍以上时用对数轴。"""
    vals = sorted(v for v in values if is_number(v))
    if not vals:
        vals = [0.0, 1.0]
    lo, hi = vals[0], vals[-1]
    use_log = lo > 0 and (log is True or (log == "auto" and hi / lo >= 100))
    if use_log:
        e0, e1 = math.floor(math.log10(lo) + 1e-12), math.ceil(math.log10(hi) - 1e-12)
        if e0 == e1:
            e1 += 1
        return Scale(10.0 ** e0, 10.0 ** e1, a, b, True, [10.0 ** e for e in range(e0, e1 + 1)])
    if lo == hi:
        pad = abs(lo) * 0.1 or 1.0
        lo, hi = lo - pad, hi + pad
    step = nice_step((hi - lo) / 4)
    first, last = math.floor(lo / step + 1e-9), math.ceil(hi / step - 1e-9)
    ticks = [round(i * step, 12) for i in range(first, last + 1)]
    return Scale(ticks[0], ticks[-1], a, b, False, ticks)


def text(x, y, content, size=12, fill=MUTED, anchor="start", weight=None):
    return el("text", {"x": n(x), "y": n(y), "font-size": size, "fill": fill, "text-anchor": anchor, "font-weight": weight}, content)


def line(x1, y1, x2, y2, stroke=AXIS, width=1, dash=None):
    return el("line", {"x1": n(x1), "y1": n(y1), "x2": n(x2), "y2": n(y2), "stroke": stroke, "stroke-width": width,
                       "stroke-dasharray": dash})


def marker(kind, x, y, solid, color, size=14):
    """证据类型的记号，中心在 (x, y)。solid 为真画实心，否则空心。"""
    k = size / 12
    return el("g", {"transform": f"translate({n(x - size / 2)} {n(y - size / 2)}) scale({k:.3f})",
                    "fill": color if solid else SURFACE, "stroke": color, "stroke-width": f"{1.6 / k:.2f}",
                    "stroke-linejoin": "round"}, Raw(MARKS.get(kind, MARK_UNKNOWN)))


def point(p, x, y):
    """一个数据点：提示文字、够大的点击范围、记号。有 href 的是链接。"""
    color = ROLE_COLOR.get(p.get("role"), BLUE)
    inner = [el("title", None, p.get("title")),
             el("circle", {"cx": n(x), "cy": n(y), "r": 13, "fill": SURFACE, "fill-opacity": 0}),
             marker(p.get("type"), x, y, p.get("solid"), color)]
    if p.get("href"):
        return el("a", {"href": p["href"], "aria-label": p.get("title"), "data-evidence": p.get("evidence")}, inner)
    return el("g", {"data-evidence": p.get("evidence")}, inner)


def error_bar(p, lo, hi, at, horizontal):
    """范围或误差。图上读数的用虚线。"""
    color = ROLE_COLOR.get(p.get("role"), BLUE)
    dash = "3 2" if p.get("dashed") else None
    if horizontal:
        return [line(lo, at, hi, at, color, 1.4, dash), line(lo, at - 4, lo, at + 4, color, 1.4), line(hi, at - 4, hi, at + 4, color, 1.4)]
    return [line(at, lo, at, hi, color, 1.4, dash), line(at - 4, lo, at + 4, lo, color, 1.4), line(at - 4, hi, at + 4, hi, color, 1.4)]


def frame(width, height, label, body):
    return el("svg", {"xmlns": "http://www.w3.org/2000/svg", "class": "chart", "viewBox": f"0 0 {width} {height}",
                      "width": width, "height": height, "role": "group", "aria-label": label, "font-family": FONT},
              el("title", None, label), body)


def dot_chart(rows, axis_label, label, ref=None, ref_label=None, width=760):
    """点图：一行一个对象，横轴是数值。rows 的每项：label、sub、value、err（下限, 上限）、
    type、solid、role、href、title、dashed、evidence。ref 是要画的参考线（比如比值 1）。"""
    left, right, top, row_h, bottom = 250, 84, 28, 38, 46
    height = top + row_h * max(len(rows), 1) + bottom
    values = [r["value"] for r in rows] + [v for r in rows for v in (r.get("err") or ())] + ([ref] if ref is not None else [])
    sx = scale_for(values, left, width - right)
    base = top + row_h * max(len(rows), 1)
    body = []
    for t in sx.ticks:
        body += [line(sx(t), top - 6, sx(t), base, GRID), text(sx(t), base + 18, sx.label(t), anchor="middle")]
    body += [line(left, base, width - right, base), text((left + width - right) / 2, base + 38, axis_label, anchor="middle")]
    if ref is not None:
        body += [line(sx(ref), top - 6, sx(ref), base, GREY, 1, "4 3"), text(sx(ref), top - 12, ref_label, 11, anchor="middle")]
    for i, r in enumerate(rows):
        y = top + row_h * i + row_h / 2
        body += [text(0, y - 2, r.get("label"), 13, INK, weight=600), text(0, y + 13, r.get("sub"), 11),
                 line(left, y, width - right, y, GRID)]
        if r.get("err"):
            body += error_bar(r, sx(r["err"][0]), sx(r["err"][1]), y, True)
        body += [point(r, sx(r["value"]), y),
                 text(max(sx(r["value"]), sx(r["err"][1]) if r.get("err") else 0) + 14, y + 4, fmt_num(r["value"]), 12, INK)]
    return frame(width, height, label, body)


def xy_chart(series, x_label, y_label, label, width=760, height=400):
    """两个量的图。series 的每项：points（每点有 x、y、label、x_err、y_err 和 dot_chart 里那些）、connect。
    connect 为真的一组点按横坐标连起来；别的不连。"""
    left, right, top, bottom = 70, 28, 34, 54
    pts = [p for s in series for p in s["points"]]
    sx = scale_for([p["x"] for p in pts] + [v for p in pts for v in (p.get("x_err") or ())], left, width - right)
    sy = scale_for([p["y"] for p in pts] + [v for p in pts for v in (p.get("y_err") or ())], height - bottom, top)
    body = [text(0, 14, y_label, 12)]
    for t in sx.ticks:
        body += [line(sx(t), top, sx(t), height - bottom, GRID), text(sx(t), height - bottom + 18, sx.label(t), anchor="middle")]
    for t in sy.ticks:
        body += [line(left, sy(t), width - right, sy(t), GRID), text(left - 8, sy(t) + 4, sy.label(t), anchor="end")]
    body += [line(left, height - bottom, width - right, height - bottom), line(left, top, left, height - bottom),
             text((left + width - right) / 2, height - 10, x_label, anchor="middle")]
    for s in series:
        ordered = sorted(s["points"], key=lambda p: (p["x"], p["y"]))
        if s.get("connect") and len(ordered) > 1:
            color = ROLE_COLOR.get(ordered[0].get("role"), BLUE)
            body.append(el("polyline", {"points": " ".join(f"{n(sx(p['x']))},{n(sy(p['y']))}" for p in ordered),
                                        "fill": "none", "stroke": color, "stroke-width": 2, "stroke-linejoin": "round",
                                        "stroke-linecap": "round"}))
    placed = []
    for p in sorted(pts, key=lambda p: (p["x"], p["y"], str(p.get("label")))):
        x, y = sx(p["x"]), sy(p["y"])
        if p.get("x_err"):
            body += error_bar(p, sx(p["x_err"][0]), sx(p["x_err"][1]), y, True)
        if p.get("y_err"):
            body += error_bar(p, sy(p["y_err"][0]), sy(p["y_err"][1]), x, False)
        body.append(point(p, x, y))
        if p.get("label"):
            # 标注先放右上；和前面的标注挤在一起就放右下
            ly = y - 10
            if any(abs(lx - x) < 90 and abs(py - ly) < 13 for lx, py in placed):
                ly = y + 20
            placed.append((x, ly))
            body.append(text(x + 10, ly, p["label"], 11, INK))
    return frame(width, height, label, body)
