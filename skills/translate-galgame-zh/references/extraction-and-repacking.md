# 解包、提取、回填与封包

## 先研究再操作

在运行任何解包工具前，先完成特定游戏研究。记录准确版本、可见扩展名、文件头、疑似引擎、成功案例、所用工具版本、文本编码和已知封包限制。

不要把“GARbro 能打开归档”等同于“能无损重新封包”。翻译前必须证明完整往返链路。

## 使用 GARbro

本 Skill 不再分发 GARbro 二进制。请自行安装 GARbro，然后通过 `-Path`、环境变量 `GARBRO_PATH` 或系统 `PATH` 提供位置。运行 `scripts/locate_garbro.ps1` 获取绝对路径；需要可见 GUI 时运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/locate_garbro.ps1 -Launch
```

也可以显式指定目录或程序：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/locate_garbro.ps1 -Path C:\Tools\GARbro
```

始终直接使用 `GARbro.Console.exe` 或 `GARbro.GUI.exe`，不要依赖快捷方式。先用一个小归档或一个脚本归档验证读取和导出，再处理全量文件。

若 GARbro 失败：

1. 读取文件头和扩展名，重新确认引擎及具体版本。
2. 搜索该游戏准确版本的专用解包、文本导出和封包方案。
3. 记录失败现象和错误信息，避免重复试错。
4. 在 staging 副本上验证候选工具；成功后固化版本和命令。

## 无翻译往返测试

依次完成：

1. 从只读源目录复制待测归档到 `staging/roundtrip/input`。
2. 解包到 `staging/roundtrip/unpacked`。
3. 不改变任何文本，使用计划中的回填/封包方式生成 `staging/roundtrip/repacked`。
4. 比较文件数、相对路径、未压缩内容哈希和容器清单。
5. 用游戏副本启动、进入相关场景并测试存档/读档。
6. 把命令、工具版本、结果和差异写入 `research/unpack-notes.md`。

无法完成往返时，暂停翻译。可以先继续语料研究，但不要产生声称可交付的完整补丁。

## 无损文本模式

将每个可翻译单元保存为一行 JSONL。推荐字段：

```json
{"id":"common_001.ks:000042","source_hash":"sha256:...","file":"scenario/common_001.ks","order":42,"route":"common","scene_id":"common-001-rooftop","kind":"dialogue","speaker":"美咲","voice_id":"v_00123","text":"……そうなんだ。","protected_tokens":["[wait]"],"boundary_before":false,"metadata":{}}
```

要求：

- `id` 在相同源版本内稳定且唯一。
- `source_hash` 由准确原文和必要结构字段计算。
- `text` 只包含真正可翻译的显示文本。
- `protected_tokens` 按出现顺序记录必须原样保留的标签、变量、占位符和转义序列。
- 把说话人、语音 ID、标签参数、路线标签、文件位置和顺序保留为结构化字段。
- 记录原始编码、BOM、换行风格和结尾换行。

不要用通用正则盲目遮蔽所有方括号或花括号；某些引擎会把可翻译文字放在标签参数中。先使用引擎感知的解析器，再生成 `protected_tokens`。

## 场景图

扫描脚本标签、跳转、调用、返回、选择肢、路线变量、背景/BGM 切换、日期地点和视角变化，生成 `extracted/script-map.json`。标记：

- 公共线与各角色路线。
- 选择节点、前置条件、合流点和结局。
- 重复调用的公共文本。
- 场景前驱、后继和可能的知识状态。

任务划分以场景图为主，文件边界为辅。

## 回填与封包

- 只按稳定 ID 回填，不按译文附近字符串模糊替换。
- 回填前再次核对源文件哈希；不一致时停止并重新提取或迁移。
- 保持原编码或采用已验证的新编码。
- 新增或替换字体时，完整读取 [font-runtime.md](font-runtime.md)。优先选择许可允许随补丁再分发的字体，记录字体内部 face 名称、文件哈希和许可证；不要把某台机器上的系统字体当成唯一可复现依赖。
- 对最终回填后的实际显示文本运行 `scripts/audit_font_coverage.py`。静态 cmap 覆盖通过只证明字形存在，不能证明引擎已加载或选中了该字体。
- 对字体目录、别名表、语言映射、早期配置、持久化用户设置和自定义渲染缓存建立加载链证据；封包回读时确认相关文件位于引擎实际读取的路径。
- 先制作最小回填样本并启动游戏，再做全量构建。
- 每次构建写入独立的 `build/<build-id>`，保留命令和日志。
- 最终补丁从已验证构建生成，不直接打包 staging 临时目录。
