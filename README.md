<p align="center">
  <img src="docs/logo.png" width="100">
  &nbsp;&nbsp;
  <img src="docs/name.png" width="300">
</p>

<h1 align="center">AI Agent for Long-form Web Novel Writing</h1>

<h2 align="center">长篇网络小说写作 AI Agent</h2>

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


## 本次迭代

本次迭代把仿写流程从“传统全书大纲 + 分卷卷纲 + 批次摘要”调整为“核心玩法 + 长短线 + 舞台 + 故事情节单元”。

目标是降低直接换皮相似度，让长篇网文更适合边写边调整，同时为系统文提供稳定的数值/状态约束。

核心变化：

- **核心玩法与长短线替代原先的大纲设计**：`novel-outline` 不再以一次性全书大纲为核心资产，而是先设计核心玩法，再生成全书长线主线、舞台路线图和角色成长线。长线负责持续悬念和期待，舞台内短线负责阶段性爽点、冲突和情绪刺激。
- **舞台驱动故事情节单元**：`stage_roadmap.md` 中的每个舞台承担原先“分卷卷纲”的作用。`story-arcs` 会基于当前舞台，从参考小说故事情节中抽象叙事模式，再生成新书自己的故事情节单元，而不是把参考剧情简单换名。
- **系统文机制层**：新增 `mechanics-init`。系统文、游戏文、领主文、无限流等可初始化机制层，用结构化规则和状态约束系统面板、经验值、技能、任务、资源等内容，避免完全依赖大模型做数字计算。
- **章节细纲层**：`write` 现在先把 ChapterFrame/章纲整理成 1000-2000 字的章节故事梗概，正文渲染后移到下一层，避免从轨迹帧直接跳到正文。
- **目标世界资料库仍作为可选增强**：`world-import` / `world-build` 可导入目标题材资料，供核心玩法、舞台路线和角色线校正目标世界合理性；没有资料库时流程自动降级为参考小说 + 用户方向。


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
- 章节细纲
- 后续正文渲染输入

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

- **全流程自动化**：从拆书分析、玩法设计到章节细纲，串联命令推进长篇小说结构化创作
- **参考仿写**：基于参考小说的节奏、结构、张力曲线生成新内容，而非凭空创作
- **目标世界资料库（可选增强）**：支持导入目标题材资料/设定/样本网文，先结构化为知识库，再用于校验核心玩法、长线主线、舞台路线图和角色线；没有资料库时会自动降级为参考小说 + 用户方向流程
- **叙事抽象防硬换皮**：参考小说先抽象为叙事模式，再结合当前舞台生成新故事情节，降低直接换名搬运的风险；故事情节审计暂时关闭，便于人工调试标准
- **故事情节单元**：参考小说拆书时按自然情节边界提取故事单元，支持跨读取窗口续接
- **玩法/舞台/角色线**：新书先生成核心玩法、全书长线主线、舞台路线图和角色成长线；每个舞台天然对应后续的故事情节生成范围
- **叙事模式仿写**：仿写阶段先压缩当前卷玩法/舞台上下文，再把参考故事情节抽象为叙事模式，生成新书自己的故事情节单元，降低硬换皮相似度
- **舞台式推进**：先设计全书舞台，再按当前舞台生成故事情节单元与章纲，适合长篇网文边写边迭代
- **机制层**：系统文、游戏文、领主文等可初始化机制层，把面板、经验、技能、任务、资源和状态变化交给结构化规则约束
- **章节细纲先行**：默认先生成简短版章节内容，再进入后续正文渲染，降低从章纲直接写正文造成的漂移
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

# 仿写辅助任务：世界观提取（建议 flash 模型）
ADAPTIVE_BUILDER_LITE_MODEL=deepseek-v4-flash
ADAPTIVE_BUILDER_LITE_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_LITE_API_KEY=your-api-key

