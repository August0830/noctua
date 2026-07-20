# Agent Skill Template
# 
# Each skill file defines a reusable procedure that SkillForge can extract and refine.
# Place in skills/ directory for Raven / Noctua agent to load.
#
# Format: markdown with YAML frontmatter (EverOS compatible)

---
title: "H20 GPU batch inference tuning"
description: "Optimize batch inference throughput on H20 GPUs using Roofline-guided parameter search"
prerequisites:
  - "Roofline data collected"
  - "Target model deployed on H20 cluster"
applicable_models:
  - "Qwen3-0.6B"
  - "Qwen3-8B"
applicable_clusters: ["H20"]
success_rate: null
---

## Steps

1. Read Roofline analysis to determine compute-bound vs memory-bound
2. If compute-bound, increase batch_size toward 80% of memory limit
3. If memory-bound, tune radix_cache and prefix_caching first
4. Run sweep: batch_size ∈ [4, 8, 16, 32], record tokens/s
5. Output report to `rubicon/data/results/{model}_{date}.json`

## Notes

- Never exceed 90% GPU memory on H20
- Check umon metrics before and after for sm_util change
