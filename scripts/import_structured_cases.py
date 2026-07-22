#!/usr/bin/env python3
"""从 worklog 和 report 中解析结构化 Case 并导入 EverOS。

三个数据源：
  1. Crucible worklog (79 个 .md): debug 反射 → Case(domain=crucible)
  2. Rome reports    (139 个 .md): 诊断/基准/优化 → Case(domain=rome)
  3. Rome results    (320 个 .json): 扫参实验 → Case(domain=rome)

每个文件解析为一个包含步骤、结果和追溯的 Case。
通过 /api/v1/memory/add 导入，以 agent_case 类型存储。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from everos.service.memorize import memorize

APP_ID = "opencode"
PROJECT_ID = "noctua"
USER_ID = "mengzhilu"
SENDER = "mengzhilu"

DRY_RUN = False
SLEEP = 0.5  # seconds between flushes


# ═══════════════════════════════════════════════════════════════════════
# 解析器：将 Markdown 文档解析为结构化字典
# ═══════════════════════════════════════════════════════════════════════


def parse_worklog(filepath: Path) -> dict | None:
    """解析 Crucible worklog 文件为 Case 字典。

    识别模式:
      - Process Tree: Problem → 根因 → 修复 → 验证 → 最终方案
      - Debugging Patterns / Anti-Patterns: 方法+反例+正确做法
      - ## 开头: 章节 = step
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    title_line = text.strip().split("\n")[0].lstrip("# ").strip()

    # 检测成功/失败信号
    success_signal = bool(re.search(r"✓|✔|成功|通过|PASS|fix|修复|解决", text))
    failure_signal = bool(re.search(r"✗|✘|×|失败|FAIL|bug|错误|问题", text)) and not success_signal
    status = "success" if success_signal else ("failure" if failure_signal else "unknown")

    # 提取步骤
    steps = []
    # 匹配 ## 开头的章节
    sections = re.split(r"\n(?=## )", text)
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        header_match = re.match(r"##\s+(.+)", sec)
        if not header_match:
            continue
        header = header_match.group(1).strip()
        steps.append({
            "action": header[:80],
            "content_preview": sec[:200].replace("\n", " "),
        })

    # 提取 tags
    tags = []
    tag_map = {
        "debug": r"(?i)(debug|调试|诊断|排查|troubleshoot)",
        "regression": r"(?i)(regression|回退|退化)",
        "fix": r"(?i)(fix|修复|解决|patch)",
        "migration": r"(?i)(migration|迁移|升级)",
        "oom": r"(?i)(OOM|内存|memory|显存)",
        "config": r"(?i)(config|配置|参数|yaml)",
        "e2e": r"(?i)(e2e|集成测试|end.to.end)",
    }
    for tag, pattern in tag_map.items():
        if re.search(pattern, text):
            tags.append(tag)

    return {
        "source": str(filepath),
        "case_id": f"case-{filepath.stem}",
        "domain": "crucible",
        "task": title_line,
        "status": status,
        "steps": steps,
        "step_count": len(steps),
        "section_count": len(re.findall(r"^### ", text, re.MULTILINE)),
        "tags": tags,
        "length": len(text),
    }


