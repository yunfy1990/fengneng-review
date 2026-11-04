#!/usr/bin/env python3
"""丰容/节能评审闭环追踪机械闸（fengneng-review v1.7 评审闭环机制）。

扫描 review-log.md 中所有「⚠️ 有条件过」的评审，提取条件和截止日期，
检查条件是否到期未完成，到期未完成则 Surface（报告级，v1.7 前称 BLOCK），即将到期则 WARN。

基于控制论闭环模型（setpoint=评审条件硬谓词、sensor=本脚本）：
  - 只有「被采纳的承诺」才应写成条件（v1.7）
  - Type A（客观可检查）由本脚本自动验证；Type A 证据不得替代 Type B 价值判断
  - Type B（需人类判断）到期只提醒作者判断
  - Surface 动作：到期未完成时停止+报告+等指示，不自动重试/降级；
    作者的合法处置含延期/放弃/修正条件/停止追踪（停止追踪=正式结束）
  - ⚠️ 本闸实际作用 = wrap-up 体检报告标红 + 退出码非 0，
    **不阻断任何受控动作**（不拦提交/部署/发信/无关事项的收尾）
  - 确定性脚本不天然独立（v1.7）：本闸 = 可复跑检查，判据审查与独立执行角色另论

用法：python -X utf8 scripts/fengneng_review_followup.py [review-log 路径]
      python -X utf8 scripts/fengneng_review_followup.py --scan-todos <待办目录>  # 额外扫描评审闭环待办
      python -X utf8 scripts/fengneng_review_followup.py --scan-dirs <项目根目录>  # 提示未在评审记录中出现的一级目录
自检：python -X utf8 scripts/fengneng_review_followup.py --selftest
退出码：有 SURFACE（到期未完成）→ 1（报告级标红）；只有 WARN → 0；全部正常 → 0。

复盘触发两线（v1.11 机械判定，WARN 级只提示不裁决，不改退出码）：
  线① = 距上次框架复盘的**新增**评审 ≥ 5 条。基准 = 新增数，不是 review-log 总条数
        （v1.9 修正口径：同批 6 条里 2 条误用总数口径）。新增数 = 当前评审总条数 −
        最新复盘块内机器基线行 <!-- fengneng:baseline reviews=N --> 的 N；缺基线行时
        退化为「评审日期 > 复盘日」并显式 WARN 盲区（同日晚于复盘录入的条目不可见）。
  线② = 同一体感谱标签（评审「框架体感」里写 【体感谱：slug】）出现在 ≥2 条不同
        评审条目里——跨条目关联由闸做，治「同谱事件未自动关联」。
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LOG = Path(__file__).resolve().parent.parent.parent / "REVIEW_LOG.md"
# 项目根目录（用于「未评审目录」提示）；默认 None = 不扫描
PROJECT_ROOT = None

REVIEW_HEADER = re.compile(r"^#{2,3}\s+评审[：:]", re.M)
CONDITIONAL_MARK = "⚠️"

# 新建目录未评审检测的豁免名单：这些一级目录不是"个人项目/事务"，不需要丰容评审
#  - 系统/工具目录：.netlify/.qoder/.wrangler/.agents/.private 等
#  - 基础设施目录：scripts/journal/calendar/ledger/media-index 等（脚本库与基础设施目录本身不是项目）
#  - 其余目录一律当作候选：机械闸只负责把候选摆上桌，由作者判断是否需要补评
EXEMPT_TOP_DIRS = {
    ".netlify", ".qoder", ".wrangler", ".git", ".agents", ".private",
    "scripts", "journal", "calendar", "ledger", "media-index",
    "Downloading", "Extracting", "tmp", "temp", "node_modules",
}
# 匹配条件行：- C1（Type A，截止2026-10-31）：描述
CONDITION_LINE = re.compile(
    r"-\s+(C\d+)[（(](Type\s*[AB])[，,]\s*截止\s*(\d{4}-\d{2}-\d{2})[）)]\s*[：:]\s*(.+?)(?:\n|$)"
)
# 匹配已完成/已终态条件：- C1（Type A，已完成✅）/ - C1（Type A，已停止）
# v1.7：停止追踪/放弃是合法终态，不再 Surface
CONDITION_DONE = re.compile(
    r"-\s+(C\d+)[（(](Type\s*[AB])[，,]\s*(?:已完成✅?|已停止|已放弃|停止追踪)[）)]"
)
# v1.7 复核修订（另一协作方独立核对）：终态判定改用受约束标记，不再用自由描述子串——
# 反例：「尚未完成，请作者决定是否停止追踪」含「停止追踪」会被误核销；任意 ✅ 同禁。
# 条目级：闭环状态 = stopped / closed / not-applicable ⇒ 整条不再追踪（历史条件保留但不报警）
# 条件级终态 = 括号状态位（CONDITION_DONE）｜【已完成】【已停止】【已放弃】【停止追踪】专用标记
# 建议级：描述含【未采纳】/【仅建议】标记 ⇒ 未获采纳的建议，不追踪也不记完成（历史建议存档）
# v1.7 二次复核修订：删除自由文本「已完成」分支——负向后顾无法消除语义误判
# （反例：「若已完成则归档，目前尚未验证」「完成标准：报告显示已完成；当前仍待验证」均误匹配）。
# 状态只认括号状态位/【】标记；既有真实完成记录显式迁移为【已完成】，不用自由语句猜状态。
ENTRY_TERMINAL = ("stopped", "closed", "not-applicable")
DONE_PHRASE = re.compile(r"【(?:已完成|已停止|已放弃|停止追踪)】")
NOT_ADOPTED = re.compile(r"【(?:未采纳|仅建议)[^】]*】")
# 匹配闭环状态行
CLOSE_LOOP_STATUS = re.compile(r"\*\*闭环状态\*\*[：:]\s*(.+?)(?:\n|$)")

# 评审闭环待办：### T1：名称（Type A/B，截止 YYYY-MM-DD）
TODO_HEADER = re.compile(r"^#{3,4}\s+T(\d+)[：:]\s*.*?[（(](Type\s*[AB])[，,]\s*截止\s*(\d{4}-\d{2}-\d{2})[）)]", re.M)
TODO_STATUS_OPEN = re.compile(r"-\s*状态[：:]\s*open")
TODO_STATUS_DONE = re.compile(r"-\s*状态[：:]\s*(?:已完成|done|closed|closed✅|✅|stopped|已停止|已放弃|停止追踪)")

SURFACE_WINDOW_DAYS = 7  # 7天内到期 → WARN

# ---- 复盘触发两线（v1.11 机械判定）----
RETRO_TRIGGER_NEW = 5  # 线①：距上次复盘新增 ≥5 条
# 框架复盘记录头：## 框架复盘记录（2026-10-24 · 第三轮 · v1.8 → v1.9）
RETRO_HEADER = re.compile(r"^#{1,3}\s+框架复盘记录[（(](\d{4}-\d{2}-\d{2})", re.M)
# 机器基线行（写在该复盘块内）：<!-- fengneng:baseline reviews=43 date=2026-10-24 -->
BASELINE_MARK = re.compile(
    r"<!--\s*fengneng:baseline\s+reviews=(\d+)(?:\s+date=(\d{4}-\d{2}-\d{2}))?\s*-->"
)
# 体感谱标签：评审「框架体感」里写 【体感谱：slug】
GANSHOU_TAG = re.compile(r"【体感谱[：:]\s*([^】\n]+?)\s*】")
DATE_ANY = re.compile(r"(\d{4}-\d{2}-\d{2})")


def split_reviews(text):
    """按 '## 评审：' 切分，返回 (header, body) 列表。"""
    matches = list(REVIEW_HEADER.finditer(text))
    reviews = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        header_line = text[m.start():text.find("\n", m.start())].strip()
        body = text[start:end]
        reviews.append((header_line, body))
    return reviews


def parse_conditions(body):
    """从评审条目中解析条件列表，返回 [(condition_id, type, deadline, desc, done)]。"""
    conditions = []
    # 已完成的条件
    done_ids = set()
    for m in CONDITION_DONE.finditer(body):
        done_ids.add(m.group(1))
    # 有截止日期的条件
    for m in CONDITION_LINE.finditer(body):
        cid = m.group(1)
        ctype = m.group(2).replace(" ", "")
        deadline = datetime.strptime(m.group(3), "%Y-%m-%d").date()
        desc = m.group(4).strip()
        not_adopted = bool(NOT_ADOPTED.search(desc))
        done = cid in done_ids or bool(DONE_PHRASE.search(desc))
        conditions.append((cid, ctype, deadline, desc, done, not_adopted))
    return conditions


def check_review(header, body, today):
    """检查单个评审条目的条件状态，返回 (blocks, warns, infos)。"""
    blocks = []
    warns = []
    infos = []

    if CONDITIONAL_MARK not in body:
        return blocks, warns, infos

    # 闭环状态（v1.7 复核修订：条目级终态控制跟踪——stopped/closed/not-applicable ⇒ 整条不再追踪，
    # 历史条件与截止原样保留但不报警；修复"只改状态仍按过期条件 Surface"的漏洞）
    status_m = CLOSE_LOOP_STATUS.search(body)
    status = status_m.group(1).strip() if status_m else "未标注"
    status_head = status.split("（")[0].strip().lower()
    if status_head in ENTRY_TERMINAL:
        infos.append(f"  ⏹️ {header}：闭环状态={status_head}（条目终态，历史条件不再追踪）")
        return blocks, warns, infos

    conditions = parse_conditions(body)
    if not conditions:
        # 有条件过但没有解析到硬谓词条件 → v1.5前的旧格式，WARN
        warns.append(f"  ⚠️ {header}：有条件过但未找到v1.5硬谓词条件（可能是旧格式，建议回溯补全）")
        return blocks, warns, infos

    for cid, ctype, deadline, desc, done, not_adopted in conditions:
        if not_adopted:
            infos.append(f"  ⏸️ {header} {cid}（{ctype}）未采纳建议（不追踪，待作者定夺）：{desc[:40]}")
            continue
        if done:
            infos.append(f"  ✅ {header} {cid}（{ctype}）已完成：{desc[:40]}")
            continue

        days_left = (deadline - today).days
        if days_left < 0:
            # 已过期
            if ctype == "TypeA":
                blocks.append(
                    f"  🚨 SURFACE（报告级）{header} {cid}（Type A）已过期 {abs(days_left)} 天："
                    f"截止 {deadline}，{desc[:50]}\n"
                    f"    → 停止、报告、等作者指示（不自动重试/降级/改宽松；本闸不阻断任何受控动作）"
                )
            else:
                # Type B 过期也 Surface（需要作者判断）
                blocks.append(
                    f"  🚨 SURFACE（报告级）{header} {cid}（Type B）已过期 {abs(days_left)} 天："
                    f"截止 {deadline}，{desc[:50]}\n"
                    f"    → 需作者判断：延期？放弃？修正条件？停止追踪？（停止追踪=合法终态）"
                )
        elif days_left <= SURFACE_WINDOW_DAYS:
            warns.append(
                f"  ⏰ WARN {header} {cid}（{ctype}）{days_left} 天后到期（{deadline}）：{desc[:50]}"
            )
        else:
            infos.append(f"  📋 {header} {cid}（{ctype}）{days_left} 天后到期：{desc[:40]}")

    return blocks, warns, infos


def scan_unreviewed_dirs(root, log_text):
    """扫描仓内一级目录，找出未在评审日志中出现的目录（可能是漏评的新项目）。

    豁免：系统/工具目录、基础设施目录、域层容器、记录层（见 EXEMPT_TOP_DIRS）。
    匹配：目录名作为子串出现在评审日志全文（标题或正文）中即视为已覆盖。
    返回：未评审目录列表。注意——这是提示器不是判决：有些目录是纯材料归档，
    天然不需要评审；机械闸只负责把候选摆上桌，由作者判断是否需要补评。
    """
    if root is None:
        return []
    unreviewed = []
    for entry in sorted(Path(root).iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name in EXEMPT_TOP_DIRS:
            continue
        if name.startswith("."):
            continue
        if name in log_text:
            continue
        unreviewed.append(name)
    return unreviewed


def scan_todos(todo_dir, today):
    """扫描待办目录下的评审闭环待办账（对抗性审查 / 内容摇落 / 周期复盘 等的评审闭环待办）。

    识别：正文含 `### T<N>：...（Type A/B，截止 YYYY-MM-DD）`。
    解析每个 T 待办的截止、类型、状态（open/done），与丰容评审同款 BLOCK/WARN 逻辑。
    返回 (blocks, warns, infos, todo_count)。
    """
    blocks, warns, infos = [], [], []
    todo_count = 0
    if todo_dir is None or not Path(todo_dir).is_dir():
        return blocks, warns, infos, todo_count

    for f in sorted(Path(todo_dir).glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if "type: review-todo" not in text:
            continue
        # 只处理有 T 待办头的账
        matches = list(TODO_HEADER.finditer(text))
        if not matches:
            warns.append(f"  ⚠️ {f.name}：type: review-todo 但未找到 T 待办硬谓词头（格式不符，建议修正）")
            continue

        # 账内所有待办是否含 open 状态：默认 open（未标状态行视为 open，但已完成账会有 done 行）
        f_text = f.name
        for m in matches:
            tid = m.group(1)
            ttype = m.group(2).replace(" ", "")
            deadline = datetime.strptime(m.group(3), "%Y-%m-%d").date()
            todo_count += 1
            # 待办状态行取该 T 段内（下一个 T 头或文件尾之间）的状态
            seg_start = m.start()
            seg_end = matches[matches.index(m) + 1].start() if matches.index(m) + 1 < len(matches) else len(text)
            seg = text[seg_start:seg_end]
            if TODO_STATUS_DONE.search(seg):
                infos.append(f"  ✅ {f_text} T{tid}（{ttype}）已完成")
                continue
            if not TODO_STATUS_OPEN.search(seg):
                # 没有显式 open 状态行——视为 open（机械闸追踪中）
                pass

            days_left = (deadline - today).days
            if days_left < 0:
                if ttype == "TypeA":
                    blocks.append(
                        f"  🚨 SURFACE（报告级）{f_text} T{tid}（Type A）已过期 {abs(days_left)} 天："
                        f"截止 {deadline}\n    → 停止、报告、等作者指示（不自动重试/降级；本闸不阻断任何受控动作）"
                    )
                else:
                    blocks.append(
                        f"  🚨 SURFACE（报告级）{f_text} T{tid}（Type B）已过期 {abs(days_left)} 天："
                        f"截止 {deadline}\n    → 需作者判断：延期？放弃？修正条件？停止追踪？"
                    )
            elif days_left <= SURFACE_WINDOW_DAYS:
                warns.append(
                    f"  ⏰ WARN {f_text} T{tid}（{ttype}）{days_left} 天后到期（{deadline}）"
                )
            else:
                infos.append(f"  📋 {f_text} T{tid}（{ttype}）{days_left} 天后到期（{deadline}）")

    return blocks, warns, infos, todo_count


def review_date_of(header):
    """从评审标题行提取 (YYYY-MM-DD) 日期；无日期返回 None。"""
    m = DATE_ANY.search(header)
    return datetime.strptime(m.group(1), "%Y-%m-%d").date() if m else None


def latest_retro(text):
    """找最新的框架复盘，返回 (复盘日期, 机器基线 reviews|None)；没有复盘返回 None。

    基线标记只在该复盘块内找（块 = 本复盘头到下一个复盘头；复盘块都在文件头部，
    评审条目追加在尾部，不会误吸评审正文里的同形注释）。
    """
    best = None
    matches = list(RETRO_HEADER.finditer(text))
    for i, m in enumerate(matches):
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if best is not None and d <= best[0]:
            continue
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bm = BASELINE_MARK.search(text, m.end(), block_end)
        best = (d, int(bm.group(1)) if bm else None)
    return best


def check_retro_trigger(text):
    """复盘触发两线机械判定，返回 (warns, infos)。WARN 级：只提示不裁决，不改退出码。

    线①：距上次框架复盘新增评审 ≥5 条（基准 = 新增数，不是总条数——v1.9 修正口径）。
          新增数优先按机器基线行算（总条数 − 基线 N）；缺基线行退化按日期，并 WARN 盲区。
    线②：同一体感谱标签出现在 ≥2 条不同评审条目里。
    """
    warns, infos = [], []
    total = len(list(REVIEW_HEADER.finditer(text)))
    retro = latest_retro(text)
    if retro is None:
        new, basis = total, "从未复盘，新增 = 总条数"
    else:
        rdate, base = retro
        if base is not None:
            new = total - base
            basis = "机器基线 reviews=%d（%s 复盘）→ 新增 = %d−%d" % (base, rdate, total, base)
        else:
            new = sum(
                1 for h, _ in split_reviews(text)
                if (review_date_of(h) or date.min) > rdate
            )
            basis = "无机器基线行，退化按评审日期 > 复盘日 %s 估算" % rdate
            warns.append(
                f"  ⚠️ 最新框架复盘（{rdate}）缺机器基线行 <!-- fengneng:baseline reviews=N -->："
                "新增数退化为按日期估算，同日晚于复盘录入的评审不可见（盲区）——下次复盘补基线行可消除"
            )
    infos.append(f"  📊 复盘触发线①：距上次框架复盘新增 {new} 条评审（基准=新增数，不是总条数；{basis}）")
    if new >= RETRO_TRIGGER_NEW:
        warns.append(
            f"  🔁 复盘触发线①：距上次框架复盘新增 {new} 条 ≥ {RETRO_TRIGGER_NEW} 条"
            "—— 建议框架复盘（作者主导，agent 辅助汇总体感）"
        )
    slug_reviews = {}
    for header, body in split_reviews(text):
        for m in GANSHOU_TAG.finditer(body):
            slug_reviews.setdefault(m.group(1), set()).add(header)
    for slug in sorted(slug_reviews):
        revs = slug_reviews[slug]
        if len(revs) >= 2:
            warns.append(
                f"  🔁 复盘触发线②：体感谱「{slug}」在 {len(revs)} 条评审中重复出现"
                " —— 达第二条触发线（v1.9），建议框架复盘"
            )
    if slug_reviews:
        infos.append("  📊 体感谱登记：" + "、".join(
            f"「{s}」×{len(slug_reviews[s])}" for s in sorted(slug_reviews)))
    return warns, infos


def run(log_path, today=None):
    """主运行逻辑，返回 (blocks, warns, infos, review_count)。"""
    if today is None:
        today = date.today()
    text = Path(log_path).read_text(encoding="utf-8")
    reviews = split_reviews(text)

    all_blocks = []
    all_warns = []
    all_infos = []
    conditional_count = 0

    # 未评审目录检测（提示器，WARN 级）
    unreviewed = scan_unreviewed_dirs(PROJECT_ROOT, text) if PROJECT_ROOT else []
    if unreviewed:
        all_warns.append(
            f"  🆕 WARN 以下一级目录未在评审日志中出现（若为新项目请补丰容评审；"
            f"纯材料/记录归档可忽略）：{'、'.join(unreviewed)}"
        )

    for header, body in reviews:
        if CONDITIONAL_MARK not in body:
            continue
        conditional_count += 1
        b, w, i = check_review(header, body, today)
        all_blocks.extend(b)
        all_warns.extend(w)
        all_infos.extend(i)

    # 复盘触发两线（v1.11 机械判定，WARN 级不改退出码）
    r_warns, r_infos = check_retro_trigger(text)
    all_warns.extend(r_warns)
    all_infos.extend(r_infos)

    return all_blocks, all_warns, all_infos, conditional_count


def selftest():
    """自检：用夹具验证解析逻辑。"""
    print("=== fengneng_review_followup 自检 ===")
    failures = []

    # 夹具1：正常有条件过，含已完成和未完成条件
    fixture1 = """### 评审：测试项目（2026-10-14）

