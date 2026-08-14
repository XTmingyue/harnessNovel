<p align="center">
  <img src="docs/logo.svg" width="96" alt="harnessNovel Logo">
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/wordmark-light.svg">
    <img src="docs/wordmark-light.svg" width="320" alt="harnessNovel">
  </picture>
</p>

<h2 align="center">AI Agent for Long-form Web Novel Writing</h2>

<h3 align="center">长篇网络小说写作 AI Agent</h3>

<div align="center">

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-green.svg)](LICENSE)

</div>

<div align="center">

[English](README_EN.md) | 中文

</div>



***

<h3 align="center">让 AI 真正学会写好网文</h3>

<p align="center">
   一个专注于高质量网文创作的 AI 辅助工具。通过「拆书 + 仿写」的双阶段流程，显著提升 AI 生成小说的创作水准。
</p>

***

## 项目背景

目前市面上大多数 AI 小说写作工具普遍存在以下痛点：

- **世界观构建薄弱**：纯依赖大模型生成，在上下文不足的情况下，难以独立构建逻辑自洽、细节丰富、经得起推敲的世界观。
- **严重平均化，缺乏创造力与特色**：模型通过海量平均语料训练，倾向于输出"最平均"的内容，导致人物脸谱化、情节套路化，缺乏独特性。
- **缺乏专业审美与判断力**：AI 训练过程缺少小说好坏的定义和区分，无法理解优秀作品与普通作品的差异，因此生成的内容往往是小说，但和优秀小说还有距离。

**harnessNovel 的解决方案：先拆书，再仿写。**

不让 AI 凭空创作，而是让它先系统学习一部优秀小说的精华，再基于此进行有根基的创新创作。

## 安装

```bash
pip install harnessNovel
```

更新：

```bash
pip install --upgrade harnessNovel
```

<h2 align="left"><img src="docs/heading-web-zh.svg" alt="Web 工作台" height="32"></h2>

项目提供本地可视化工作台。全书设计、舞台设计、故事情节、逐章章纲和正文生成均支持多轮对话，可对生成结果反复调整直到满意后再确认写入。

```bash
novel web
```
默认访问地址为 `http://127.0.0.1:8765`
首次启动会优先使用 `~/Documents/my-novels` 作为工作区根目录，也可以在页面设置中切换，或启动时指定：
```bash
novel web --workspace-root /path/to/my-novels
```

### 界面预览

<table align="center">
  <tr>
    <td><img src="docs/web-ui-1-reference.png" width="450" alt="参考小说拆解"></td>
    <td><img src="docs/web-ui-3-design.png" width="450" alt="全书设计对话"></td>
  </tr>
  <tr>
    <td><img src="docs/web-ui-4-chapters.png" width="450" alt="逐章章纲"></td>
    <td><img src="docs/web-ui-2-config.png" width="450" alt="大模型 API 配置"></td>
  </tr>
</table>


## 核心功能

**结构化拆书**

支持对优秀网文进行多粒度拆解，提取：

- 参考小说整体结构与玩法循环
- 完整世界观设定（规则、势力、体系、背景等）
- 故事结构与阶段推进规律
- 故事情节单元摘要
- 章节核心摘要
- 关键情节节奏与情感节点

**高质量仿写**

以拆书结果作为高质量上下文，结合用户灵感生成：

- 核心玩法
- 全书长线主线
- 舞台路线图
- 角色成长线
- 故事情节单元
- 详细章纲
- 正文内容

**文风 & 写作规范**
从多部小说中深度分析并提炼文风特征与写作规范，帮助去除写作的AI味。

- 语言风格（遣词造句习惯、修辞偏好）
- 叙述节奏与视角控制
- 情感表达方式与细节描写密度
- 对话风格与人物声线
- 整体行文规范

**灵活的大模型支持**

支持 Claude、GPT-4o、DeepSeek、Qwen 等主流模型。

## 工作流程

1. **拆书阶段**：选择高质量小说，一键拆解成结构化知识。
2. **仿写阶段**：输入你的核心灵感 + 拆书结果，让 AI 在"站在巨人肩膀上"的基础上进行创作。
3. **迭代优化**：随时调整核心玩法、舞台、角色线、机制层和章节内容，逐步完善作品。

<p align="center">
  <img src="docs/workflow.png" width="900" alt="工作流程" style="border-radius: 12px;">
</p>

## 特性

