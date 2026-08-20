# 子智能体编排协议

## 角色

- **主智能体**：维护唯一事实源、任务图和资料库；冻结决策；准备共享前缀与任务包；收集、验证、裁决、合并和封包。
- **干净种子**：不继承长主对话，只按 manifest 读入一份内容冻结的完整共享前缀，然后派发同一 cohort 的翻译或审校子智能体。
- **研究子智能体**：只处理一条证据线，返回带链接、证据语言、权威度和具体 claims 的研究记录。
- **翻译子智能体**：只翻译一个批准任务，在需要时按 chunk plan 分批读取，写入独立草稿文件。
- **审校子智能体**：不读翻译者解释，对照同一冻结前缀、完整场景和草稿独立审校。

主智能体不得把最终裁决、共享文件编辑和封包责任移交出去。干净种子只负责预热与派发，不裁决新术语。

## 何时委派

如果当前会话提供子智能体工具，明确使用真实子智能体。保留至少一个主协调容量；并发不足时小批派发，不让任务边界因并发容量而变形。

子智能体不可用时，把原因写入 `run-state.json`，由主智能体按相同输入输出契约逐项执行。

## 任务划分

优先以完整独立场景作为一个 job：

- 同一时间、地点、视角、人物组合且连续发生的小片段可以合并。
- 选择前的公共场景和选择后的各分支分别建任务；分支任务携带父选择和条件。
- 一个脚本文件包含多个独立场景时拆开；多个零碎文件共同构成一场戏时合并。
- 重复调用的公共台词建立唯一任务，不允许多名子智能体分别翻译。
- `plan_jobs.py` 只生成场景级建议，默认不用人为字符上限切开场景。主智能体必须阅读场景图和边界附近原文后批准。
- 超大 job 不必重新改写为多个 job；`build_context_bundle.py` 可按自然子场景生成 chunk plan。每个 ID 只有一个 primary chunk，overlap 只读且禁止输出。

批准时把任务的 `plan_approved` 设为 `true`，并填写适用的 `time`、`location`、`prior_summary`、`predecessors`、`adjacent_entry_ids` 和 `context_notes`。即使不需要额外上下文，也要说明原因。

## 共享前缀与缓存友好派发

完整执行 [shared-prefix-and-batching.md](shared-prefix-and-batching.md)。核心不变式是：

1. 先冻结 Bible 和一份 cohort 翻译决策快照，运行 `build_shared_prefix.py`。
2. 共享前缀按固定顺序完整包含：翻译契约→世界观→全部人设→全部口吻→称谓与术语→全部知识门→批准译例→冻结决策。不为单个 job 裁掉其中的角色、术语或知识门。
3. 主智能体用不继承主对话的方式建立干净种子。种子只读 `shared-prefix-manifest.json` 指定的文件和顺序，校验哈希后回报 `PREFIX_READY <prefix_id>`。
4. 由该种子以完整历史继承方式派发同一 cohort 的正式子智能体。每个 job 的可变 prompt 必须放在共享前缀之后。
5. 翻译与审校可用两个干净种子，两者使用完全相同的初始化 prompt、模型、工具定义、prefix ID 和读取顺序；在 `PREFIX_READY` 之后再追加角色与 job 信息。
6. 同一 cohort 内不改写、重排或重新序列化前缀。资料库或决策变更时生成新 prefix ID，只让受影响任务进入新 cohort。

这个结构能使世界观、人设、口吻、术语和知识门作为所有正式子智能体的相同前缀，也是跨子智能体缓存命中的必要条件。但缓存是平台端能力；技能只能通过精确前缀稳定性来提高命中率，不宣称能保证计费或某次调用必然 100% 命中。可见时把每次的 input/cache/output 计数记录到 `qa/cache/`，不可见时只记录 prefix ID 和哈希。

## 任务包与分批读取

共享前缀模式的 job 包只附可变内容：

1. `context.md`：任务 ID、路线、场景、前情、边界、输出路径与 prefix 绑定。
2. `source.model.jsonl`：给模型的精简视图，只含 `id`、`kind`、`speaker`、`text`、`protected_tokens`。
3. `adjacent.model.jsonl`：必要相邻原文，只用于理解。
4. `chunk-plan.json` 与 `coverage-plan.json`：分批顺序、重叠边界和唯一覆盖证明。
5. `source-manifest.json`：机器核对的原文哈希、文件和顺序；模型不必在每行重复输出这些字段。

一个子智能体可在同一 job 中逐个 chunk 读取和翻译，不需要一次把全部原文都放进单次模型输入。它必须持续写入同一任务草稿，每完成一批就核对 primary ID，最终以 `coverage-plan.json` 确认无漏译、无重复。

## 翻译种子与任务模板

干净种子初始化 prompt 保持一字不变，只包含 prefix manifest 路径和下列要求：

```text
使用 $translate-galgame-zh 建立正式任务的干净种子。
不读主任务对话。完整校验 shared-prefix-manifest.json，并按 seed_read_order 完整读入每个 section。
不读任何 job 文件，不修改任何文件。完成后只回报 PREFIX_READY <prefix_id> <prefix_sha256>。
```

种子就绪后，再追加 cohort 角色和 job 列表。它为每个 job 派发的可变 prompt：

```text
你是翻译执行者，不是协调者。必须使用已继承的共享前缀，不重读 Bible、契约或 decisions。
校验指定 job 的 bundle-status.json，确认 shared_prefix_id 与种子一致。
按 context.md 和 chunk-plan.json 顺序读取 source.model.jsonl/分批文件；overlap 只读，只为 primary ID 输出。
不得搜索或修改其他任务，不得修改术语表、决策、最终脚本或游戏文件。
把 JSONL 写入指定 drafts/<job_id>.jsonl；运行任务级验证器并修复结构错误。
最后只返回：输出路径、记录数、低置信度 ID、术语提案数量和未解决问题。
```

子智能体输出后，主智能体立即运行验证器。失败任务不得进入审校；只返回错误报告和原任务包修复。

## 审校种子与任务模板

尽量使用不同于翻译者的子智能体。审校种子与翻译种子使用同一 prefix，但另行初始化，不继承某个翻译子智能体的对话。就绪后附加：

```text
你是独立审校者。使用已继承的共享前缀，不读翻译者解释。
读取指定 job 的 context.md、source.model.jsonl/分批文件和草稿译文。
检查语义、主体对象、否定、使役被动、路线知识、人物口吻、称谓、术语、控制符和中文自然度。
把逐条裁决写入 reviews/<job_id>.jsonl，不直接修改草稿或共享资料库。
最后返回 error/warning 数量、需主智能体裁决的 ID 和输出路径。
```

主智能体审阅问题并生成 `translations/approved/<job_id>.jsonl`。审校子智能体不得批准自己的翻译。

## 共享事实变更

子智能体只能通过 `term_proposals` 或 review issue 提案。主智能体批准后：

1. 更新资料库或决策文件，递增相应版本。
2. 生成新决策快照和新 prefix ID，不覆盖旧 prefix。
3. 找出包含该词或受影响人物的任务。
4. 对未开始任务使用新 cohort；对已完成任务运行定向一致性审计，必要时重新审校。

禁止并行智能体直接编辑 `glossary.tsv`、`characters.json`、`voice.json`、`route-knowledge.json`、`translation-decisions.json`、`jobs.jsonl` 或最终脚本。

## 收集与恢复

分批等待任务完成，收到一个就立即验证并更新状态。子智能体失败或中断时保留日志，将任务从 `assigned` 设为 `pending`；如果输出文件完整，先验证再决定是否重做。项目状态以文件为准，不因主对话压缩而丢失。
