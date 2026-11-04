# -*- coding: utf-8 -*-
"""生成发布包配图（可复现脚本）。

产出（默认写到仓库根的 docs/）：
  hero.png               封面横幅（README 顶部）
  four-dimensions.png    四个维度速查
  evidence-discipline.png 四条证据纪律
  review-loop.png        评审闭环流程

文件名一律用 ASCII：中文路径在 GitHub release 附件上传时会被解析成 default.png。

字体：Windows 微软雅黑（msyh.ttc / msyhbd.ttc）。
注意：微软雅黑缺 U+2194（↔）字形，脚本对 ↔ 走自绘双向箭头，避免渲染成方框。

用法：
    python -X utf8 scripts/gen_images.py
    python -X utf8 scripts/gen_images.py --out ../../docs
"""
from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

REG = "C:/Windows/Fonts/msyh.ttc"
BOLD = "C:/Windows/Fonts/msyhbd.ttc"

BG = (247, 244, 239)
CARD = (255, 255, 255)
BORDER = (231, 225, 214)
INK = (28, 28, 30)
SUB = (122, 118, 112)
RED = (176, 58, 46)
BLUE = (46, 94, 142)
GREEN = (58, 125, 68)
OCHRE = (192, 118, 26)

F = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in F:
        F[key] = ImageFont.truetype(BOLD if bold else REG, size)
    return F[key]


def arrow_bidir(draw, x, y, w, color, width=3):
    """自绘双向箭头（微软雅黑无 ↔ 字形）。"""
    draw.line([(x, y), (x + w, y)], fill=color, width=width)
    draw.line([(x, y), (x + 13, y - 9)], fill=color, width=width)
    draw.line([(x, y), (x + 13, y + 9)], fill=color, width=width)
    draw.line([(x + w, y), (x + w - 13, y - 9)], fill=color, width=width)
    draw.line([(x + w, y), (x + w - 13, y + 9)], fill=color, width=width)


def text_with_arrows(draw, xy, text, fnt, color):
    """绘制含 ↔ 的文本，↔ 用自绘箭头替换。返回整体宽度。"""
    parts = text.split("↔")
    total = 0
    for i, p in enumerate(parts):
        total += draw.textlength(p, font=fnt)
    total += 30 * (len(parts) - 1)
    x, y = xy
    for i, p in enumerate(parts):
        if p:
            draw.text((x, y), p, font=fnt, fill=color)
            x += draw.textlength(p, font=fnt)
        if i < len(parts) - 1:
            arrow_bidir(draw, x + 2, y + fnt.size * 0.55, 26, color)
            x += 30
    return total


def tw(draw, s, fnt):
    return draw.textlength(s, font=fnt)