# 仿写核心任务：玩法、舞台、情节单元、章纲、章节细纲（建议 pro 模型，质量高）
ADAPTIVE_BUILDER_MODEL=deepseek-v4-pro
ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_API_KEY=your-api-key
```

也可通过同名环境变量覆盖配置。三组配置可使用不同的模型和服务商。

## 快速开始

### Phase 1 叙事轨迹流

```bash
# 1. 初始化工作区（有参考小说时会拆解参考结构；没有参考小说也可先创建空工作区）
novel init 我的新小说 --txt /path/to/参考小说.txt --distill-ready

# 2. 蒸馏参考小说追读机制 PatternBank
novel reference-distill 我的新小说

# 3. 从灵感分层生成 StoryContract、NovelSpine、VolumeRoadmap、ArcFrame 和 ChapterFrame
novel trajectory-plan 我的新小说 --direction "灵感输入"

# 4. 审计结构化叙事状态帧
novel trajectory-audit 我的新小说

# 5. 基于 ChapterFrame 解码出的章纲生成章节细纲
novel write 我的新小说 --volume 1 --start 1 --max 5
```

也可以一步生成轨迹后立刻生成前 5 章细纲：

```bash
novel trajectory-plan 我的新小说 --direction "灵感输入" --write-first 5
```

`trajectory-plan` 默认生成 3 卷，每卷 20 章。它会先生成全书主线，再生成分卷路线、情节单元网格和章节轨迹。可用 `--stages` 和 `--chapters-per-stage` 调整规模。

如果不想在 `init` 阶段消耗额外模型调用，可以拆成两步：

```bash
novel init 我的新小说 --txt /path/to/参考小说.txt
novel reference-prepare 我的新小说 --max-chapters 60 --max-arcs 20
novel reference-distill 我的新小说 --max-arcs 20
```

### 传统拆书仿写流

```bash
# 1. 初始化工作区（自动拆书：章节切分→故事情节单元→智能分卷→参考世界观提取）
novel init 我的新小说 --txt /path/to/参考小说.txt

# 2. 生成核心玩法 + 全书长线主线 + 舞台路线图 + 角色成长线
novel novel-outline 我的新小说 --direction "灵感输入"

# 3. 生成指定舞台的故事情节单元
#    会读取 stage_roadmap.md 中的对应舞台，再抽象参考情节的叙事模式
novel story-arcs 我的新小说 --volume 1

# 4. 基于故事情节单元生成逐章章纲
novel chapter-outlines 我的新小说 --volume 1

# 5. 生成章节细纲
novel write 我的新小说 --volume 1 --start 1
```

## 结构化叙事状态层

新流程会在保留 Markdown 资产的同时，自动同步一份机器可读的叙事状态轨迹：

- `file_system/bible/story_bible.json`：全书核心玩法、长线主线、读者契约等 StoryBible。
- `file_system/bible/story_contract.json`：题材、目标读者、核心吸引力和读者承诺。
- `file_system/trajectory/novel_spine.json`：全书主线、中央问题、长线债务和兑现排期。
- `file_system/trajectory/volumes/`：每卷的 VolumeRoadmap。
- `file_system/trajectory/stages/`：兼容旧流程的 StageFrame，由 VolumeRoadmap 解码得到。
- `file_system/trajectory/arcs/`：每个故事情节单元的 ArcFrame。
- `file_system/trajectory/chapters/`：每章的 ChapterFrame，记录目标、情绪曲线、情节点、伏笔、章末钩子和机制事件。
- `file_system/chapter_detail_outlines/`：由 `write` 生成的章节细纲，即 1000-2000 字的章节故事梗概。
- `file_system/ledger/global_state.json`：连续性账本，汇总已规划/已写章节的状态变化、钩子和伏笔。
- `file_system/critics/trajectory/`：基础结构审计报告。
- `reference/reference_manifest.json`：参考小说章节、卷、情节单元稳定索引。
- `reference/cards/chapters/`：参考章节级追读机制卡片。
- `reference/cards/arcs/`：参考情节单元结构卡片。
- `reference/mechanics/`：系统文/游戏文机制检测与机制事件。
- `reference/pattern_bank/`：`trajectory-plan` 优先消费的参考小说 PatternBank。

`novel-outline`、`story-arcs`、`chapter-outlines`、`write` 会在完成后自动同步对应状态帧。已有工作区可手动迁移：

```bash
novel trajectory-sync 我的新小说 --volume 1
novel trajectory-audit 我的新小说 --volume 1
```

## 故事情节单元生成流程

`novel story-arcs 我的新小说 --volume 1` 的作用是把“参考小说提供的叙事经验”转化成“当前新书舞台下可执行的剧情蓝图”。

当前流程不再先生成传统分卷卷纲，再按批次摘要仿写。`stage_roadmap.md` 中的每个舞台就是后续生成的基本单位：

- 它定义当前阶段的空间、规则、敌人、资源、角色节点、长线推进和舞台内短线
- `story-arcs` 会读取当前卷/舞台，并把它压缩成可复用的 `arc_context`

参考小说在这一阶段的作用不是提供可替换的剧情，而是提供可学习的叙事模式。

系统会默认选取一个参考故事情节作为叙事样本，抽象出情节功能、冲突结构、信息差、情绪曲线、爽点机制、关键转折和章末钩子，再结合当前舞台重新生成新书的故事情节单元。

## 章节细纲层

`novel write` 当前不直接生成正文，而是把 `chapter_outlines/` 中的章纲整理成 1000-2000 字的章节故事梗概。

细纲会写入：

- `file_system/chapter_detail_outlines/vol_xx/chapter_yyy.md`

每章细纲会像简短版章节内容一样，用事件流串起开局、冲突、情绪爆点、结果变化和章末钩子，方便作者或后续模型直接扩写成正文。

```bash
# 生成前 5 章章节细纲
novel write 我的新小说 --volume 1 --start 1 --max 5
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

