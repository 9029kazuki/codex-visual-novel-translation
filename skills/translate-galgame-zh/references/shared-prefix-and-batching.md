# 共享资料、请求稳定性与分批

## 冻结与模型视图

`build_shared_prefix.py` 生成 UTF-8/LF、稳定键序的四段正文：翻译契约→世界观/角色/口吻→术语/称谓/知识门/译例→生效决策。来源 URL、检索时间等审计字段保留在权威资料中；pending/proposed 不进入生效决策。不要依靠压缩删除翻译所需语义。

快照包含 `shared-prefix.md`、有序 `sections/`、`semantic-inputs.json` 和 manifest。`current.json` 只指定新任务默认采用的快照，不要求已运行任务迁移到它。运行测量存入 `qa/cache`，不写进不可变 manifest。

默认路径为 `contexts/shared-prefix/<prefix-id>/<binding-id>/`：正文身份与物理来源绑定分开。同一正文来自不同冻结文件时可并存，不覆盖旧 manifest；正文哈希相同也不保证宿主实际请求的缓存命中。

默认使用完整项目资料。大型项目可提供主协调者批准的 profile：

```json
{"mode":"selected","approved":true,"rationale":"已检查人物关系、间接提及与知识门依赖","characters":["misaki","protagonist"],"routes":["route-a"],"extra_scopes":["scene-a-rooftop"]}
```

profile 必须是语义依赖闭包。没有批准与理由的裁剪会被拒绝；未知角色或路线也会失败。全局事实、称谓、全局知识、全局术语与全部生效决策始终保留；目前不自动裁剪决策作用域。角色 ID、名字和别名都可匹配；别名歧义时用唯一 ID。列表必须包含未出场但被提及或影响解释的角色，以及消歧所需的其他路线。

同一 profile 的任务可共享完整前缀。job 的 `dependency_scope` 可使用同一格式记录经过批准的更小闭包；缺省使用前缀 profile。资料变更后，审计将冻结依赖与当前权威资料比较，忽略单纯版本号、来源或 pending 变化。全局规则变化可以合法地影响全部任务。

## 原生子智能体的稳定历史

共享文件哈希相同不代表实际模型前缀相同：系统/工具定义、消息顺序、工具调用与输出、路径、版本摘要都可能在正文之前出现。

使用无主对话历史的初始化，保持模型、推理设置、工具定义、契约和读取顺序稳定。加载必要资料后才附加角色与具体 job。长种子持续派发会积累 job 列表、工具返回和其他任务记录；只有宿主支持固定种子检查点时才从该检查点复用。没有检查点能力时使用短生命周期 cohort，抽查首、中、末 worker 的继承情况，不宣称种子永久干净。

初始化只执行加载与校验，不再次启动整个本地化 skill 的研究和项目协调流程。同一批内部保持路径与消息稳定；跨版本的早期路径/摘要变化仍可能造成冷启动。只有宿主能控制真正的消息拼装时，才可把机器校验信息放到待复用正文之后。

当前原生接口未暴露 cache key/breakpoint 时，不声称已设置它们。保留现有原生翻译机制，无需为了缓存改用外部翻译 API。缓存不能释放上下文窗口，也不是零成本。

## 分批读取与预算

```text
contexts/<job>/current.json
  → snapshots/<snapshot-id>/bundle-status.json
                           context.md
                           source.jsonl / source.model.jsonl
                           chunk-plan.json / coverage-plan.json
                           chunks/<chunk>.packet.json
```

源文件、回填元数据和覆盖清单由机器保管。模型读取经 `emit_chunk.py <project> <job> <chunk>` 验证的 packet，包含任务上下文、primary 原文、必要邻接与重叠原文。只对 primary 输出译文。不要先读全量 source.model 再读所有 chunk。

`build_context_bundle.py` 的默认 32,000 是模型附加输入的规划上限，不代表宿主实际窗口；默认另预留 8,192 输出 token。可以按宿主测得的余量指定 `--input-budget-tokens`、`--fixed-overhead-tokens`、`--output-reserve-tokens` 和 `--context-window-tokens`。计入已有工具/指令/历史，检查工具返回上限；若传入的预算已经扣除了宿主开销，不能重复扣减。

默认使用 UTF-8 字节数作保守的本地规划估算；安装 tiktoken 并传 `--encoding` 可用指定编码的代理计数。二者都不叫真实 usage。`budget.actual_usage_verified` 保持 false，除非另有真实宿主测量证据。

共享前缀、必要上下文或单条记录超预算时明确失败，调整已批准 profile、宿主允许的预算或制定超长条目方案。不要静默切坏条目。必要邻接原文不删减；可选 overlap 因预算缩减会被标记。源 ID 顺序和覆盖必须不变。

每批译文写独立文件并记录摘要，汇总后生成 job 草稿。分批不会自动清空历史：结合窗口余量和已出现的无关历史决定何时建立新工作上下文。交接只带有证据 ID 的人物状态、公开知识、称谓、悬念、未解决指代和前批结尾；必要时补读原文。最终仍进行完整场景独立审校。

## 缓存观测

优先让第一个实际任务承担探针，不做重复空预热。记录逐请求的 input、cached、cache-write、output、模型/推理设置、历史模式、任务/分批、耗时和重试原因。

`record_cache_probe.py --usage-jsonl <requests>` 接受每行一个唯一 request_id 的本次 usage；相同重复事件去重，冲突重复事件或累计计数拒绝。整体命中率用总缓存读除以总输入。单独的文件 token 数不能证明命中某段完整资料，缺少渲染边界或请求 ID 时只记录 observed-only。

已知单次完整边界时可使用 `--boundary-kind rendered-prefix --expected-prefix-tokens … --request-id …`。tolerance 必须小于正边界；这是对声明边界的最佳努力检查，不保证宿主路由或订阅计费。