**结论**：⚠️ 有条件过
**矩阵定位**：中间区
**闭环状态**：open（C1未满足）

**条件（v1.5硬谓词）**：
- C1（Type A，截止2026-10-31）：测试条件一
- C2（Type A，已完成✅）：测试条件二
- C3（Type B，截止2026-11-15）：测试条件三
"""
    today = date(2026, 10, 14)
    b, w, i, cnt = run_fixture(fixture1, today)
    if cnt != 1:
        failures.append(f"夹具1：期望1个有条件过，实际{cnt}")
    if len(b) != 0:
        failures.append(f"夹具1：期望0个BLOCK，实际{len(b)}")
    # C1 还有17天，C3还有32天，都不在7天窗口内
    if len(w) != 0:
        failures.append(f"夹具1：期望0个WARN，实际{len(w)}：{w}")
    if len(i) != 2:  # C1+C3未完成，C2已完成
        failures.append(f"夹具1：期望2个info（未完成条件），实际{len(i)}")

    # 夹具2：条件已过期
    fixture2 = """### 评审：过期项目（2026-10-01）

**结论**：⚠️ 有条件过
**闭环状态**：open

**条件（v1.5硬谓词）**：
- C1（Type A，截止2026-10-10）：过期条件
"""
    b, w, i, cnt = run_fixture(fixture2, today)
    if len(b) != 1:
        failures.append(f"夹具2：期望1个SURFACE（过期），实际{len(b)}")
    if "SURFACE" not in b[0] if b else True:
        failures.append("夹具2：SURFACE消息格式不对")

    # 夹具3：7天内到期 → WARN
    fixture3 = """### 评审：临期项目（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.5硬谓词）**：