def rounded(draw, box, radius=14, fill=CARD, outline=BORDER, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(draw, title, subtitle, accent=RED, W=1400):
    draw.text((64, 44), title, font=font(46, True), fill=INK)
    draw.text((66, 112), subtitle, font=font(21), fill=SUB)
    draw.rectangle([66, 148, 128, 155], fill=accent)


def bullets(draw, x, y, items, fnt, dot, line_h=42, gap=14, max_w=560):
    cy = y
    for it in items:
        draw.ellipse([x, cy + 9, x + 9, cy + 18], fill=dot)
        tx = x + 24
        for ln in wrap(draw, it, fnt, max_w):
            draw.text((tx, cy), ln, font=fnt, fill=(58, 56, 54))
            cy += line_h
        cy += gap
    return cy


def wrap(draw, s, fnt, max_w):
    lines, cur = [], ""
    for ch in s:
        if ch == "↔":
            # 箭头当成一个宽字符参与断行
            if draw.textlength(cur + ch, font=fnt) > max_w and cur:
                lines.append(cur)
                cur = ""
            cur += ch
            continue
        if draw.textlength(cur + ch, font=fnt) > max_w and cur:
            lines.append(cur)
            cur = ""
        cur += ch
    if cur:
        lines.append(cur)
    return lines


def arrow_gap(draw, s, fnt):
    """文本中 ↔ 预留 30px 宽度的折算。"""
    return s.replace("↔", "\u3000")


def draw_wrapped(draw, x, y, s, fnt, color, max_w, line_h):
    """逐行绘制，含 ↔ 的行用自绘箭头。"""
    for ln in wrap(draw, arrow_gap(s) if False else s, fnt, max_w):
        if "↔" in ln:
            text_with_arrows(draw, (x, y), ln, fnt, color)
        else:
            draw.text((x, y), ln, font=fnt, fill=color)
        y += line_h
    return y


# ---------------------------------------------------------------- hero
def gen_hero(out):
    W, H = 1400, 560
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # 顶部渐变条
    for i in range(W):
        t = i / W
        c = (
            int(176 + (46 - 176) * t),
            int(58 + (94 - 58) * t),
            int(46 + (142 - 46) * t),
        )
        d.rectangle([i, 0, i, 7], fill=c)
    d.rectangle([0, H - 4, W, H], fill=(30, 30, 32))

    d.text((72, 84), "fengneng-review", font=font(24), fill=SUB)
    d.text((68, 126), "丰容 / 节能评审框架", font=font(64, True), fill=INK)
    d.text((72, 214), "Enrichment & Energy-Saving Review Framework", font=font(24), fill=SUB)
    d.text(
        (72, 262),
        "不是给答案，是帮你把依据和未知分开。",
        font=font(34, True),
        fill=RED,
    )
    d.text(
        (72, 320),
        "四维度检查清单 · 评审闭环 · 证据纪律 —— 一个在真实使用中迭代出来的框架",
        font=font(21),
        fill=(90, 86, 82),
    )

    pills = [
        ("一 · 丰容价值", BLUE),
        ("二 · 节能价值", GREEN),
        ("三 · 平衡与风险", OCHRE),
        ("四 · 铁律兼容", RED),
    ]
    px = 72
    for label, c in pills:
        w = tw(d, label, font(20, True)) + 44
        d.rounded_rectangle([px, 386, px + w, 434], radius=24, fill=(255, 255, 255), outline=c, width=2)
        d.ellipse([px + 18, 405, px + 30, 417], fill=c)
        d.text((px + 40, 398), label, font=font(20, True), fill=INK)
        px += w + 18

    d.text((72, 486), "v1.13 · Apache License 2.0 · 提供给人类与 agent 两套入口",
           font=font(19), fill=SUB)
    im.save(os.path.join(out, "hero.png"))


# ------------------------------------------------------- 四维度矩阵
def gen_matrix(out):
    W, H = 1400, 1000
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(
        d,
        "丰容 / 节能评审框架 · 四维度",
        "核心问题：带来的丰容，与消耗的精力（含被 AI 加速后反而变多的那部分），是不是划算",
    )

    cards = [
        (
            BLUE,
            "一 · 丰容价值",
            [
                "带来什么类型的丰容？（认知 / 社交 / 物理感官）",
                "边际效用曲线如何？多久开始递减？会不会越做越像负担？",
                "它是「基本盘」还是「可调节增量」？",
                "间接丰容：基础设施类不再被系统性低估",
            ],
        ),
        (
            GREEN,
            "二 · 节能价值",
            [
                "真的省精力，还是把精力换个地方花？",
                "长期净节能，还是净耗能？",
                "有没有「越用越沉没成本」的东西？",
            ],
        ),
        (
            OCHRE,
            "三 · 平衡与风险",
            [
                "遇到问题能不能停下来？出事损失什么？",
                "运维成本谁来做？＝ 时间 + 费用 + 故障善后 + 权限风险",
                "读 vs 写权限分级：读写风险不对称",
                "产出物的形态决定它是不是负担",
            ],
        ),
        (
            RED,
            "四 · 铁律兼容",
            [
                "触碰了哪些既有硬约束与禁忌？",
                "agent 提炼的风险提示 ≠ 作者明确规定的禁忌",
                "（否决权仅属后者，且仅在其授权范围内）",
            ],
        ),
    ]

    cw, chh = 620, 280
    x0, y0, gx, gy = 64, 172, 32, 22
    for i, (color, title, items) in enumerate(cards):
        cx = x0 + (i % 2) * (cw + gx)
        cy = y0 + (i // 2) * (chh + gy)
        rounded(d, [cx, cy, cx + cw, cy + chh])
        d.rectangle([cx, cy + 1, cx + 7, cy + chh - 1], fill=color)
        d.text((cx + 32, cy + 22), title, font=font(28, True), fill=INK)
        bullets(d, cx + 32, cy + 78, items, font(19), color, line_h=38, gap=10, max_w=cw - 70)

    by = y0 + 2 * (chh + gy)
    rounded(d, [64, by, W - 64, by + 160], radius=16, fill=(255, 253, 250))
    d.text((92, by + 18), "评审闭环：结论之后才是重点", font=font(24, True), fill=INK)
    y2 = by + 62
    for ln in wrap(
        d,
        "结论落六态之一（继续 / 限额试验 / 缩减 / 暂停 / 停止 / 接受残余风险）→ 被采纳的承诺写成硬谓词并挂账 → 到期提示复核 → 记录「框架体感」→ 阈值触发框架复盘",
        font(17),
        W - 190,
    ):
        d.text((92, y2), ln, font=font(17), fill=(70, 67, 64))
        y2 += 28
    d.text(
        (92, y2 + 8),
        "脚本只核格式、日期与声明状态，实际证据另行检查。   |   边界：解决单个项目，解决不了系统级问题。",
        font=font(16),
        fill=SUB,
    )
    im.save(os.path.join(out, "four-dimensions.png"))


# ------------------------------------------------------- 证据纪律
def gen_evidence(out):
    W, H = 1400, 860
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "证据纪律：四条，比四维度更值钱", "四条来自真实教训（不是从原理推出来的）")

    items = [
        (
            "文档 ↔ 实现必须对读",
            [
                "文档写「一律推送」、实现却多了一个前提条件 —— 这是纸面规则，不是行为。",
                "规则文本和执行现实不一致时，这段规则不能证明被执行。",
            ],
        ),
        (
            "触发条件当前是否可能成立？",
            [
                "永不成立 ＝ 纸面条款候选（该删或该修）；长期成立却没有对应动作 ＝ 噪声或失效候选。",
                "只标记，不自动删 —— 删规则是人的决定。",
            ],
        ),
        (
            "单次成功只证明「发生过」",
            [
                "要下「稳定」「可靠」这类结论，必须重复运行，并报出次数 n 与失败数。",
                "样本不足就标「待验证」。「首跑成功 → 长期有效」是最常见的一次推断跳跃。",
            ],
        ),
        (
            "独立验证有层级",
            [
                "「不同源」只是起点。合格的独立层必须能接触原始凭证、自由选择检查方法、报告不同结论。",
                "只能对着你的摘要背书的，叫第二意见，不叫独立验证。",
            ],
        ),
    ]

    y = 186
    for idx, (title, lines) in enumerate(items, 1):
        h = 150 if len(lines) == 2 else 128
        rounded(d, [64, y, W - 64, y + h], radius=14)
        d.text((94, y + 30), str(idx), font=font(30, True), fill=RED)
        text_with_arrows(d, (140, y + 30), title, font(24, True), INK)
        ly = y + 74
        for ln in lines:
            d.text((140, ly), ln, font=font(19), fill=(62, 60, 58))
            ly += 34
        y += h + 16
    im.save(os.path.join(out, "evidence-discipline.png"))


# ------------------------------------------------------- 评审闭环
def gen_loop(out):
    W, H = 1400, 760
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "评审闭环", "一份评审报告本身没有价值，有价值的是它后面发生的事")

    steps = [
        ("评审", "四维度过一遍\n产出报告", BLUE),
        ("定态", "结论落六态之一\n继续/限额/缩减/暂停/停止/接受残余风险", RED),
        ("挂账", "只把被采纳的承诺\n写成硬谓词并追踪", OCHRE),
        ("验证", "到期按「证明什么」\n那一栏去核", GREEN),
        ("复盘", "记录本次「别扭感」\n达阈值触发框架复盘", BLUE),
    ]
    n = len(steps)
    bw, bh = 232, 250
    gap = (W - 128 - n * bw) // (n - 1)
    x = 64
    y = 220
    for i, (t, desc, c) in enumerate(steps):
        rounded(d, [x, y, x + bw, y + bh], radius=16)
        d.rectangle([x, y + 1, x + bw, y + 8], fill=c)
        d.text((x + 26, y + 34), f"{i + 1}", font=font(22, True), fill=c)
        d.text((x + 52, y + 30), t, font=font(28, True), fill=INK)
        ly = y + 92
        for ln in desc.split("\n"):
            for sub in wrap(d, ln, font(17), bw - 52):
                d.text((x + 26, ly), sub, font=font(17), fill=(66, 63, 61))
                ly += 30
        if i < n - 1:
            ax = x + bw + 6
            ay = y + bh // 2
            d.line([(ax, ay), (ax + gap - 14, ay)], fill=(176, 170, 160), width=3)
            d.line([(ax + gap - 14, ay), (ax + gap - 28, ay - 9)], fill=(176, 170, 160), width=3)
            d.line([(ax + gap - 14, ay), (ax + gap - 28, ay + 9)], fill=(176, 170, 160), width=3)
        x += bw + gap

    rounded(d, [64, 520, W - 64, 664], radius=14, fill=(255, 253, 250))
    d.text((92, 540), "硬谓词怎么写", font=font(22, True), fill=INK)
    d.text(
        (92, 578),
        "截止日期  +  可检查的完成标准  +  验证方式  +  「证明什么」标注",
        font=font(19),
        fill=(70, 67, 64),
    )
    d.text(
        (92, 612),
        "「证明什么」这一栏最容易漏，但它决定这条待办会不会变成一句空话：证明「实现存在」可以机器判定，证明「价值」需要人判断，且不许伪装成机器谓词。",
        font=font(17),
        fill=SUB,
    )
    im.save(os.path.join(out, "review-loop.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    gen_hero(a.out)
    gen_matrix(a.out)
    gen_evidence(a.out)
    gen_loop(a.out)
    print("generated:", a.out)


if __name__ == "__main__":
    main()
