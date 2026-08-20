# Codex Visual Novel Translation

> 面向 Codex 的端到端视觉小说／Galgame 翻译 Skill，覆盖长期上下文、独立审校、无损回填、字体诊断和实机 QA。

[English](README.md) · 简体中文

本仓库提供可安装的 Codex Skill，不是实时翻译器、OCR 覆盖层或一键机翻软件。仓库同时提供日语视觉小说到简体中文的专用版，以及采用英文说明、可配置源语言和目标语言的国际版。

## Skill

| Skill | 用途 | 状态 |
| --- | --- | --- |
| [`translate-galgame-zh`](skills/translate-galgame-zh) | 日语视觉小说 → 简体中文 | 已发布 |
| [`translate-visual-novel`](skills/translate-visual-novel) | 英文说明，可配置语言对 | 已发布 |

## 主要能力

- 针对准确游戏版本研究引擎、归档、脚本、回填和封包方案。
- 不限语言研究世界观、人物关系、剧情知识状态和角色口吻。
- 研究目标中文译名与汉化惯例，建立可版本化的项目 Bible。
- 保存稳定文本 ID、原文哈希、控制符和场景图。
- 按完整场景组织翻译任务，使用缓存友好的共享上下文。
- 独立审校、术语裁决、确定性合并和自动 QA。
- 字形静态覆盖与引擎运行时字体链诊断。
- 回填、封包、实机测试和补丁复现证据。
- 从工作区文件恢复中断任务，不依赖聊天记忆。

## 安装

```powershell
git clone https://github.com/9029kazuki/codex-visual-novel-translation.git
Copy-Item -Recurse -Force `
  .\codex-visual-novel-translation\skills\translate-galgame-zh `
  "$env:USERPROFILE\.codex\skills\translate-galgame-zh"
```

如果 Skill 没有立即出现，请重启 Codex。

安装英文多语言版时，将上面命令中的两个 `translate-galgame-zh` 都替换为 `translate-visual-novel`。

## 使用

```text
使用 $translate-galgame-zh 汉化这个 Galgame。先研究准确版本的解包与封包方法，再建立术语、人设和角色口吻，按完整场景翻译、独立审校、回填并实机验证。
```

也可以直接提供游戏目录，并说明补丁形式、是否允许启动游戏及其他限制。

国际版调用示例：

```text
Use $translate-visual-novel to translate this Japanese visual novel into Spanish. Preserve engine controls, research established Spanish names and terminology, and build a recoverable localization project.
```

## 当前范围

- 完整流程已经在一个商业规模的 Windows KiriKiri/XP3 项目中实际执行。
- 国际版要求显式填写 BCP 47 风格的源语言和目标语言，并为每个工程生成冻结的语言对配置。
- 具体引擎的解包与封包仍必须针对准确版本研究，并单独证明无翻译往返可行。
- 本仓库不分发 GARbro；如目标游戏适用，请使用用户自行安装的版本。
- 本仓库不包含任何商业游戏的文件、脚本、译文、字体或补丁。

## 许可证

本仓库原创代码和文档采用 [MIT License](LICENSE)。可选第三方工具继续遵守各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