- C1（Type A，截止2026-10-18）：4天后到期
"""
    b, w, i, cnt = run_fixture(fixture3, today)
    if len(w) != 1:
        failures.append(f"夹具3：期望1个WARN（4天到期），实际{len(w)}")
    if len(b) != 0:
        failures.append(f"夹具3：期望0个BLOCK，实际{len(b)}")

    # 夹具4：无条件过的项目不检查
    fixture4 = """### 评审：通过项目（2026-10-14）

**结论**：✅ 过
**矩阵定位**：甜品区
"""
    b, w, i, cnt = run_fixture(fixture4, today)
    if cnt != 0:
        failures.append(f"夹具4：期望0个有条件过，实际{cnt}")

    # 夹具5：旧格式（有条件过但无硬谓词）→ WARN
    fixture5 = """### 评审：旧格式项目（2026-10-12）

**结论**：⚠️ 有条件过
**建议**：有条件过。条件：①做某事②做另一件事
"""
    b, w, i, cnt = run_fixture(fixture5, today)
    if len(w) != 1:
        failures.append(f"夹具5：期望1个WARN（旧格式），实际{len(w)}")

    # 夹具6：未评审目录检测——被评审覆盖的目录不报，未覆盖的报
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 已评审目录名出现在 log_text 中
        (root / "2026-10投资SOP").mkdir()
        (root / "2026-10饮食").mkdir()
        # 未评审目录
        (root / "2026-11新项目").mkdir()
        # 豁免目录不报
        (root / "scripts").mkdir()
        (root / "个人档案").mkdir()
        # 隐藏目录不报
        (root / ".wrangler").mkdir()
        log_text = "评审：投资SOP（2026-10投资SOP）\n评审：饮食体系（2026-10饮食）\n评审：档案（个人档案）"
        unrev = scan_unreviewed_dirs(root, log_text)
        if unrev != ["2026-11新项目"]:
            failures.append(f"夹具6：期望只报 [2026-11新项目]，实际 {unrev}")

    # 夹具7：评审闭环待办扫描——open 过期 SURFACE、done 不计、无 T 待办头的账不扫
    with tempfile.TemporaryDirectory() as td:
        todo_dir = Path(td)
        (todo_dir / "2026-10-14-300-对抗审查修复-测试项目.md").write_text(
            "---\nstatus: open\ntype: review-todo\n---\n\n## 评审待办（硬谓词）\n\n"
            "### T1：修复X（Type A，截止 2026-10-10）\n- 完成标准：xxx\n- 状态：open\n\n"
            "### T2：修复Y（Type A，截止 2026-11-01）\n- 完成标准：yyy\n- 状态：open\n",
            encoding="utf-8",
        )
        (todo_dir / "2026-10-14-301-内容摇落修复-测试物.md").write_text(
            "---\nstatus: open\ntype: review-todo\n---\n\n## 评审待办（硬谓词）\n\n"
            "### T1：改论点（Type B，截止 2026-11-10）\n- 完成标准：zzz\n- 状态：已完成✅\n",
            encoding="utf-8",
        )
        (todo_dir / "2026-10-14-302-普通账.md").write_text(
            "---\nstatus: open\ntype: task\n---\n\n普通任务，非评审待办\n",
            encoding="utf-8",
        )
        (todo_dir / "2026-10-15-303-停止追踪账.md").write_text(
            "---\nstatus: open\ntype: review-todo\n---\n\n## 评审待办（硬谓词）\n\n"
            "### T1：某待办（Type A，截止 2026-10-01）\n- 完成标准：xxx\n- 状态：停止追踪\n",
            encoding="utf-8",
        )
        b, w, i, cnt = scan_todos(todo_dir, today)
        if cnt != 4:  # T1/T2（红蓝） + T1（shakedown） + T1（停止追踪账）
            failures.append(f"夹具7：期望4个待办，实际{cnt}")
        # T1 已过期（截止10-10 < today 10-14）→ SURFACE；T2 11-01 未到窗口；shakedown T1 已完成；停止追踪账 T1 终态
        if len(b) != 1:
            failures.append(f"夹具7：期望1个SURFACE（T1过期），实际{len(b)}：{b}")
        if len(i) != 3:  # T2 进行中 + shakedown T1 已完成 + 停止追踪账 T1 终态
            failures.append(f"夹具7：期望3个info，实际{len(i)}：{i}")

    # 夹具8（v1.7）：停止追踪/放弃 = 合法终态，不 Surface、不计 BLOCK
    fixture8 = """### 评审：停止追踪项目（2026-10-14）