## 已有工作区重建

已有工作区需要按新规则重建资料库、覆盖旧大纲或局部补齐新资产时，再使用以下命令。

```bash
# 重新构建目标世界知识库
novel world-build 我的新小说 --force --primary 主资料.txt --chapter-batch-size 20

# 只基于已生成的 worlds/<资料名>/*.md 重新融合最终资料库
novel world-build 我的新小说 --merge-only --primary 主资料.txt

# 覆盖核心玩法、长线主线、舞台路线图和角色成长线
novel novel-outline 我的新小说 --force --direction "灵感输入"

# 仅重建核心玩法、长线主线、舞台路线图、角色成长线
novel story-design 我的新小说 --force

# 基于灵感插入一个新舞台
novel stage-insert 我的新小说 --direction "新舞台灵感" --after-stage 1

# 初始化或覆盖机制层
novel mechanics-init 我的新小说 --force --file /path/to/mechanics.md

# 覆盖指定卷/舞台的故事情节单元
novel story-arcs 我的新小说 --volume 1 --force

# 覆盖指定卷/舞台的章纲
novel chapter-outlines 我的新小说 --volume 1 --force

# 覆盖指定章节细纲
novel write 我的新小说 --volume 1 --start 1 --max 3 --force
```

## 注意

- 参考小说的格式目前仅支持txt格式，编码需采用utf-8


## 命令参考

