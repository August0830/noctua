#!/usr/bin/env python3
"""从已有执行轨迹中采样，输出结构化数据效果，边看边调 Schema。

用法：
  python scripts/sample_trajectories.py              # 采样全部已有数据
  python scripts/sample_trajectories.py --run <id>   # 只看某一次 run
  python scripts/sample_trajectories.py --json       # 仅输出 JSON，不打印统计
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "runs"

sys.path.insert(0, str(ROOT / "src"))
from noctua.schemas import (
    AgentCase, AgentCaseStep, ProvenanceRef,
    Skill, SkillApplicability,
    TrainingSample, TrainingMessage, TrainingDataset,
)


def parse_frontmatter(text: str) -> dict[str, str]:
    """解析 Markdown 文件中的 YAML-like 元数据块。

    格式：每行 `key: value`，从包含 `>` 的第一行开始，
    到第一个空行或 `---` 结束。
    """
    meta = {}
    lines = text.strip().split("\n")
    started = False
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            started = True
            # 提取引用的 meta 行
            # "> **Plan ID:** `xxx`" → plan_id: xxx
            inner = s.lstrip("> ").strip()
            m = re.match(r"\*\*([^:]+):?\*\*\s*(.+)", inner)
            if m:
                key = m.group(1).lower().replace(" ", "_").replace("-", "_")
                val = m.group(2).strip().strip("`") 
                meta[key] = val
            continue
        if started and s == "":
            break
        if ":" in s and not s.startswith("#") and not s.startswith("|") and not s.startswith("-"):
            key, _, val = s.partition(":")
            meta[key.strip().lower().replace(" ", "_")] = val.strip()
    return meta


def parse_paper_analysis(filepath: Path) -> AgentCase:
    """从 paper-analysis.md 构造 AgentCase。"""
    text = filepath.read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    
    # 提取标题
    first_line = text.strip().split("\n")[0].lstrip("# ").strip()
    
    # 统计章节：## 开头的为步骤
    steps = []
    sections = re.split(r"\n(?=## )", text)
    turn = 0
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        header_match = re.match(r"##\s+\d+\.?\s*(.+)", sec)
        if not header_match:
            continue
        header = header_match.group(1).strip()
        turn += 1
        
        # 估算这步的质量
        lines = sec.count("\n")
        has_detail = "|" in sec or lines > 5
        
        steps.append(AgentCaseStep(
            turn=turn,
            action=f"analyze_{header.replace(' ', '_').lower()[:40]}",
            action_type="text_output",
            reasoning=f"阅读并分析: {header}",
            tool_args={"section": header},
            tool_result={"content_length": len(sec), "has_table": "|" in sec},
            success=has_detail,
            duration_ms=len(sec) * 10,  # 粗略估计
        ))

    # 从 meta 中提取 domain 和 plan_id
    domain = meta.get("domain", "paper-reading")
    
    # 从章节标题提取涉及的论文/技术点作为 provenance
    paper_refs = re.findall(r"(FireAct|EvoAgentBench|ReAct|SWE-bench|EverOS|Raven|verl|GRPO|DPO|LoRA)", text)
    provenance = []
    seen = set()
    for ref in paper_refs:
        if ref not in seen:
            seen.add(ref)
            provenance.append(ProvenanceRef(
                source_type="knowledge_doc",
                source_id=ref,
                confidence=0.8,
                snippet=f"论文/技术引用: {ref}",
            ))

    return AgentCase(
        case_id=meta.get("plan_id", filepath.parent.name),
        plan_id=meta.get("plan_id", ""),
        domain=domain,
        task_description=first_line,
        task_instruction="系统性地阅读和分析相关论文，建立技术全景图",
        steps=steps,
        provenance=provenance,
        success=True,
        artifact_paths=[str(f.relative_to(DATA.parent)) for f in filepath.parent.rglob("*.md")],
        summary=f"完成 {turn} 个分析步骤，覆盖 {len(provenance)} 个技术要点",
        total_tokens=len(text) // 2,  # 粗略估计
        total_wall_time_seconds=1800,  # 假设30分钟
        total_turns=turn,
        started_at=meta.get("created", meta.get("created_at", "")),
        finished_at=meta.get("created", meta.get("created_at", "")),
        verifier_score=0.85,
    )


def parse_self_review(filepath: Path) -> AgentCase:
    """从 self-review.yaml 构造 AgentCase（Crucible 集测场景）。"""
    import yaml  # type: ignore
    text = filepath.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    
    steps = []
    for i, check in enumerate(data.get("checks", [])):
        passed = check.get("result") == "PASS"
        steps.append(AgentCaseStep(
            turn=i + 1,
            action=f"check_{check.get('id', f'step{i}')}",
            action_type="tool_call",
            reasoning=check.get("desc", ""),
            tool_args={"check_id": check.get("id")},
            tool_result={"result": check.get("result"), "details": check.get("details", "")},
            success=passed,
            error="" if passed else check.get("details", "unknown error"),
        ))

    return AgentCase(
        case_id=data.get("plan_id", filepath.parent.name),
        plan_id=data.get("plan_id", ""),
        domain="crucible",
        task_description="Scaling Admin PR 的自我审查 — 代码变更验证",
        task_instruction="对 18 个修改文件进行 Build/Vet/Case 验证",
        steps=steps,
        provenance=[
            ProvenanceRef(source_type="skill", source_id="crucible-self-review", confidence=0.9),
            ProvenanceRef(source_type="knowledge_doc", source_id="crucible-venti-test-scaling-admin", confidence=0.7),
        ],
        success=data.get("status", "").startswith("PASSED"),
        artifact_paths=[str(filepath.relative_to(DATA.parent))],
        summary=f"完成 {len(steps)} 项检查, {data.get('status', 'UNKNOWN')}",
        total_tokens=2000,
        total_wall_time_seconds=120,
        total_turns=len(steps),
        started_at=data.get("timestamp", ""),
        finished_at=data.get("timestamp", ""),
        verifier_score=0.95 if data.get("status", "").startswith("PASSED") else 0.5,
    )


def parse_phase_plan(filepath: Path) -> AgentCase:
    """从 phase-*-detailed.md 构造 AgentCase（设计规划轨迹）。"""
    text = filepath.read_text(encoding="utf-8")
    
    first_line = text.strip().split("\n")[0].lstrip("# ").strip()
    
    # 提取步骤：## 开头的为设计阶段
    steps = []
    sections = re.split(r"\n(?=## )", text)
    turn = 0
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        header_match = re.match(r"##\s+(\d+)\.?\s*(.+)", sec)
        if not header_match:
            continue
        num, header = header_match.groups()
        turn += 1
        
        # 检测是否包含代码块/架构图（有质量的设计）
        has_code = "```" in sec
        has_table = "|" in sec and sec.count("|") > 5
        has_architecture = any(kw in sec.lower() for kw in ["pipeline", "actor", "architecture", "架构", "flow"])
        quality = has_code or has_table or has_architecture
        
        steps.append(AgentCaseStep(
            turn=turn,
            action=f"design_{header.replace(' ', '_').lower()[:40]}",
            action_type="text_output",
            reasoning=f"设计阶段 {num}: {header}",
            tool_args={"section": header},
            tool_result={
                "has_code": has_code,
                "has_table": has_table,
                "has_architecture": has_architecture,
            },
            success=True,
            duration_ms=300000,  # 假设5分钟
        ))

    return AgentCase(
        case_id=filepath.parent.name + "-phase-plan",
        plan_id=filepath.parent.name,
        domain="paper-reading",
        task_description=first_line,
        task_instruction="设计技术方案，产出可执行的 implementation plan",
        steps=steps,
        provenance=[
            ProvenanceRef(source_type="episode", source_id="lollapalooza-context", confidence=0.8),
        ],
        success=True,
        artifact_paths=[str(filepath.relative_to(DATA.parent))],
        summary=f"完成 {turn} 个设计阶段",
        total_tokens=len(text) // 2,
        total_wall_time_seconds=1200,
        total_turns=turn,
        started_at="",
        finished_at="",
        verifier_score=0.80,
    )


def case_to_training_sample(case: AgentCase, skill_ids: list[str] | None = None) -> TrainingSample:
    """将一个 AgentCase 转换为一条 TrainingSample。"""
    messages = []
    
    # System
    messages.append(TrainingMessage(role="system", content=(
        f"你是 Noctua Agent，当前领域: {case.domain}。\n"
        f"任务指令: {case.task_instruction}\n"
        "请逐步执行，必要时使用工具。每步之后说明你的推理。"
    )))
    
    # User
    messages.append(TrainingMessage(role="user", content=case.task_description))
    
    # Assistant + Tool 消息对
    for step in case.steps:
        content = step.reasoning or f"执行: {step.action}"
        tool_calls = None
        if step.action_type == "tool_call" and step.tool_args:
            tool_calls = [{
                "id": f"call_{step.turn}",
                "type": "function",
                "function": {
                    "name": step.action,
                    "arguments": json.dumps(step.tool_args, ensure_ascii=False),
                }
            }]
        messages.append(TrainingMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        ))
        
        if step.tool_result is not None:
            messages.append(TrainingMessage(
                role="tool",
                content=json.dumps(step.tool_result, ensure_ascii=False),
                tool_call_id=f"call_{step.turn}" if step.action_type == "tool_call" else None,
                name=step.action if step.action_type == "tool_call" else None,
            ))
    
    # 最终 summary
    messages.append(TrainingMessage(
        role="assistant",
        content=f"执行完成。{case.summary}。成功: {case.success}。评分: {case.verifier_score or 'N/A'}。",
    ))

    return TrainingSample(
        sample_id=f"{case.case_id}-train-001",
        source_case_id=case.case_id,
        domain=case.domain,
        messages=messages,
        quality_score=case.verifier_score or 0.5,
        success=case.success,
        human_verified=case.human_decision == "approve",
        skill_ids=skill_ids or [],
        signal_type="positive" if case.success else "negative",
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=[case.domain, f"turns={case.total_turns}"],
    )


def extract_skill_from_case(case: AgentCase, other_cases: list[AgentCase], threshold: int = 2) -> Skill | None:
    """从单个 Case + 相似 Case 中尝试提取 Skill。

    简单实现：如果 domain 相同且有 ≥ threshold 个 case，提取为 Skill。
    实际应该用 SkillForge/EverAlgo 的 AgentSkillExtractor 来做。
    """
    same_domain = [c for c in other_cases if c.domain == case.domain and c.success]
    if len(same_domain) < threshold:
        return None

    action_names = []
    for c in same_domain:
        action_names.extend(s.action for s in c.steps)

    success_rate = (
        sum(1 for c in same_domain if c.success) / len(same_domain)
        if same_domain else 0
    )

    return Skill(
        skill_id=f"skill-{case.domain}-{len(same_domain):03d}",
        title=f"{case.domain} 执行模式 (从 {len(same_domain)} 个 case 提取)",
        description=f"在 {case.domain} 领域执行任务的通用模式",
        source_cases=[c.case_id for c in same_domain],
        applicability=SkillApplicability(
            domains=[case.domain],
            conditions=["任务类型匹配"],
            exclusion_patterns=["领域不匹配的不要使用"],
        ),
        prerequisites=sorted(set(action_names)),
        steps=[
            f"1. 分析 {case.domain} 任务范围",
            f"2. 分步执行，每步产出中间结果",
            f"3. 自检每个步骤的质量",
            f"4. 汇总结果并输出",
        ],
        success_rate=success_rate,
        confidence=0.6 + 0.1 * min(len(same_domain), 4),
    )


def sample_all_runs(data_dir: Path) -> tuple[list[AgentCase], TrainingDataset]:
    """扫描 data/runs/ 下所有执行记录，构造 Case + TrainingSample。"""
    cases = []
    
    for run_dir in sorted(data_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        
        # paper-analysis.md → Case
        analysis = run_dir / "paper-analysis.md"
        if analysis.exists():
            cases.append(parse_paper_analysis(analysis))
        
        # self-review.yaml → Case
        review = run_dir / "self-review.yaml"
        if review.exists():
            cases.append(parse_self_review(review))
        
        # phase-*-detailed.md → Case
        for phase_file in sorted(run_dir.glob("phase-*-detailed.md")):
            cases.append(parse_phase_plan(phase_file))

    # Case → TrainingSample
    samples = []
    for case in cases:
        skill_ids = []
        # 尝试提取 Skill
        others = [c for c in cases if c.case_id != case.case_id]
        skill = extract_skill_from_case(case, others)
        if skill:
            skill_ids.append(skill.skill_id)
        samples.append(case_to_training_sample(case, skill_ids))

    dataset = TrainingDataset(
        dataset_id=f"noctua-sample-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        description="从已有执行轨迹首次采样的训练数据",
        domain="multi",
        samples=samples,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    
    return cases, dataset


def print_stats(cases: list[AgentCase], dataset: TrainingDataset) -> None:
    """打印采样统计信息。"""
    print("=" * 60)
    print("  采样统计")
    print("=" * 60)
    print()
    
    print("【AgentCase】")
    print(f"  总计: {len(cases)} 个")
    for domain in sorted(set(c.domain for c in cases)):
        domain_cases = [c for c in cases if c.domain == domain]
        print(f"    {domain}: {len(domain_cases)} 个 (成功率 {sum(1 for c in domain_cases if c.success)/len(domain_cases):.0%})")
    print()
    
    print("【TrainingSample】")
    print(f"  总计: {dataset.sample_count} 条")
    print(f"  Positive: {dataset.positive_count} 条")
    print(f"  DPO pairs: {dataset.dpo_count} 条")
    print(f"  Negative: {dataset.sample_count - dataset.positive_count - dataset.dpo_count} 条")
    print()
    
    total_tokens = sum(s.messages.__len__() for s in dataset.samples)
    total_msgs = sum(len(s.messages) for s in dataset.samples)
    print(f"  总消息数: {total_msgs}")
    print(f"  平均每条样本消息数: {total_msgs / max(dataset.sample_count, 1):.1f}")
    print()
    
    print("【质量分布】")
    for bucket, count in dataset.quality_distribution.items():
        bar = "█" * (count * 2)
        print(f"  {bucket}: {count:3d} {bar}")
    print()
    
    print("【Skill 提取】")
    skills = set()
    for s in dataset.samples:
        skills.update(s.skill_ids)
    print(f"  可提取 skill: {len(skills)} 个")
    for sid in sorted(skills):
        print(f"    - {sid}")
    print()


def main():
    parser = argparse.ArgumentParser(description="从已有执行轨迹采样数据")
    parser.add_argument("--run", help="指定 run id，仅采样该次执行")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON，不打印统计")
    parser.add_argument("--output", "-o", help="输出 JSON 到文件")
    parser.add_argument("--sample-idx", type=int, help="仅输出第 N 条样本的详细内容")
    args = parser.parse_args()

    data_dir = DATA
    if args.run:
        data_dir = DATA / args.run

    cases, dataset = sample_all_runs(data_dir)

    if args.sample_idx is not None:
        if args.sample_idx >= len(dataset.samples):
            print(f"样本索引 {args.sample_idx} 超出范围 (0-{len(dataset.samples)-1})", file=sys.stderr)
            sys.exit(1)
        sample = dataset.samples[args.sample_idx]
        print(json.dumps(sample.model_dump(), indent=2, ensure_ascii=False, default=str))
        return

    if args.json:
        output = {
            "dataset_id": dataset.dataset_id,
            "sample_count": dataset.sample_count,
            "cases": [c.model_dump() for c in cases],
            "samples": [s.model_dump() for s in dataset.samples],
        }
        dump = json.dumps(output, indent=2, ensure_ascii=False, default=str)
        if args.output:
            Path(args.output).write_text(dump, encoding="utf-8")
            print(f"输出到: {args.output}")
        else:
            print(dump)
    else:
        print_stats(cases, dataset)
        
        # 输出前 3 条样本的摘要
        print("【样本预览（前 3 条）】")
        for i, sample in enumerate(dataset.samples[:3]):
            print(f"--- 样本 {i} ---")
            print(f"  ID: {sample.sample_id}")
            print(f"  Domain: {sample.domain}")
            print(f"  Quality: {sample.quality_score:.2f}")
            print(f"  Success: {sample.success}")
            print(f"  Skills: {sample.skill_ids or '(无)'}")
            print(f"  Messages: {len(sample.messages)} 条")
            print(f"  首条消息: {sample.messages[0].content[:80]}...")
            print()


if __name__ == "__main__":
    main()