**结论**：⚠️ 有条件过
**闭环状态**：open（条件见下）

**条件（v1.7硬谓词）**：
- C1（Type A，已停止）：原条件一（作者拍板放弃）
- C2（Type B，截止2026-10-10）：【停止追踪】原条件二——作者已拍板放弃整条决策
"""
    b, w, i, cnt = run_fixture(fixture8, today)
    if len(b) != 0:
        failures.append(f"夹具8：期望0个SURFACE（已停止追踪），实际{len(b)}：{b}")
    # C1 为「已停止」无截止行 → 不再解析追踪（跳过）；C2 描述带【停止追踪】受约束标记 → 记终态 info
    if len(i) != 1:
        failures.append(f"夹具8：期望1个info（C2 记终态，C1 无截止行跳过），实际{len(i)}：{i}")

    # 夹具9（v1.7复核）：条目级终态——闭环状态 stopped ⇒ 历史条件（含已过期）不再报警
    fixture9 = """### 评审：条目级停止（2026-10-14）

**结论**：⚠️ 有条件过
**闭环状态**：stopped（条件未获采纳，历史建议存档）

**条件（v1.7硬谓词）**：
- C1（Type A，截止2026-10-10）：已过期但条目已终止的条件
"""
    b, w, i, cnt = run_fixture(fixture9, today)
    if len(b) != 0:
        failures.append(f"夹具9：期望0个SURFACE（条目 stopped），实际{len(b)}：{b}")
    if len(i) != 1:
        failures.append(f"夹具9：期望1个info（条目终态说明），实际{len(i)}：{i}")

    # 夹具10（v1.7复核）：否定语境不误核销——「尚未完成，请作者决定是否停止追踪」仍应 Surface
    fixture10 = """### 评审：否定语境（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.7硬谓词）**：
