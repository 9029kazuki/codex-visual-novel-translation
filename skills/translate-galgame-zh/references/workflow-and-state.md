# 工作流、项目结构与状态

## 目录契约

为每个游戏建立独立项目目录：

```text
project/
├── project.json
├── run-state.json
├── source/
│   ├── file-manifest.json
│   └── signatures.md
├── research/
│   ├── sources.jsonl
│   ├── unpack-notes.md
│   └── decisions.md
├── staging/
│   ├── unpacked/
│   └── roundtrip/
├── extracted/
│   ├── source.jsonl
│   ├── script-map.json
│   └── control-token-report.json
├── bible/
│   ├── world.md
│   ├── characters.json
│   ├── voice.json
│   ├── route-knowledge.json
│   ├── honorifics.md
│   ├── glossary.tsv
│   └── version.json
├── planning/
│   ├── jobs.jsonl
│   ├── translation-decisions.json
│   └── decision-snapshots/
├── contexts/
│   ├── shared-prefix/
│   └── <job_id>/
├── translations/
│   ├── drafts/
│   ├── approved/
│   └── final.jsonl
├── reviews/
├── qa/
│   ├── jobs/
│   └── cache/
├── build/
└── release/
```

不要把 GARbro 解包结果写进原始游戏目录。不要覆盖 `extracted/source.jsonl`；重新提取时生成新版本并比较原文哈希。

## 阶段状态机

按以下阶段推进 `run-state.json`：

1. `initialized`
2. `researched`
3. `roundtrip-proven`
4. `extracted`
5. `bible-frozen`
6. `plan-approved`
7. `translating`
8. `reviewed`
9. `validated`
10. `repacked`
11. `playtested`
12. `released`

只在证据文件存在时提升阶段。失败时保留当前阶段，记录失败命令、日志路径、受影响文件和下一步。
先运行 `scripts/audit_project.py`，再使用 `scripts/set_stage.py` 逐级推进并附证据路径；不要手工把状态跳到后续阶段。状态脚本会检查连续历史和阶段专属证据内容，而不只检查路径是否存在。

## 阶段门禁

### 初始化门禁

- 记录准确作品名、日文原名、品牌、版本、平台和源目录。
- 生成 SHA-256 清单。
- 确认工作区和输出位置有足够空间。

### 研究门禁

- 解包研究覆盖准确版本、引擎和实际扩展名。
- 引擎与作品事实研究不限语言，覆盖游戏内文本、官方资料、工具文档和可追溯社区证据；只有目标中文译名与汉化惯例限定中文语域。
- `research/sources.jsonl` 对 `engine`、`canon`、`target-locale` 三条证据线均有有效记录，并记录证据语言、类型、权威度和具体 claims。
- 每个锁定术语都能追溯到来源或明确的主智能体裁决。

### 往返门禁

- 在未改译文的情况下完成解包、提取、回填和封包。
- 重新封包的副本能够启动并读取测试脚本。
- 对比确认除预期容器差异外无资源缺失。

### 提取门禁

- 每个可翻译单元都有稳定 ID、原文哈希、文件、顺序和类型。
- 控制符、占位符、标签、语音 ID、换行和说话人字段被单独记录。
- UI、选项、旁白、对白、系统文本和图片文字均被盘点。

### 资料库门禁

- 完成路线图、角色关系、当前知识状态、称谓、口吻和锁定术语。
- 完成一个代表性场景的校准翻译和审阅。
- 更新 `bible/version.json` 并冻结版本。

### 翻译门禁

- 主智能体批准任务边界。
- 每个任务把 `plan_approved` 设为 `true`，并填写适用的时间、地点、前情、前驱和相邻原文 ID；无需求时明确说明“无需额外上下文”。
- 每个任务绑定原文哈希和资料库版本。
- 冻结一份翻译决策快照，运行 `build_shared_prefix.py`，并让每个正式任务同时绑定 `shared_prefix_id`、共享前缀哈希和决策快照哈希。
- 每个任务的 `bundle-status.json`、`chunk-plan.json` 和 `coverage-plan.json` 有效；每个原文 ID 恰好属于一个 primary chunk，overlap 不计入输出覆盖。
- 每个草稿通过结构验证后才进入审校。

### 发布门禁

- 最终译文覆盖全部计划 ID。
- 自动 QA 无 error；warning 已人工裁决并记录。
- 最终显示字符的字体覆盖报告缺失数为 0；字体文件、内部 face、许可证和归档路径均有记录。
- 运行时字体报告证明全新配置与已有设置恢复后仍选择预期字体；正文、姓名框、选项、历史记录和存档标题的未覆盖项已明确标成风险。
- 回填、封包、启动、存读档、选择肢和目标路线测试通过。
- 发布目录只包含预期补丁文件、说明、校验和与已知问题。

## 可恢复性

使用以下任务状态：

```text
pending -> assigned -> translated -> validated -> reviewed -> approved -> merged
                         \-> failed -> pending
```

每次子智能体开始前把任务设为 `assigned`；收到译文后立即验证。进程中断时，将没有完整输出的 `assigned` 任务恢复为 `pending`，不要重做已批准任务。使用原子写入脚本更新状态，避免并行写坏任务表。

在所有生成物中记录：技能版本、资料库版本、共享前缀 ID/哈希、决策快照哈希、原文哈希、任务 ID、生成时间、执行者角色和验证结果。不把可变时间戳、绝对路径或运行状态写入共享 Prompt 前缀；它们只属于机器报告。