- **全流程自动化**：从拆书分析、玩法设计到正文生成，串联命令完成完整长篇小说
- **参考仿写**：基于参考小说的节奏、结构、张力曲线生成新内容，而非凭空创作
- **目标世界资料库（可选增强）**：支持导入目标题材资料/设定/样本网文，先结构化为知识库，再用于校验核心玩法、长线主线、舞台路线图和角色线；没有资料库时会自动降级为参考小说 + 用户方向流程
- **叙事抽象防硬换皮**：参考小说先抽象为叙事模式，再结合当前舞台生成新故事情节，降低直接换名搬运的风险；故事情节审计暂时关闭，便于人工调试标准
- **故事情节单元**：参考小说拆书时按自然情节边界提取故事单元，支持跨读取窗口续接
- **玩法/舞台/角色线**：新书先生成核心玩法、全书长线主线、舞台路线图和角色成长线；每个舞台天然对应后续的故事情节生成范围
- **叙事模式仿写**：仿写阶段先压缩当前卷玩法/舞台上下文，再把参考故事情节抽象为叙事模式，生成新书自己的故事情节单元，降低硬换皮相似度
- **舞台式推进**：先设计全书舞台，再按当前舞台生成故事情节单元与章纲，适合长篇网文边写边迭代
- **机制层**：系统文、游戏文、领主文等可初始化机制层，把面板、经验、技能、任务、资源和状态变化交给结构化规则约束
- **正文去AI味**：基于 [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) 增加章节级后处理，默认对新生成正文执行语言精修，并保留原稿备份
- **断点续写**：所有阶段自动跳过已生成内容，支持中断后继续

## 环境要求

- Python 3.9+
- LLM API：需支持 OpenAI 兼容接口（DeepSeek、智谱 GLM、Kimi 等）

## 安装

```bash
pip install harnessNovel
```

更新：

```bash
pip install --upgrade harnessNovel
```

安装后 `novel` 命令全局可用。

## 配置

```bash
novel config
```

执行后会自动创建全局配置文件 `~/.harnessNovel/.env`，编辑该文件填入你的 API Key：

```ini
# 参考小说故事情节单元提取（建议 flash 模型，速度快、成本低）
DATA_BUILDER_MODEL=deepseek-v4-flash
DATA_BUILDER_BASE_URL=https://api.deepseek.com
DATA_BUILDER_API_KEY=your-api-key

# 故事情节、逐章章纲、正文及轻量辅助任务（建议 flash 模型）
ADAPTIVE_BUILDER_LITE_MODEL=deepseek-v4-flash
ADAPTIVE_BUILDER_LITE_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_LITE_API_KEY=your-api-key

# 全书设计与舞台设计（建议 pro 模型，质量高）
ADAPTIVE_BUILDER_MODEL=deepseek-v4-pro
ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_API_KEY=your-api-key
```

也可通过同名环境变量覆盖配置。三组配置可使用不同的模型和服务商。

## 快速开始

```bash
# 1. 初始化工作区（自动识别编码并按三阶段拆书；可先只拆前 200 章）
novel init 我的新小说 --txt /path/to/参考小说.txt --max-chapters 200

# 后续继续拆到前 400 章，或移除 --max-chapters 以完成整本拆解
novel reference-resume 我的新小说 --max-chapters 400

# 只导入，稍后再决定拆整本还是前 N 章
novel init 我的新小说 --txt /path/to/参考小说.txt --no-analyze

# 2. 生成核心玩法 + 全书长线主线 + 舞台路线图 + 角色成长线
novel novel-outline 我的新小说 --direction "灵感输入"

# 参考小说后续拆解完成后，只追加长线、角色线和后续舞台
# 不会改动核心玩法与书名建议
novel story-design-extend 我的新小说 --use-reference

# 不参考新增拆解，直接基于已有新书设计继续扩展后续舞台
novel story-design-extend 我的新小说

# 3. 生成指定舞台的故事情节单元
#    会读取 stage_roadmap.md 中的对应舞台，再抽象参考情节的叙事模式
novel story-arcs 我的新小说 --volume 1

# 4. 基于故事情节单元生成逐章章纲
novel chapter-outlines 我的新小说 --volume 1

# 5. 生成正文；默认会在每章生成后执行去AI味精修
novel write 我的新小说 --volume 1 --start 1
```

## 故事情节单元生成流程

`novel story-arcs 我的新小说 --volume 1` 的作用是把“参考小说提供的叙事经验”转化成“当前新书舞台下可执行的剧情蓝图”。

当前流程不再先生成传统分卷卷纲，再按批次摘要仿写。`stage_roadmap.md` 中的每个舞台就是后续生成的基本单位：

- 它定义当前阶段的空间、规则、敌人、资源、角色节点、长线推进和舞台内短线
- `story-arcs` 会读取当前卷/舞台，并把它压缩成可复用的 `arc_context`

参考小说在这一阶段的作用不是提供可替换的剧情，而是提供可学习的叙事模式。

系统会默认选取一个参考故事情节作为叙事样本，抽象出情节功能、冲突结构、信息差、情绪曲线、爽点机制、关键转折和章末钩子，再结合当前舞台重新生成新书的故事情节单元。