- C1（Type A，截止2026-10-10）：尚未完成，请作者决定是否停止追踪
"""
    b, w, i, cnt = run_fixture(fixture10, today)
    if len(b) != 1:
        failures.append(f"夹具10：期望1个SURFACE（否定语境不核销），实际{len(b)}：{b}")

    # 夹具11（v1.7复核）：未采纳建议标记——【未采纳】不追踪、不报警、也不记完成
    fixture11 = """### 评审：未采纳建议（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.7硬谓词）**：
- C1（Type B，截止2026-10-10）：某条评审建议【未采纳·仅建议存档】
"""
    b, w, i, cnt = run_fixture(fixture11, today)
    if len(b) != 0:
        failures.append(f"夹具11：期望0个SURFACE（未采纳不追踪），实际{len(b)}：{b}")
    if len(i) != 1:
        failures.append(f"夹具11：期望1个info（⏸️ 未采纳），实际{len(i)}：{i}")

    # 夹具12（v1.7复核）：「讨论停止追踪但未决定」无受约束终态标记 ⇒ 仍追踪（过期即 Surface）
    fixture12 = """### 评审：讨论未决（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.7硬谓词）**：
- C1（Type A，截止2026-10-10）：讨论停止追踪但未决定
"""
    b, w, i, cnt = run_fixture(fixture12, today)
    if len(b) != 1:
        failures.append(f"夹具12：期望1个SURFACE（讨论停止≠已停止），实际{len(b)}：{b}")

    # 夹具13（v1.7二次复核，反例）：「若已完成则归档」是假设句不是完成状态 ⇒ 不误核销
    fixture13 = """### 评审：假设语境（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.7硬谓词）**：
