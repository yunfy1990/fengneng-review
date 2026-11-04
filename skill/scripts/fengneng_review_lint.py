#!/usr/bin/env python3
"""丰容/节能评审日志机械闸（fengneng-review skill 输出格式校验）。

检查 review-log.md 中每条评审条目：
  ① 必须包含「现有产物」字段（v1.2 强制步骤，防止把已落地的东西当成待办）
  ② 「现有产物」字段不能为空——必须列出具体文件，或写「无新增，本项目为全新」
  ③ 必须包含结论、四维度、建议、框架体感字段（格式完整性）
  ④ 结论必须是 ✅过 / ⚠️有条件过 / ❌不过 三档之一

用法：python -X utf8 scripts/fengneng_review_lint.py [review-log 路径]
自检：python -X utf8 scripts/fengneng_review_lint.py --selftest
退出码：违规 > 0 → 1；零违规 → 打印通过并返回 0。
"""

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 评审日志默认取**当前工作目录**（= 项目归属地），与 SKILL.md「skill 目录只放定义，
# 运行数据放项目归属地」一致。skill/ 与仓根都不是默认位置（历史实现两处不一致，已修）。
DEFAULT_LOG = Path.cwd() / "REVIEW_LOG.md"

_OPT_PAREN = r"(?:[（(][^）)]*[）)])?"  # 字段标签后允许一层可选括号注记（2026-10-18 放宽：闸查字段存在性，不查字面排版——「**铁律兼容**（机制类）：」语义合规，误报假违规与投资 C1 裸 grep 教训同源）

_FIELD_NAMES = ("矩阵定位", "现有产物", "业界参考", "结论", "丰容价值", "节能价值", "平衡与风险", "铁律兼容", "建议", "框架体感")

REQUIRED_FIELDS = [
    (name, rf"\*\*{name}\*\*{_OPT_PAREN}[：:]")
    for name in _FIELD_NAMES
]

VALID_MATRIX_ZONES = ("甜品区", "沉迷区", "苦修区", "烂尾区", "中间区")

# 结论必须是三档之一：锚定到"符号 + 档位词"，允许后接括注。
# 反例（已修）：`**结论**：✅ 完全胡说` 只含符号 → 旧实现误判为合法。
VALID_CONCLUSION_PATTERNS = [
    re.compile(r"^✅\s*过(?=$|[\s（(，,。；;])"),
    re.compile(r"^⚠️\s*有条件过(?=$|[\s（(，,。；;])"),
    re.compile(r"^❌\s*不过(?=$|[\s（(，,。；;])"),
]
# 「现有产物」字段的有效值：列出具体文件（含路径/扩展名），或明确写"无新增，本项目为全新"
VALID_EXISTING_PATTERNS = [
    re.compile(r"\.(?:md|py|json|csv|txt|html?|js|ts|sh|ps1|yaml|yml|toml)", re.I),
    re.compile(r"[\\/]\w+"),  # 路径形式
    re.compile(r"无新增.*全新"),
    re.compile(r"不适用"),
    re.compile(r"已完成.*复盘"),
]

REVIEW_HEADER = re.compile(r"^#{2,3}\s+评审[：:]", re.M)


def split_reviews(text):
    """按 '## 评审：' 切分，返回 (header, body) 列表。"""
    matches = list(REVIEW_HEADER.finditer(text))
    reviews = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        header_line = text[m.start():text.find("\n", m.start())].strip()
        body = text[start:end].strip()
        reviews.append((header_line, body))
    return reviews


def check_review(header, body):
    """检查单条评审，返回违规列表。"""
    violations = []

    # ① 必需字段存在性
    for field_name, pattern in REQUIRED_FIELDS:
        if not re.search(pattern, body):
            violations.append(f"缺少「{field_name}」字段")

    # ② 现有产物字段非空检查
    existing_match = re.search(rf"\*\*现有产物\*\*{_OPT_PAREN}[：:][ \t]*([^\n]*)", body)
    if existing_match:
        value = existing_match.group(1).strip()
        if not value:
            violations.append("「现有产物」字段为空")
        elif not any(p.search(value) for p in VALID_EXISTING_PATTERNS):
            violations.append(f"「现有产物」字段值不合法：「{value[:40]}」——必须列出具体文件或写「无新增，本项目为全新」")

    # ③ 结论合法性
    conclusion_match = re.search(rf"\*\*结论\*\*{_OPT_PAREN}[：:][ \t]*([^\n]*)", body)
    if conclusion_match:
        value = conclusion_match.group(1).strip()
        if not any(p.match(value) for p in VALID_CONCLUSION_PATTERNS):
            violations.append(f"结论不合法：「{value[:30]}」——必须是 ✅过 / ⚠️有条件过 / ❌不过")

    # ④ 矩阵定位合法性
    matrix_match = re.search(rf"\*\*矩阵定位\*\*{_OPT_PAREN}[：:][ \t]*([^\n]*)", body)
    if matrix_match:
        value = matrix_match.group(1).strip()
        if not any(value.startswith(z) for z in VALID_MATRIX_ZONES):
            violations.append(f"矩阵定位不合法：「{value[:30]}」——必须是 甜品区/沉迷区/苦修区/烂尾区/中间区")

    return violations