## 正文去AI味后处理

`novel write` 新增去AI味精修，该步骤规则来源于 [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh)

核心原则包括：删除填充短语、打破公式结构、变化句子节奏、信任读者、删除金句，并针对网文场景额外约束剧情、爽点、章末钩子和机制数值不得被改动。

去除AI味后正文经朱雀AI检测，可保证平均 **80%+** 内容判定为疑似 AI。

- 精修结果写入正式章节文件 `file_system/chapters/vol_xx/`
- 最近一次精修前的原稿保存在 `file_system/drafts/vol_xx/raw_chapters/`；内容变化时，旧快照归档到其 `versions/` 子目录

```bash
# 默认开启：生成正文后自动去AI味
novel write 我的新小说 --volume 1 --start 1

# 关闭去AI味，直接保存原始正文
novel write 我的新小说 --volume 1 --start 1 --no-humanize

# 对已经存在的正文重新执行去AI味
novel write 我的新小说 --volume 1 --start 1 --max 3 --humanize-existing
```

## 可选：机制层 mechanics

如果新书是系统文、游戏文、领主文、无限流，或需要稳定追踪境界、资源、技能、任务、关系状态，可以初始化机制层。

**非系统文可以关闭，后续流程会自动忽略。**

```bash
# 自动判断是否需要机制层：none / light_state / explicit_mechanics
novel mechanics-init 我的新小说

# 通过一句话指定机制设定
novel mechanics-init 我的新小说 --direction "血族吞噬进化系统，包含经验值、血脉纯度、技能树"

# 读取机制设定文件，优先级高于 --direction
novel mechanics-init 我的新小说 --file /path/to/mechanics.md

# 显式关闭机制层
novel mechanics-init 我的新小说 --none --force
```

输出：

- `file_system/mechanics/profile.json`：是否启用、模式、可见面板、严格程度
- `file_system/mechanics/design.md`：机制层设计说明
- `file_system/mechanics/rules.json`：可计算事件、展示规则、模型不可自行修改的约束
- `file_system/mechanics/state.json`：初始状态

模式说明：

- `none`：不启用机制层，不出现系统面板。
- `light_state`：不展示面板，只内部追踪境界、资源、关系、伤势、伏笔状态等。
- `explicit_mechanics`：显式系统/面板/经验/任务/积分/技能树等，章纲只输出机制事件草案，具体数值应由后续程序计算。

`story-arcs`、`chapter-outlines`、`write` 会自动读取 `file_system/mechanics/`。如果机制层未启用，它们只会收到“未启用机制层”的说明，不会强行加入系统面板。

## 可选：目标世界资料库

如果新书需要切换到一个资料要求较高的题材世界，可以在 `novel-outline` 前导入资料并构建知识库。没有资料库时，流程会自动使用“参考小说 + 灵感输入”生成新书方案。

```bash
# 可导入单个文件、多个文件，或资料目录
novel world-import 我的新小说 /path/to/主资料.txt
novel world-import 我的新小说 /path/to/补充资料.txt

# 结构化目标世界知识库；--primary 用于指定主资料
novel world-build 我的新小说 --primary 主资料.txt

# 之后正常生成新书大纲，后台会自动读取资料库
novel novel-outline 我的新小说 --direction "灵感输入"
```

## 注意

- 参考小说目前仅支持 `.txt`；导入时会自动检测常见中文编码并转换为 UTF-8。


## 命令参考

| 命令                                                                    | 说明                 |
| --------------------------------------------------------------------- | ------------------ |
| `novel config`                                                        | 初始化全局配置文件          |
| `novel web [--host HOST] [--port PORT] [--workspace-root PATH]`      | 启动本地可视化工作台        |
| `novel list`                                                          | 列出所有工作区            |
| `novel init <ws> --txt <path> [--batch-size N] [--max-chapters N] [--no-analyze]` | 创建工作区，自动识别编码并按三阶段拆书；可只导入 |
| `novel reference-resume <ws> [--batch-size N] [--max-chapters N]` | 继续或重试参考拆解 |
| `novel world-import <ws> <paths...> [--force]`                        | 导入目标题材资料文件或目录      |
| `novel world-build <ws> [--force] [--merge-only] [--primary NAME] [--chapter-batch-size N] [--chunk-size N] [--max-workers N]` | 将目标题材资料结构化为分栏知识库 |
| `novel novel-outline <ws> [--direction TEXT] [--direction-file PATH]` | 生成核心玩法、长线主线、舞台路线图和角色成长线 |
| `novel story-design <ws> [--force] [--direction TEXT] [--direction-file PATH]` | 生成核心玩法、长线主线、舞台路线图和角色成长线 |
| `novel story-design-extend <ws> [--use-reference] [--direction TEXT] [--direction-file PATH]` | 保留已有内容，追加长线、角色线和后续舞台 |
| `novel stage-insert <ws> [--direction TEXT] [--direction-file PATH] [--after-stage N] [--before-stage N]` | 基于灵感设计新舞台并插入舞台路线图 |
| `novel mechanics-init <ws> [--file PATH] [--direction TEXT] [--none] [--force]` | 初始化或关闭可选机制层 |
| `novel volume-outline <ws> [--volume N] [--force]`                    | 旧流程兼容：生成卷纲、每卷世界观和每卷舞台计划 |
| `novel story-arcs <ws> [--volume N] [--force]`                        | 按卷/舞台生成故事情节单元和叙事模式 |
| `novel chapter-outlines <ws> [--volume N] [--force]`                  | 基于故事情节单元生成逐章章纲      |
| `novel write <ws> [--volume N] [--start N] [--max N] [--no-humanize] [--humanize-existing]` | 串行生成正文，默认生成后执行去AI味 |