def parse_rome_report(filepath: Path) -> dict | None:
    """解析 Rome 报告为 Case 字典。

    识别模式:
      - 诊断报告: 问题 → 根因 → 证据 → 修复 → 验证
      - 基准测试: 配置 → 结果 → 分析
      - 优化实验: 基线 → 变量 → 结果 → 结论
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    title_line = text.strip().split("\n")[0].lstrip("# ").strip()

    if len(text) < 200:
        return None  # 太短，跳过

    success_signal = bool(re.search(r"✓|✔|通过|PASS|\+.*%|提升|改善|优化成功", text))
    status = "success" if success_signal else "analysis"

    # 提取关键指标
    metrics = {}
    # tokens/s 或 tok/s
    tps = re.findall(r"(\d+\.?\d*)\s*(?:tokens?/s|tok/s)", text)
    if tps:
        metrics["peak_tokens_per_second"] = max(float(v) for v in tps)
    # GPU 利用率
    gpu = re.findall(r"(\d+\.?\d*)%\s*(?:GPU|gpu).*?(?:util|利用率)", text)
    if gpu:
        metrics["peak_gpu_utilization_pct"] = max(float(v) for v in gpu)
    # 吞吐提升百分比
    improvement = re.findall(r"(\d+\.?\d*)x.*?(?:提升|improvement|throughput)", text)
    if not improvement:
        improvement = re.findall(r"提升.*?(\d+\.?\d*)x", text)
    if improvement:
        metrics["throughput_multiplier"] = max(float(v) for v in improvement)

    steps = []
    sections = re.split(r"\n(?=## )", text)
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        header_match = re.match(r"##\s+(.+)", sec)
        if not header_match:
            continue
        header = header_match.group(1).strip()
        steps.append({"action": header[:80]})

    # Tags
    tags = []
    tag_patterns = {
        "diagnosis": r"(?i)(诊断|diagnosis|根因|root cause)",
        "benchmark": r"(?i)(bench|基准|baseline|基线)",
        "optimization": r"(?i)(优化|optimization|调优|tuning)",
        "oom": r"(?i)(OOM|内存|memory|显存)",
        "latency": r"(?i)(延迟|latency|p50|p99)",
        "throughput": r"(?i)(吞吐|throughput|tokens?/s)",
        "batch": r"(?i)(batch|批处理|批量)",
    }
    for tag, pattern in tag_patterns.items():
        if re.search(pattern, text):
            tags.append(tag)

    model_match = re.search(r"(?:omni|Qwen|Omni)[\-\.]?\s*(\d+[A-Za-z]?)", text, re.IGNORECASE)
    model = model_match.group(0) if model_match else None

    return {
        "source": str(filepath),
        "case_id": f"case-{filepath.stem}",
        "domain": "rome",
        "task": title_line,
        "status": status,
        "steps": steps,
        "step_count": len(steps),
        "tags": tags,
        "model": model,
        "metrics": metrics,
        "length": len(text),
    }


def parse_rome_result(filepath: Path) -> dict | None:
    """解析 Rome 实验结果 JSON。"""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    return {
        "source": str(filepath),
        "case_id": f"case-{filepath.stem}",
        "domain": "rome",
        "task": f"Experiment: {filepath.stem}",
        "status": "success",
        "steps": [],
        "step_count": len(data) if isinstance(data, list) else 1,
        "tags": ["experiment", "benchmark"],
        "metrics": {},
        "length": filepath.stat().st_size,
    }


# ═══════════════════════════════════════════════════════════════════════
# Converter: Case dict → EverOS 消息（以结构化的 agent_case 格式存入）
# ═══════════════════════════════════════════════════════════════════════


def case_to_messages(case: dict) -> list[dict]:
    """将 Case 字典转换为用于 memorize 的消息列表。

    格式:
      user: [CASE] <domain>/<task>  →  触发 agent_case 提取
      user: [CASE_DATA] <json>     →  结构化数据作为消息体
    """
    now_ms = int(time.time() * 1000)
    tag_str = ", ".join(case.get("tags", []))
    metrics_str = json.dumps(case.get("metrics", {}), ensure_ascii=False) if case.get("metrics") else ""
    model_str = f" model={case['model']}" if case.get("model") else ""

    content = (
        f"[CASE] domain={case['domain']} status={case['status']}{model_str}\n"
        f"task: {case['task']}\n"
        f"tags: {tag_str}\n"
        f"steps: {case['step_count']} (code sections: {case.get('section_count', 0)})\n"
        f"source: {case['source']}\n"
        f"metrics: {metrics_str}\n"
        f"---\n"
        f"steps_detail: {json.dumps(case['steps'][:10], ensure_ascii=False)}"
    )

    return [
        {
            "sender_id": SENDER,
            "role": "user",
            "timestamp": now_ms,
            "content": content,
        },
    ]


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════


async def import_cases(
    cases: list[dict],
    label: str,
    app_id: str = APP_ID,
    project_id: str = PROJECT_ID,
) -> tuple[int, int]:
    """批量导入 Case 到 EverOS 记忆。

    Returns: (成功数, 跳过/失败数)
    """
    ok, skip = 0, 0
    for i, case in enumerate(cases):
        session_id = f"seed-case-{case['case_id']}"[:128]
        messages = case_to_messages(case)

        if DRY_RUN:
            ok += 1
            continue

        try:
            result = await memorize({
                "session_id": session_id,
                "app_id": app_id,
                "project_id": project_id,
                "messages": messages,
                "flush": True,
            })
            ok += 1
        except Exception as e:
            print(f"  ERR {case['case_id']}: {str(e)[:120]}")
            skip += 1
            await asyncio.sleep(1)

        await asyncio.sleep(SLEEP)

        if (i + 1) % 20 == 0:
            print(f"  [{label}] {i+1}/{len(cases)}: {ok} OK, {skip} errors")

    return ok, skip


async def main():
    print("=" * 60)
    print("  Noctua 结构化 Case 导入")
    print("=" * 60)
    if DRY_RUN:
        print("  *** DRY RUN — 仅解析，不写入 ***")
    print()

    all_cases = []

    # ── 数据源 1: Crucible worklog ──
    print("【数据源 1: Crucible worklog】")
    worklog_dir = ROOT / "crucible" / "worklog"
    wl_files = sorted(worklog_dir.rglob("*.md"))
    wl_cases = []
    for f in wl_files:
        case = parse_worklog(f)
        if case:
            wl_cases.append(case)
    print(f"  文件: {len(wl_files)}, 解析到 Case: {len(wl_cases)}")
    statuses = {}
    for c in wl_cases:
        statuses[c["status"]] = statuses.get(c["status"], 0) + 1
    print(f"  Status: {statuses}")
    tags = {}
    for c in wl_cases:
        for t in c.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    top_tags = dict(sorted(tags.items(), key=lambda x: -x[1])[:10])
    print(f"  Tags: {top_tags}")
    all_cases.extend(wl_cases)

    # ── 数据源 2: Rome reports ──
    print("\n【数据源 2: Rome reports】")
    reports_dir = ROOT / "rome" / "rubicon" / "docs" / "reports"
    rp_files = sorted(reports_dir.rglob("*.md"))
    rp_cases = []
    for f in rp_files:
        case = parse_rome_report(f)
        if case:
            rp_cases.append(case)
    print(f"  文件: {len(rp_files)}, 解析到 Case: {len(rp_cases)}")
    rp_statuses = {}
    for c in rp_cases:
        rp_statuses[c["status"]] = rp_statuses.get(c["status"], 0) + 1
    print(f"  Status: {rp_statuses}")
    rp_tags = {}
    for c in rp_cases:
        for t in c.get("tags", []):
            rp_tags[t] = rp_tags.get(t, 0) + 1
    top_rp_tags = dict(sorted(rp_tags.items(), key=lambda x: -x[1])[:10])
    print(f"  Tags: {top_rp_tags}")
    models = [c.get("model") for c in rp_cases if c.get("model")]
    print(f"  Models: {', '.join(sorted(set(models))[:8])}")
    all_cases.extend(rp_cases)

    # ── 数据源 3: Rome experiment results ──
    print("\n【数据源 3: Rome experiment results (JSON)】")
    results_dir = ROOT / "rome" / "rubicon" / "data" / "results"
    rs_files = sorted(results_dir.rglob("*.json"))[:50]  # cap at 50
    rs_cases = []
    for f in rs_files:
        case = parse_rome_result(f)
        if case:
            rs_cases.append(case)
    print(f"  采样文件: {len(rs_files)}, 解析到 Case: {len(rs_cases)}")
    all_cases.extend(rs_cases)

    # ── 汇总 ──
    print(f"\n{'=' * 60}")
    print(f"  总计: {len(all_cases)} 个 Case")
    print(f"    crucible: {len(wl_cases)}")
    print(f"    rome (reports): {len(rp_cases)}")
    print(f"    rome (results): {len(rs_cases)}")

    if DRY_RUN:
        # 打印前 5 个 case 预览
        print(f"\n【前 5 个 Case 预览】")
        for i, c in enumerate(all_cases[:5]):
            print(f"  {i}. [{c['domain']}] {c['task'][:60]}")
            print(f"     status={c['status']}, steps={c['step_count']}, tags={c['tags']}")
        return

    # ── 导入 ──
    print(f"\n导入中...")
    t0 = time.time()
    ok, skip = await import_cases(all_cases, "structured-cases")
    elapsed = time.time() - t0
    print(f"\n完成: {ok} OK, {skip} errors, 耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
