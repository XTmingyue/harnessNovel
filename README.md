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

本次迭代重点解决基于参考小说+灵感设计新世界观时出现的不合理的问题，主要体现在进行新世界观设计时缺少辅助的资料。
比如参考小说为西游世界观，新世界为封神世界观，需要增加封神世界观相关资料，保证设计合理。

新增能力：

- `world-import`：可选，导入一个或多个目标题材资料文件/目录
- `world-build`：可选，把导入资料结构化为分栏知识库，供后续大纲和世界观生成使用
- `novel-outline`：若存在资料库，则根据参考小说 + 灵感生成初稿，再结合知识库做合理性校正。如果没有资料库，则直接基于参考小说 + 灵感生成大纲和世界观


## 核心功能

**结构化拆书**

支持对优秀网文进行多粒度拆解，提取：

- 全书大纲
- 完整世界观设定（规则、势力、体系、背景等）
- 卷纲设计
- 章节核心摘要
- 关键情节节奏与情感节点

**高质量仿写**

以拆书结果作为高质量上下文，结合用户灵感生成：

- 全书大纲
- 世界观框架
- 卷纲
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
3. **迭代优化**：随时调整大纲、世界观、章节内容，逐步完善作品。

<p align="center">
  <img src="docs/workflow.png" width="720" alt="工作流程" style="border-radius: 12px;">
</p>

## 特性

- **全流程自动化**：从拆书分析到正文生成，5 条命令完成完整长篇小说
- **参考仿写**：基于参考小说的节奏、结构、张力曲线生成新内容，而非凭空创作
- **目标世界资料库（可选增强）**：支持导入目标题材资料/设定/样本网文，先结构化为知识库，再用于校验新书大纲和世界观；没有资料库时会自动降级为参考小说 + 用户方向流程
- **换皮防污染**：生成换皮映射表，批次摘要、章纲、正文都会读取硬约束并进行禁用词审计
- **批次摘要**：每 20 章一个批次，保持长线情节连贯性
- **渐进式世界观**：全书世界观 → 每卷世界观，随情节推进细化设定
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
# 参考小说批次摘要提取（建议 flash 模型，速度快、成本低）
DATA_BUILDER_MODEL=deepseek-v4-flash
DATA_BUILDER_BASE_URL=https://api.deepseek.com
DATA_BUILDER_API_KEY=your-api-key

# 仿写辅助任务：世界观提取（建议 flash 模型）
ADAPTIVE_BUILDER_LITE_MODEL=deepseek-v4-flash
ADAPTIVE_BUILDER_LITE_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_LITE_API_KEY=your-api-key

# 仿写核心任务：大纲、卷纲、章纲、正文（建议 pro 模型，质量高）
ADAPTIVE_BUILDER_MODEL=deepseek-v4-pro
ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_API_KEY=your-api-key
```

也可通过同名环境变量覆盖配置。三组配置可使用不同的模型和服务商。

## 快速开始

```bash
# 1. 初始化工作区（自动拆书：章节切分→批次摘要→智能分卷→参考世界观提取）
novel init 我的新小说 --txt /path/to/参考小说.txt

# 2. 可选：导入资料，可导入多本，用于新小说世界观设计
novel world-import 我的新小说 doc1.txt
novel world-import 我的新小说 doc2.txt

# 3. 可选：结构化目标世界知识库，--primary用于指定主资料
novel world-build 我的新小说 --primary doc1.txt

# 4. 生成新小说大纲 + 全书世界观
#    有资料库时会先生成初稿，再基于目标世界知识库校正；无资料库时自动跳过校正
novel novel-outline 我的新小说 --direction "灵感输入"

# 5. 生成卷纲 + 每卷世界观
novel volume-outline 我的新小说 --volume 1

# 6. 生成批次摘要 + 逐章章纲
#    会先适配参考批次，再生成新批次摘要，并进行旧世界残留审计
novel chapter-outlines 我的新小说 --volume 1

# 7. 生成正文
novel write 我的新小说 --volume 1 --start 1
```

已有工作区需要按新规则重建资料库或覆盖旧结果时，可使用：

```bash
novel world-build 我的新小说 --force --primary doc1.txt --chapter-batch-size 20
novel novel-outline 我的新小说 --force --direction "灵感输入"
novel volume-outline 我的新小说 --volume 1 --force
novel chapter-outlines 我的新小说 --volume 1 --force
```

## 注意

- 参考小说的格式目前仅支持txt格式，编码需采用utf-8


## 命令参考

| 命令                                                                    | 说明                 |
| --------------------------------------------------------------------- | ------------------ |
| `novel config`                                                        | 初始化全局配置文件          |
| `novel list`                                                          | 列出所有工作区            |
| `novel init <ws> --txt <path> [--batch-size N]`                       | 创建工作区，自动拆书 + 世界观提取 |
| `novel world-import <ws> <paths...> [--force]`                        | 导入目标题材资料文件或目录      |
| `novel world-build <ws> [--force] [--merge-only] [--primary NAME] [--chapter-batch-size N] [--chunk-size N] [--max-workers N]` | 将目标题材资料结构化为分栏知识库 |
| `novel novel-outline <ws> [--direction TEXT] [--direction-file PATH]` | 生成新小说大纲和全书世界观      |
| `novel volume-outline <ws> [--volume N] [--force]`                    | 生成卷纲和每卷世界观         |
| `novel chapter-outlines <ws> [--volume N] [--force]`                  | 两阶段生成：批次摘要 → 逐章章纲  |
| `novel write <ws> [--volume N] [--start N] [--max N]`                 | 串行生成正文             |

### 参数说明

- `--txt <path>`：参考小说文件路径（仅 init）
- `--batch-size N`：每批处理章节数，默认 20（仅 init）
- `--direction TEXT`：创作方向，如"改为现代都市背景"（仅 novel-outline）
- `--direction-file PATH`：从文件读取创作方向（仅 novel-outline）
- `--chapter-batch-size N`：章节资料每批章节数，默认 20；识别不到章节时才使用字符分片（仅 world-build）
- `--chunk-size N`：目标题材资料分片字符数，默认 12000（仅 world-build）
- `--max-workers N`：兼容旧版参数；当前 world-build 使用全栏目汇总，通常无需设置
- `--primary NAME`：指定 world-build 主资料，可填文件名、路径或资料 ID；不指定时默认最大文件
- `--merge-only`：只基于已有 `worlds/<资料名>/*.md` 重建 `worlds/_final/` 和审计，不重新提取 cards
- `--volume N`：指定卷号，默认 1
- `--start N`：起始章节号，默认 1（仅 write）
- `--max N`：最大生成章节数（仅 write）
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