- C1（Type A，截止2026-10-10）：若已完成则归档，目前尚未验证
"""
    b, w, i, cnt = run_fixture(fixture13, today)
    if len(b) != 1:
        failures.append(f"夹具13：期望1个SURFACE（假设句不核销），实际{len(b)}：{b}")

    # 夹具14（v1.7二次复核，反例）：「报告显示已完成；当前仍待验证」是转述目标不是完成状态 ⇒ 不误核销
    fixture14 = """### 评审：转述语境（2026-10-14）

**结论**：⚠️ 有条件过

**条件（v1.7硬谓词）**：
- C1（Type A，截止2026-10-10）：完成标准：报告显示已完成；当前仍待验证
"""
    b, w, i, cnt = run_fixture(fixture14, today)
    if len(b) != 1:
        failures.append(f"夹具14：期望1个SURFACE（转述句不核销），实际{len(b)}：{b}")

    # ---- 复盘触发两线（v1.11 机械判定）----

    # 夹具15：机器基线行口径——新增 = 总条数 − 基线，不是总条数
    fixture15 = """## 框架复盘记录（2026-10-24 · 第三轮 · v1.8 → v1.9）

**计数基线**：本条之后计数归零。
<!-- fengneng:baseline reviews=3 date=2026-10-24 -->

