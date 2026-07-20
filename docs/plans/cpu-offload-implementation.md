# Omni-397B CPU Offload Implementation Plan

> 基于 `rome/rubicon/docs/notes/omni-397B/cpu-offload-analysis.md` 的定量分析，
> 将 ViT + Projector 从 GPU 搬迁到 CPU，释放 HBM 给 KV cache。
>
> 实施策略：方案 A（ViT + Projector 都在 CPU，零框架改动）
>
> 状态：⏳ 待执行 | 优先级：P0

---

## 背景

### 问题

Omni-397B 线上推理主瓶颈已锁定：
- `max_running_requests=2` 导致 SM 利用率 ~40%（真实 `sm_util`），显存接近打满
- 根因：多模态 embedding（ViT + Projector）占用 ~6-10GB HBM，挤占 KV cache 空间
- 当前 `util.gpu` 89% 是误导（主要是显存占用，不是计算利用）

### 目标

- 释放多模态 embedding 所占 HBM → KV pool +23-39%
- `max_running_requests` 从 2 提到 8-16
- 吞吐目标：sm_util 55-65%，后续阶段向 70%+ 推进

### 方案选择

**方案 A（推荐）**：ViT + Projector 都在 CPU

```python
vision_cpu = engine.model.thinker.visual.cpu()
emb = vision_cpu(pixel_values, grid_thw).to("cuda")  # 12.4 MB
# 零 SGLang 源码改动，走 precomputed_embedding 模式
```

**方案 B**：ViT CPU + Projector GPU（需 monkey-patch，收益 <0.1%，放弃）

---

## 关键未知项确认清单

> 这些必须在生产环境实测，不能靠估算。

| # | 未知项 | 风险 | 确认方法 | 预计耗时 |
|---|--------|------|---------|---------|
| U1 | CPU ViT 实际耗时（无实测） | **高** | 在目标 CPU 节点跑 `visual.cpu()` forward 并计时 | 30min |
| U2 | SGLang primus fork 是否支持 `precomputed_embedding` | **高** | 检查生产镜像 SGLang 版本，v0.4.6 不支持 | 15min |
| U3 | IPEX + INT8 + AMX 实际加速比 | 中 | 在有 IPEX 的环境实测 ViT forward | 1h（需环境） |
| U4 | 外部缓存命中率（刷库场景） | 中 | 采样 ODPS 数据统计图片 hash 重复率 | 30min |
| U5 | 生产 CPU 节点 core 数 | 中 | `kubectl describe node` 或 `lscpu` | 5min |

---

## 实施步骤

### Phase 1: 可行性确认（本阶段）

#### Step 1.1: 确认 SGLang 版本支持

```bash
# 在生产 Pod 中执行
kubectl exec -it <omni-pod> -- python -c "
import sglang
print(sglang.__version__)
# 检查是否有 precomputed_embedding 支持
from sglang.srt.managers.io_struct import GenerateReqInput
print(hasattr(GenerateReqInput, 'image_data'))
"
```

**判定**：如果版本 >= v0.4.7 且有 `image_data` 字段 → ✅ 支持。否则需要先升级镜像。

#### Step 1.2: CPU ViT Benchmark

```bash
# 在生产 CPU 节点上运行（通过 RayJob 提交单 GPU worker 测试）
python cpu_vit_bench.py --model omni-397b --images ./sample_images/ --repeats 100
```

**采集指标**：
- 单图 ViT forward 耗时（p50/p95/p99）
- Projector forward 耗时
- 不同图片分辨率下的耗时分布
- CPU 核数使用率

**判定**：p50 < 200ms → ✅ IPEX 级别可行。p50 200-500ms → ⚠️ 需评估在线场景延迟。p50 > 500ms → ❌ 离线 batch 优先。

#### Step 1.3: 外部缓存命中率

```bash
# 从 ODPS 采样 1000 条请求，统计图片 URL/内容的 hash 重复率
python tools/check_image_cache_hit.py --sample-size 1000 --table <odps_table>
```

**判定**：命中率 > 30% → ✅ 刷库场景大量重复图片，CPU 成本大幅摊薄。命中率 < 10% → ⚠️ 缓存收益有限，CPU 延迟需严格控制。

### Phase 2: 实验验证（下一阶段）

#### Step 2.1: 离线 Batch 验证

使用 `precomputed_embedding` 模式跑全量 batch benchmark：
```yaml
# RayJob 配置
tp: 8
max_running_requests: 16
cpu_offload: true
precomputed_embedding: true
data: omni_397b_full_6988.jsonl
```

**对比基线**（无 CPU offload，max_running_requests=2）：
- throughput (tok/s)
- sm_util
- P50/P99 latency
- GPU memory usage

#### Step 2.2: 在线灰度

1. 选 1 台 GPU 节点部署 CPU offload 版本
2. 引流 10% 流量 → 观察 1h
3. 引流 50% → 观察 2h
4. 全量 → 持续监控 24h

**监控指标**：
- sm_util（目标 >55%）
- max_running_requests 实际值
- P50/P99 latency（不能显著劣化）
- GPU 显存释放量

### Phase 3: 全量上线（最后阶段）

- 全集群部署 CPU offload 版本
- 更新 WingsApp 配置
- 通知相关团队（刷库业务方）
- 回滚预案：保留原 GPU ViT 版本镜像，一键回滚

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| SGLang primus fork 不支持 precomputed_embedding | Phase 1 阻断 | 升级镜像 or fallback 到方案 B（monkey-patch） |
| CPU ViT 耗时远超估算（200ms→500ms+） | 在线场景延迟不可接受 | 仅用于离线 batch；在线用 GPU ViT + 外部缓存 |
| IPEX 不可用 | CPU 降级到 ~3.4s/图（不可接受） | 必须确保 IPEX 或 oneDNN 可用 |
| 外部缓存命中率极低 | CPU 成本不能通过缓存摊薄 | 离线 batch 场景不受影响；在线场景需 CPU 加速 |

---

## 参考

- `rome/rubicon/docs/notes/omni-397B/cpu-offload-analysis.md` — 定量分析
- `rome/rubicon/docs/notes/omni-397B/omni-397b-optimization-plan.md` — 整体优化路线
- `rome/rubicon/docs/designs/cpu-preprocessing-omni.md` — CPU 预处理设计（引用来源）
- `rome/sglang/docs/advanced_features/server_arguments.md` — `--cpu-offload-gb` 参数
