# 字体覆盖与运行时字体链

## 核心不变量

字体文件的 Unicode cmap 覆盖通过，不代表游戏实际使用了该字体。字体门禁必须保留两份相互独立的证据：

1. `qa/font-coverage.json`：最终显示文本所需字形在随补丁发布的字体或明确回退链中全部存在。
2. `qa/font-runtime-report.json`：引擎初始化、恢复已有设置和创建各类文本层后，实际选择了预期字体。

静态报告不得声称实机通过；某一行正文显示正常，也不得推断姓名框、选项、历史记录或 UI 使用同一渲染器。

## 静态字形门禁

1. 从回填后的运行时文本汇总字符，不要只扫描翻译草稿。至少纳入正文、姓名框、选项、历史记录、设置、存档标题和补丁新增 UI 文本。
2. 只用引擎感知的结果剥离控制符。可以移除 `protected_tokens` 中已确认不显示的精确串，不要用通用正则删除所有方括号、花括号或标签参数。
3. 对实际发布字体运行 `scripts/audit_font_coverage.py`；字体回退链有多套字体时逐个传入，报告以 cmap 并集计算覆盖，但运行时报告仍须证明回退链真实生效。
4. 对简体中文项目另选一组日文字体通常不含、且确实可能在文本中出现的探针，例如“请、动、诉、嘟”。探针是诊断辅助，不应替代完整字符并集。
5. 记录每个字体的路径、字节数、SHA-256、集合 face 索引、内部 family/full/PostScript 名称和 Unicode cmap 数量。
6. 随补丁再分发字体时，保存许可证文件并确认允许再分发；系统字体可以作为兼容方案，但不能无证据地作为跨机器唯一依赖。

推荐命令：

~~~powershell
python scripts/audit_font_coverage.py `
  --input translations/final.jsonl `
  --input bible/namebox-map.json `
  --source-jsonl extracted/source.jsonl `
  --field translation `
  --field target `
  --font build/patch-tree/font/SourceHanSansSC-Regular.otf `
  --license build/patch-tree/font/SourceHanSans-LICENSE.txt `
  --require-license `
  --probe "请动诉嘟" `
  --report qa/font-coverage.json
~~~

对于 TTC，用 `路径::face索引` 指定实际选择的 face，例如 `C:\Windows\Fonts\msyh.ttc::0`。不要用多个 face 的无条件并集掩盖运行时只选择其中一个 face 的事实。

## 运行时字体链调查

在修改字体前先画出加载顺序，并把结论写入 `qa/font-runtime-report.json`：

- 引擎最早读取哪个配置文件，补丁归档和子目录在此时是否已经加入搜索路径。
- 字体文件的真实 family/face 名称是否与脚本中的别名一致。
- 默认字体、语言字体映射、正文层、姓名框、选项、历史记录、设置和存档 UI 分别从哪里取 face。
- 旧存档、系统变量或用户设置是否会在初始化后恢复并覆盖默认 face。
- 游戏是否有自定义 TextRender、缓存的 `defaultFace`、预渲染字库、位图字体或图片文字。
- 字体修改是在新建文本层之前还是之后生效；已有文本层是否需要显式刷新。

不要通过删除用户存档或配置来掩盖持久化覆盖。应在副本上分别测试全新配置和已有配置，并在正确的初始化阶段刷新字体。

## KiriKiri/KAG 专项

以下是调查方向，不是对所有 KiriKiri 游戏都可直接套用的固定补丁：

1. KAG 可能在普通补丁子目录加入搜索路径前读取 `Config.tjs`。若原脚本和最小实验确认如此，把字体引导配置放在补丁归档根目录，并用 `Storages.addAutoPath` 注册实际需要的 `font/`、`main/`、`system/` 或 `sysscn/`。
2. 同时核对 `SystemDefaultFontFace`、`MessageDefaultFontFace`、语言字体映射、历史记录字体及 `font/embfontlist.tjs`。脚本中的别名必须对应字体内部真实 face 名称。
3. KAG 消息层建立后，可在游戏支持时调用 `kag.setMessageLayerUserFont()` 刷新用户字体。若系统变量会恢复旧 `userFace`，应在恢复完成后的初始化回调再次刷新，而不是只改默认配置。
4. 搜索 `getLanguageFont`、`defaultFace`、`TextRender`、`userFace` 和字体缓存。自定义渲染器可能在启动时复制一次 face，之后不会响应全局默认值变化。
5. XP3 构建后必须回读，确认根配置、字体、别名表和初始化脚本以正确大小写进入引擎实际读取的路径。

示意性的自动路径写法如下；归档名和目录必须以目标游戏实测为准：

~~~tjs
Storages.addAutoPath(System.exePath + "patch.xp3>font/");
Storages.addAutoPath(System.exePath + "patch.xp3>main/");
~~~

## 症状分流

| 症状 | 优先检查 |
| --- | --- |
| 个别中文字为空、方框或被跳过 | 实际 face 的 cmap、字体回退、错误的日文字体 |
| cmap 覆盖为 100%，实机仍缺字 | 早期加载顺序、别名不匹配、旧 `userFace`、自定义渲染缓存 |
| 同一中文正文以不同字号重复 | 主/副语言槽或双语显示设置，不属于字体覆盖 |
| 中文上方出现日文小字 | ruby/注音控制，不属于字库缺失 |
| 正文正常但菜单或历史记录异常 | 独立渲染器、独立字体设置、位图或图片文字 |
| 重启前正常、重启后复发 | 持久化设置恢复顺序或字体文件未真正进入补丁 |

## 运行时报告最小字段

`qa/font-runtime-report.json` 至少记录：

- 构建和补丁哈希、游戏版本、测试时间及配置档案（全新或已有）。
- 预期 face、实际加载路径、别名映射和刷新时机。
- `body`、`namebox`、`choice`、`history`、`settings`、`save_title` 各自的 `pass`、`fail` 或 `not_tested`。
- 目标语言特有探针、截图或人工确认的证据位置。
- 已知未覆盖项；只要必测表面仍为 `not_tested`，就不得把字体实机门禁标为完全通过。
