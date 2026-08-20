# 共享前缀、子智能体种子与分批覆盖

## 目标

让同一翻译或审校批次的所有正式 job 获得同一份完整世界观、人设、口吻、术语、知识门和决策快照，同时避免继承长期主任务中的旧 job、日志和调试输出。

缓存是延迟和计算优化，不是记忆或上下文压缩。共享资料即使命中缓存，仍会占用模型上下文窗口。

## 稳定共享前缀

运行 `scripts/build_shared_prefix.py` 生成内容寻址的共享前缀。固定顺序为：

1. 翻译契约与输出结构。
2. 世界观、完整人设和完整口吻。
3. 完整术语、称谓策略、路线知识门和批准译例。
4. 当前批次的冻结 decisions。

工具生成：

```text
contexts/shared-prefix/<prefix-id>/
├── sections/
│   ├── 00-translation-contract.md
│   ├── 10-canon-and-voice.md
│   ├── 20-terminology-and-knowledge.md
│   └── 30-decisions.md
├── shared-prefix.md
└── shared-prefix-manifest.json
```

`contexts/shared-prefix/current.json` 只是指向当前快照的指针，不是模型共享前缀的一部分。共享文本中不得包含生成时间、绝对路径、job ID、临时进度或其他每次运行会变的值。

## 两级派发

1. 长期主智能体使用 `fork_turns="none"` 创建一个干净种子。
2. 种子按 manifest 的 `seed_read_order` 顺序完整读取四个 section，不读取任何 job 原文。
3. 等待种子轮次完成，使各层共享前缀有机会写入缓存。
4. 先从种子使用 `fork_turns="all"` 派发一个探针 job。种子历史必须只含共享前缀，因此这里的 `all` 不会带入长期主任务污染。
5. 对照 manifest 和实际 usage 记录探针的 `cached_tokens`；宿主提供计数时使用 `scripts/record_cache_probe.py` 写入 `qa/cache/`。当宿主不暴露精确缓存边界时，明确记录为“最佳努力验证”，不宣称绝对命中。
6. 探针合格后，从同一种子批量派发其余正式 job。每个 job 只处理一个批准任务。

当 `fork_turns` 不可控或子智能体不可用时，降级为独立 job bundle；必须仍绑定同一 shared-prefix digest 和 decision snapshot，但不虚报跨请求缓存命中。

## 共享前缀不变式

- 同一批次使用同一模型、工具集、工具顺序、输出 schema 和共享内容顺序。
- 文本使用 UTF-8 和 LF；JSON 使用确定性键顺序；不在共享前缀中加入随机数或时间戳。
- 任何 job 独有内容都在共享前缀之后追加。
- 一批翻译使用固定 decisions。新术语提案集中裁决后创建新快照，不向正在运行的 job 逐个广播。
- 如使用可控的 GPT-5.6+ API 编排器，在共享前缀末尾设显式 cache breakpoint，对相同快照使用相同 `prompt_cache_key`。当前 Codex 子智能体接口没有暴露这两个参数时，不得伪造或假定已设置。

## 任务模型视图

完整原文与回填元数据仍保存在 `source.jsonl` 和 `source-manifest.json`。翻译子智能体优先读取 `source.model.jsonl`，其中只保留：

```text
id / kind / speaker / text / protected_tokens
```

机器字段由验证和合并工具按 ID 从冻结原文补回。子智能体不得依赖模型视图中没有的回填位置、归档偏移或其他机器字段。

## 超大任务的分批覆盖

完整 bundle 不设置固定总字符失败上限。`build_context_bundle.py` 生成 `chunk-plan.json`，每批包含：

- 稳定 `chunk_id`。
- 唯一的 `primary_entry_ids`。
- 只读的 `overlap_before_ids` 与 `overlap_after_ids`。
- 自然场景边界与强制切分标记。
- 对应的模型原文文件。

`coverage-plan.json` 必须证明每个计划 ID 恰好属于一个 primary 范围。重叠 ID 只用于语义承接，不得重复输出译文。各分批完成后运行一次全局一致性扫描，再允许进入审校或合并。

`bundle-status.json` 是当前 bundle 的唯一有效状态入口，并引用 source digest、shared-prefix digest、chunk-plan digest 和 coverage digest。成功重建后删除旧 `budget-report.json`；不允许有效状态与残留失败报告并存。