### 参数说明

- `--txt <path>`：参考小说文件路径（仅 init）
- `--batch-size N`：每次读取章节数，用于识别故事情节单元，默认 20（仅 init）
- `--direction TEXT`：创作方向，如"改为现代都市背景"；`novel-outline` 用于生成全书方案，`story-design` 用于单独调整玩法/舞台/角色线，`story-design-extend` 用于补充后续设计
- `--direction-file PATH`：从文件读取创作方向；适用于 `novel-outline`、`story-design` 和 `story-design-extend`
- `--use-reference`：`story-design-extend` 读取上次全书设计后新增的参考故事片段；不传时只基于已有新书设计续写
- `--file PATH`：机制层设定文件路径，适用于 `mechanics-init`
- `--none`：显式关闭机制层，适用于 `mechanics-init`
- `--chapter-batch-size N`：章节资料每批章节数，默认 20；识别不到章节时才使用字符分片（仅 world-build）
- `--chunk-size N`：目标题材资料分片字符数，默认 36000（仅 world-build；章节资料同时受每批最多 20 章限制）
- `--max-workers N`：目标世界资料章节批次的并行提取数，默认 4；全部批次完成后再串行汇总
- `--max-workers N`：兼容旧版参数；当前 world-build 使用全栏目汇总，通常无需设置
- `--primary NAME`：指定 world-build 主资料，可填文件名、路径或资料 ID；不指定时默认最大文件
- `--merge-only`：只基于已有 `worlds/<资料名>/*.md` 重建 `worlds/_final/` 和审计，不重新提取 cards
- `--volume N`：指定卷号，默认 1；新流程中一卷对应 `stage_roadmap.md` 中的一个舞台
- `--stage N`：兼容旧命令的别名，等同于 `--volume`，不表示“卷内 stage”；适用于 `story-arcs`、`chapter-outlines`、`write`
- `--after-stage N` / `--before-stage N`：插入新舞台时指定相对位置（仅 stage-insert）
- `--start N`：起始章节号，默认 1（仅 write）
- `--max N`：最大生成章节数（仅 write）
- `--no-humanize`：关闭正文生成后的自动去AI味后处理（仅 write）
- `--humanize-existing`：对已存在正文执行去AI味；默认只处理本次新生成章节（仅 write）
- `--force`：强制重新生成，覆盖已有内容


## 关于作者

飞鸟 one the way — 探索者

<p align="left">
  <img src="docs/qrcode.png" width="400" alt="公众号二维码">
</p>

## Star History

## Star History

## Star History

<a href="https://www.star-history.com/?repos=XTmingyue%2FharnessNovel&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&theme=dark&legend=top-left&sealed_token=pXVarvqjLwVGWU1ssO117sGXYJwt6q91Yf-QqTmDpDqz8roh31aOfNBVcB7ygXPCW6crcRbHychzuSUkX9fWEAg879re3tYB2rHmIF8MVG1GKrEF5HLS4w" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&legend=top-left&sealed_token=pXVarvqjLwVGWU1ssO117sGXYJwt6q91Yf-QqTmDpDqz8roh31aOfNBVcB7ygXPCW6crcRbHychzuSUkX9fWEAg879re3tYB2rHmIF8MVG1GKrEF5HLS4w" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&legend=top-left&sealed_token=pXVarvqjLwVGWU1ssO117sGXYJwt6q91Yf-QqTmDpDqz8roh31aOfNBVcB7ygXPCW6crcRbHychzuSUkX9fWEAg879re3tYB2rHmIF8MVG1GKrEF5HLS4w" />
 </picture>
</a>

## License

[GPL-3.0](LICENSE)