### 评审：项目甲（2026-10-25）

### 评审：项目乙（2026-10-25）

### 评审：项目丙（2026-10-26）

### 评审：项目丁（2026-10-26）

### 评审：项目戊（2026-10-27）
"""
    w, i = check_retro_trigger(fixture15)
    if any("触发线①" in x for x in w):
        failures.append(f"夹具15：基线3+新5条 → 新增2？错。期望新增=5−3=2 不触发，实际：{w}")
    if not any("新增 2 条" in x for x in i):
        failures.append(f"夹具15：期望 info 报「新增 2 条」（不是总条数5），实际：{i}")
    if any("缺机器基线行" in x for x in w):
        failures.append(f"夹具15：有基线行不应报盲区，实际：{w}")
    # 同一夹具再加 3 条 → 新增 5 → 触发线①
    fixture15b = fixture15 + "\n### 评审：项目己（2026-10-27）\n\n### 评审：项目庚（2026-10-28）\n\n### 评审：项目辛（2026-10-28）\n"
    w, i = check_retro_trigger(fixture15b)
    if not any("触发线①" in x and "新增 5 条" in x for x in w):
        failures.append(f"夹具15b：新增5条应触发线①，实际：{w}")

    # 夹具16：缺基线行 → 退化按日期 + 盲区 WARN；同日晚于复盘的条目不可见（如实报盲区）
    fixture16 = """## 框架复盘记录（2026-10-24 · 第三轮）

### 评审：旧条目（2026-10-20）

### 评审：同日晚录（2026-10-24）

### 评审：次日甲（2026-10-25）

### 评审：次日乙（2026-10-26）
"""
    w, i = check_retro_trigger(fixture16)
    if not any("缺机器基线行" in x for x in w):
        failures.append(f"夹具16：缺基线行应报盲区 WARN，实际：{w}")
    if not any("新增 2 条" in x for x in i):
        failures.append(f"夹具16：退化口径期望新增2（同日的10-24不可见），实际：{i}")

    # 夹具17：体感谱——≥2 条不同评审同 slug 触发线②；同一条目内重复不算
    fixture17 = """### 评审：项目一（2026-10-25）