| 命令                                                                    | 说明                 |
| --------------------------------------------------------------------- | ------------------ |
| `novel config`                                                        | 初始化全局配置文件          |
| `novel list`                                                          | 列出所有工作区            |
| `novel init <ws> --txt <path> [--batch-size N]`                       | 创建工作区，自动拆书 + 世界观提取 |
| `novel init <ws> --txt <path> --distill-ready`                        | 创建工作区，并准备 reference-distill 所需结构化输入 |
| `novel reference-prepare <ws> [--lite] [--max-chapters N] [--max-arcs N] [--force]` | 准备参考小说 manifest、章节卡、情节卡和机制索引 |
| `novel reference-distill <ws> [--volumes 1,2] [--max-arcs N] [--force]` | 蒸馏参考小说追读机制 PatternBank |
| `novel world-import <ws> <paths...> [--force]`                        | 导入目标题材资料文件或目录      |
| `novel world-build <ws> [--force] [--merge-only] [--primary NAME] [--chapter-batch-size N] [--chunk-size N] [--max-workers N]` | 将目标题材资料结构化为分栏知识库 |
| `novel novel-outline <ws> [--direction TEXT] [--direction-file PATH]` | 生成核心玩法、长线主线、舞台路线图和角色成长线 |
| `novel story-design <ws> [--force] [--direction TEXT] [--direction-file PATH]` | 生成核心玩法、长线主线、舞台路线图和角色成长线 |
| `novel stage-insert <ws> [--direction TEXT] [--direction-file PATH] [--after-stage N] [--before-stage N]` | 基于灵感设计新舞台并插入舞台路线图 |
| `novel mechanics-init <ws> [--file PATH] [--direction TEXT] [--none] [--force]` | 初始化或关闭可选机制层 |
| `novel volume-outline <ws> [--volume N] [--force]`                    | 旧流程兼容：生成卷纲、每卷世界观和每卷舞台计划 |
| `novel story-arcs <ws> [--volume N] [--force]`                        | 按卷/舞台生成故事情节单元和叙事模式 |
| `novel chapter-outlines <ws> [--volume N] [--force]`                  | 基于故事情节单元生成逐章章纲      |
| `novel write <ws> [--volume N] [--start N] [--max N] [--force]` | 串行生成章节细纲，不直接生成正文 |
| `novel trajectory-plan <ws> [--direction TEXT] [--stages N] [--chapters-per-stage N] [--write-first N] [--force]` | Phase 1：从灵感生成结构化叙事轨迹 |
| `novel trajectory-sync <ws> [--volume N]`                              | 从现有 Markdown 资产同步结构化叙事状态帧 |
| `novel trajectory-audit <ws> [--volume N]`                             | 审计结构化叙事状态帧 |

### 参数说明

- `--txt <path>`：参考小说文件路径（仅 init）
- `--batch-size N`：每次读取章节数，用于识别故事情节单元，默认 20（仅 init）
- `--direction TEXT`：创作方向，如"改为现代都市背景"；`novel-outline` 用于生成全书方案，`story-design` 用于单独调整玩法/舞台/角色线
- `--direction-file PATH`：从文件读取创作方向；适用于 `novel-outline` 和 `story-design`
- `--file PATH`：机制层设定文件路径，适用于 `mechanics-init`
- `--none`：显式关闭机制层，适用于 `mechanics-init`
- `--chapter-batch-size N`：章节资料每批章节数，默认 20；识别不到章节时才使用字符分片（仅 world-build）
- `--chunk-size N`：目标题材资料分片字符数，默认 12000（仅 world-build）
- `--max-workers N`：兼容旧版参数；当前 world-build 使用全栏目汇总，通常无需设置
- `--primary NAME`：指定 world-build 主资料，可填文件名、路径或资料 ID；不指定时默认最大文件
- `--merge-only`：只基于已有 `worlds/<资料名>/*.md` 重建 `worlds/_final/` 和审计，不重新提取 cards
- `--volume N`：指定卷号，默认 1；新流程中一卷对应 `stage_roadmap.md` 中的一个舞台
- `--stage N`：兼容旧命令的别名，等同于 `--volume`，不表示“卷内 stage”；适用于 `story-arcs`、`chapter-outlines`、`write`
- `--after-stage N` / `--before-stage N`：插入新舞台时指定相对位置（仅 stage-insert）
- `--start N`：起始章节号，默认 1（仅 write）
- `--max N`：最大生成章节数（仅 write）
- `--no-humanize` / `--humanize-existing`：旧正文生成参数，当前 `write` 细纲模式会忽略
- `--force`：强制重新生成，覆盖已有内容


## 关于作者

飞鸟 one the way — 探索者

<p align="left">
  <img src="docs/qrcode.png" width="400" alt="公众号二维码">
</p>

## Star History

<a href="https://www.star-history.com/?repos=XTmingyue%2FharnessNovel&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=XTmingyue/harnessNovel&type=date&legend=top-left" />
 </picture>
</a>

## License

[GPL-3.0](LICENSE)
