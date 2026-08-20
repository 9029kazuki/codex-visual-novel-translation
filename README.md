# Codex Visual Novel Translation

> End-to-end Codex skills for translating visual novels and Galgames with persistent context, independent review, lossless repacking, font diagnosis, and playtest QA.

English · [简体中文](README.zh-CN.md)

This repository contains installable Codex skills rather than a runtime translator, OCR overlay, or one-click machine-translation application. It provides a specialized Japanese-to-Simplified-Chinese edition and an English, language-pair-configurable edition.

## Skills

| Skill | Purpose | Status |
| --- | --- | --- |
| [`translate-galgame-zh`](skills/translate-galgame-zh) | Japanese visual novel → Simplified Chinese | Available |
| [`translate-visual-novel`](skills/translate-visual-novel) | Configurable source and target languages, English instructions | Available |

## What the workflow covers

- Engine, archive, script, and repacking research for the exact game version.
- Multilingual canon research for worldbuilding, character relationships, knowledge state, and voice.
- Target-locale terminology research and a versioned project Bible.
- Stable text IDs, source hashes, protected control tokens, and scene graphs.
- Full-scene translation jobs with cache-friendly shared context.
- Independent review, terminology adjudication, deterministic merge, and automated QA.
- Font coverage and runtime font-chain diagnosis.
- Repacking, playtesting, and reproducible patch evidence.
- Resuming interrupted projects from files instead of chat memory.

## Install

Clone the repository and copy the skill you want into your Codex skills directory.

### PowerShell

```powershell
git clone https://github.com/9029kazuki/codex-visual-novel-translation.git
Copy-Item -Recurse -Force `
  .\codex-visual-novel-translation\skills\translate-galgame-zh `
  "$env:USERPROFILE\.codex\skills\translate-galgame-zh"
```

Restart Codex if the skill does not appear immediately.

For the English multilingual edition, copy `skills/translate-visual-novel` instead:

```powershell
Copy-Item -Recurse -Force `
  .\codex-visual-novel-translation\skills\translate-visual-novel `
  "$env:USERPROFILE\.codex\skills\translate-visual-novel"
```

## Use

Invoke the Chinese translation workflow explicitly:

```text
Use $translate-galgame-zh to translate this Japanese visual novel into Simplified Chinese and build a recoverable localization project.
```

Or ask naturally in Chinese:

```text
使用 $translate-galgame-zh 汉化这个 Galgame。先研究准确版本的解包与封包方法，再建立术语、人设和角色口吻，按完整场景翻译、独立审校、回填并实机验证。
```

For another language pair:

```text
Use $translate-visual-novel to translate this Japanese visual novel into Spanish. Preserve engine controls, research established Spanish names and terminology, and build a recoverable localization project.
```

## Current scope

- The complete workflow has been exercised on a commercial-scale Windows KiriKiri/XP3 project.
- The multilingual edition accepts explicit BCP 47-style source and target locales and generates a frozen language-pair profile for each project.
- Engine-specific extraction and repacking still require exact-version research and an independently proven round trip.
- GARbro is optional and is not redistributed in this repository. Use your own installation when it is appropriate for the target game.
- The skill does not include game files, scripts, translations, fonts, or patches from any commercial title.

## Repository layout

```text
skills/
  translate-galgame-zh/   Japanese-to-Simplified-Chinese edition
  translate-visual-novel/ English multilingual edition
```

Each skill folder is self-contained and includes its own `SKILL.md`, references, and deterministic helper scripts.

## License

The original code and documentation in this repository are licensed under the [MIT License](LICENSE). Optional third-party tools retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