def lint(path):
    """主检查逻辑，返回 (违规数, 输出文本)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return 1, f"读取失败：{e}"

    reviews = split_reviews(text)
    if not reviews:
        return 0, "评审日志为空（无评审条目），跳过"

    total_violations = 0
    output_lines = []

    for header, body in reviews:
        violations = check_review(header, body)
        if violations:
            total_violations += len(violations)
            output_lines.append(f"⚠️  {header}")
            for v in violations:
                output_lines.append(f"    - {v}")

    if total_violations == 0:
        output_lines.append(f"✅ 丰容/节能评审日志体检通过（{len(reviews)} 条评审，格式完整）")
    else:
        output_lines.append(f"共 {total_violations} 项违规（{len(reviews)} 条评审）")

    return total_violations, "\n".join(output_lines)


def selftest():
    """纯逻辑夹具自检，不读真实文件。"""
    cases = [
        (
            "完整合法评审",
            "## 评审：测试项目（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：scripts/test.py、README.md\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            0,
        ),
        (
            "现有产物写无新增",
            "## 评审：新项目（2026-10-12）\n\n**结论**：⚠️ 有条件过\n**矩阵定位**：中间区\n\n**现有产物**：无新增，本项目为全新\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：加退出策略\n\n**框架体感**：无",
            0,
        ),
        (
            "矩阵定位不合法",
            "## 评审：坏定位（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：快乐区\n\n**现有产物**：无新增，本项目为全新\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "缺少现有产物字段",
            "## 评审：缺字段（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "现有产物为空",
            "## 评审：空字段（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "现有产物值不合法",
            "## 评审：不合法值（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：一些东西\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "结论不合法",
            "## 评审：坏结论（2026-10-12）\n\n**结论**：可能过吧\n**矩阵定位**：甜品区\n\n**现有产物**：无新增，本项目为全新\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "缺少多个字段",
            "## 评审：多缺（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：test.py\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高",
            5,  # 缺节能/平衡/铁律/建议/框架体感（业界参考已加）
        ),
        (
            "字段标签带括号注记（合规变体）",
            "## 评审：括号变体（2026-10-18）\n\n**结论**：⚠️ 有条件过\n**矩阵定位**：中间区\n\n**现有产物**：scripts/test.py\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**（机制类，审查强度升高）：好\n\n**建议**（强建议，带因果链）：无\n\n**框架体感**：无",
            0,
        ),
        (
            "字段标签带括号但无冒号（仍算缺失）",
            "## 评审：无冒号（2026-10-18）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：test.py\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**（机制类） 好\n\n**建议**：无\n\n**框架体感**：无",
            1,  # 铁律兼容无冒号 ⇒ 仍判缺字段
        ),
        # —— 以下 3 例为独立评审（2026-11-04）补的反例 ——
        (
            "反例：结论只含符号但档位词是胡说（旧实现误判合法）",
            "## 评审：胡说结论（2026-10-12）\n\n**结论**：✅ 完全胡说\n**矩阵定位**：甜品区\n\n**现有产物**：test.py\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "反例：现有产物为空且下一行含文件名（不得跨行吞）",
            "## 评审：跨行吞（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：甜品区\n\n**现有产物**：\n**业界参考**：见 README.md\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,  # 现有产物为空 ⇒ 1 条；「见 README.md」属业界参考，不得被当现有产物
        ),
        (
            "反例：矩阵定位含某档位词但不在开头",
            "## 评审：矩阵定位非开头（2026-10-12）\n\n**结论**：✅ 过\n**矩阵定位**：不是甜品区而是中间区\n\n**现有产物**：test.py\n**业界参考**：无成熟业界参考，阈值从本仓库数据提炼\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "反例：过不能前缀吞掉过去",
            "## 评审：过去（2026-11-04）\n\n**结论**：✅ 过去\n**矩阵定位**：甜品区\n\n**现有产物**：test.py\n**业界参考**：无\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
        (
            "反例：不过不能前缀吞掉不过去",
            "## 评审：不过去（2026-11-04）\n\n**结论**：❌ 不过去\n**矩阵定位**：甜品区\n\n**现有产物**：test.py\n**业界参考**：无\n\n**丰容价值**：高\n**节能价值**：中\n**平衡与风险**：低\n**铁律兼容**：好\n\n**建议**：无\n\n**框架体感**：无",
            1,
        ),
    ]

    passed = 0
    failed = 0
    for name, body, expected_violations in cases:
        violations = check_review("## 评审：测试", body)
        actual = len(violations)
        if actual == expected_violations:
            passed += 1
            print(f"  ✅ {name}（违规数={actual}，预期={expected_violations}）")
        else:
            failed += 1
            print(f"  ❌ {name}（违规数={actual}，预期={expected_violations}）")
            for v in violations:
                print(f"     - {v}")

    print(f"\n自检完成：{passed} 通过 / {failed} 失败（共 {len(cases)} 例）")
    return 1 if failed else 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    path = DEFAULT_LOG
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            path = Path(arg)
            break

    violations, output = lint(path)
    print(output)
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