**框架体感**：确认式落账被自己打穿 【体感谱：确认式落账】

### 评审：项目二（2026-10-26）

**框架体感**：又是口径自证 【体感谱：确认式落账】

### 评审：项目三（2026-10-26）

**框架体感**：单条内说两遍 【体感谱：孤立谱】【体感谱：孤立谱】
"""
    w, i = check_retro_trigger(fixture17)
    if not any("触发线②" in x and "确认式落账" in x and "2 条评审" in x for x in w):
        failures.append(f"夹具17：同谱2条评审应触发线②，实际：{w}")
    if any("孤立谱" in x and "触发线②" in x for x in w):
        failures.append(f"夹具17：同一条目内重复不应触发，实际：{w}")
    if not any("体感谱登记" in x and "孤立谱」×1" in x for x in i):
        failures.append(f"夹具17：登记应把孤立谱计为1条评审，实际：{i}")

    # 夹具18：从未复盘 → 新增 = 总条数，满 5 即触发
    fixture18 = "\n".join(f"### 评审：项目{n}（2026-10-1{n}）" for n in range(5)) + "\n"
    w, i = check_retro_trigger(fixture18)
    if not any("触发线①" in x and "新增 5 条" in x for x in w):
        failures.append(f"夹具18：从未复盘5条应触发线①，实际：{w}")
    if not any("从未复盘" in x for x in i):
        failures.append(f"夹具18：期望 basis=从未复盘，实际：{i}")
    # 0 条目也不崩
    w, i = check_retro_trigger("没有任何评审。")
    if not any("新增 0 条" in x for x in i):
        failures.append(f"夹具18b：空日志期望新增0，实际：{i}")

    if failures:
        print(f"❌ 自检失败：{len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"✅ 自检通过（14项条件夹具 + 4组复盘触发夹具全部通过）")
    return 0


def run_fixture(text, today):
    """在夹具文本上运行检查逻辑（不读文件）。"""
    reviews = split_reviews(text)
    all_blocks, all_warns, all_infos = [], [], []
    conditional_count = 0
    for header, body in reviews:
        if CONDITIONAL_MARK not in body:
            continue
        conditional_count += 1
        b, w, i = check_review(header, body, today)
        all_blocks.extend(b)
        all_warns.extend(w)
        all_infos.extend(i)
    return all_blocks, all_warns, all_infos, conditional_count


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(selftest())

    todo_dir = None
    project_root = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--scan-todos" and i + 1 < len(args):
            todo_dir = args[i + 1]
            i += 2
            continue
        if a == "--scan-dirs" and i + 1 < len(args):
            project_root = args[i + 1]
            i += 2
            continue
        positional.append(a)
        i += 1
    args = positional

    log_path = Path(args[0]) if args and not args[0].startswith("--") else DEFAULT_LOG
    if not log_path.exists():
        print(f"❌ 评审日志不存在：{log_path}", file=sys.stderr)
        sys.exit(2)

    today = date.today()
    blocks, warns, infos, conditional_count = run(log_path, today)

    print(f"=== 丰容/节能评审闭环追踪 ===")
    print(f"评审日志：{log_path}")
    print(f"今日：{today}")
    print(f"有条件过的评审：{conditional_count} 个")
    print()

    if todo_dir:
        l_blocks, l_warns, l_infos, todo_count = scan_todos(todo_dir, today)
        print(f"--- 评审闭环待办（{todo_dir}）---")
        print(f"扫描目录：{todo_dir}")
        print(f"硬谓词待办：{todo_count} 个")
        blocks.extend(l_blocks)
        warns.extend(l_warns)
        infos.extend(l_infos)
        print()

    if blocks:
        print(f"🚨 SURFACE（{len(blocks)} 个，报告级——需作者指示，不阻断受控动作）：")
        for b in blocks:
            print(b)
        print()

    if warns:
        print(f"⏰ WARN（{len(warns)} 个，{SURFACE_WINDOW_DAYS}天内到期或旧格式）：")
        for w in warns:
            print(w)
        print()

    if infos:
        print(f"📋 进行中（{len(infos)} 个条件/待办）：")
        for i in infos:
            print(i)
        print()

    if not blocks and not warns and not infos:
        print("✅ 所有评审条件/待办均已完成或无截止日期约束")

    if blocks:
        print(f"❌ 有 {len(blocks)} 个条件/待办已过期未完成 → 退出码1（报告级标红，不阻断受控动作；需 Surface 给作者）")
        sys.exit(1)
    else:
        print("✅ 无过期未完成条件/待办 → 退出码0")
        sys.exit(0)


if __name__ == "__main__":
    main()
