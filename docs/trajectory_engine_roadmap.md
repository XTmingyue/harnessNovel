# 长篇网文叙事轨迹引擎路线图

更新时间：2026-07-02

本文档用于保存当前项目重构方向、Phase 0 + Phase 1 已完成内容，以及后续 Phase 2+ 的实现路线，避免后续上下文丢失。

## 核心定位

项目不再只定位为“AI 小说生成器”，而是：

长篇网文叙事轨迹引擎。

目标是把一个灵感扩展成一条可持续连载、可审计、可修复、可训练的故事状态轨迹。

核心优化对象不是句子是否通顺，而是：

- 读者契约是否清楚
- 情绪刺激是否有效
- 章节是否有追读欲
- 主角状态变化是否连续
- 伏笔、资源、能力、关系是否可追踪
- 长线主线是否持续牵引
- 参考小说是否只被学习结构，而不是换皮搬运

## Diffusion 思路的落地方式

这里采用 diffusion-like 的生成范式，但不在第一阶段直接训练文本 DiT。

核心思想：

```text
噪声/灵感
→ 粗糙全书轨迹
→ 修正后的全书轨迹
→ 分卷/舞台轨迹
→ 情节单元轨迹
→ 章节关键帧
→ 场景帧
→ 正文
```

对应文生视频类比：

```text
Condition Encoder
= 用户灵感 + 对标小说 + 题材资料 + 类型契约

DiT / diffusion core
= 生成并反复修正全书叙事状态轨迹

VAE / decoder
= ChapterFrame / SceneFrame → 章纲 → 正文

插帧 / 超分
= 场景扩展、对白增强、文风增强、去 AI 味、节奏润色
```

关键判断：

小说的 latent 不应该第一步就是不可读向量，而应该先是可读、可审计、可编辑的结构化状态帧。等数据积累后，再训练真正的 trajectory denoiser 或 latent trajectory diffusion。

## 总体架构

```text
灵感 / 对标小说 / 题材资料
→ StoryContract
→ StoryBible
→ NovelSpine
→ VolumeRoadmap
→ StageFrame
→ ArcFrame
→ ChapterFrame
→ SceneFrame
→ 正文
→ Ledger 连续性账本
→ Critic 审计报告
→ Repair 去噪
```

核心资产：

- StoryContract：题材、目标读者、核心吸引力、读者承诺、成功标准。
- StoryBible：全书核心玩法、长线主线、简介、硬约束。
- NovelSpine：全书中央问题、终局方向、长线债务、兑现排期和分卷功能。
- VolumeRoadmap：分卷路线，定义本卷功能、短期目标、旧债兑现、新债制造和状态锚点。
- StageFrame：兼容旧流程的舞台/副本级状态帧，由 VolumeRoadmap 解码得到。
- ArcFrame：故事情节单元级状态帧。
- ChapterFrame：章节关键帧。
- SceneFrame：场景关键帧，Phase 0 已建模型，后续阶段接入。
- ContinuityLedger：连续性账本。
- CriticReport：审计报告。

## 已完成：Phase 0

Phase 0 目标：定义叙事状态协议。

已实现文件：

- `core/models.py`
  - `StoryContract`
  - `StoryBible`
  - `NovelSpine`
  - `VolumeRoadmap`
  - `StageFrame`
  - `ArcFrame`
  - `ChapterFrame`
  - `SceneFrame`
  - `CriticIssue`
  - `CriticReport`
  - `ContinuityLedger`

- `core/repository.py`
  - 结构化资产读写
  - `file_system/bible/story_contract.json`
  - `file_system/bible/story_bible.json`
  - `file_system/trajectory/novel_spine.json`
  - `file_system/trajectory/volumes/`
  - `file_system/trajectory/stages/`
  - `file_system/trajectory/arcs/`
  - `file_system/trajectory/chapters/`
  - `file_system/trajectory/scenes/`
  - `file_system/ledger/global_state.json`
  - `file_system/critics/trajectory/`

- `core/frame_extractor.py`
  - 从旧 Markdown 资产解析 `StageFrame`、`ArcFrame`、`ChapterFrame`

- `core/validators.py`
  - 基础 deterministic critic
  - 检查缺章数、缺核心事件、缺情绪曲线、缺钩子、章节断档等硬问题

- `training/trajectory_builder.py`
  - 从现有 Markdown 资产同步结构化状态帧
  - 生成基础审计报告
  - 同步连续性账本

新增 CLI：

```bash
novel trajectory-sync <workspace> [--volume N]
novel trajectory-audit <workspace> [--volume N]
```

## 已完成：Phase 1

Phase 1 目标：不训练模型，先用 LLM 跑通“灵感 → 全书主线 → 分卷路线 → 情节单元 → 章节轨迹 → 章节细纲”的 MVP。

新增文件：

- `training/phase1_builder.py`
  - Phase 1 主生成器
  - 从灵感/参考小说/目标世界资料生成 `StoryContract` 与 `StoryBible`
  - 先生成 `NovelSpine`
  - 再逐卷生成 `VolumeRoadmap`
  - 基于分卷路线生成 `ArcFrame`
  - 最后基于情节单元生成 `ChapterFrame`
  - 将 `ChapterFrame` 解码成现有 `chapter_outlines`
  - 可选直接调用现有 `write` 生成前 N 章章节细纲

- `core/prompts/phase1_story_contract/prompt.txt`
  - 生成 `StoryContract + StoryBible`

- `core/prompts/phase1_novel_spine/prompt.txt`
  - 生成全书主线 `NovelSpine`

- `core/prompts/phase1_volume_roadmap/prompt.txt`
  - 生成单卷路线 `VolumeRoadmap`

- `core/prompts/phase1_arc_lattice/prompt.txt`
  - 生成卷内情节单元 `ArcFrame[]`

- `core/prompts/phase1_chapter_trajectory/prompt.txt`
  - 生成章节轨迹 `ChapterFrame[]`

新增 CLI：

```bash
novel trajectory-plan <workspace> \
  --direction "灵感输入" \
  --stages 3 \
  --chapters-per-stage 20
```

默认生成：

```text
StoryContract
→ StoryBible
→ NovelSpine
→ 3 个 VolumeRoadmap
→ 每卷若干 ArcFrame
→ 每卷 20 个 ChapterFrame
→ chapter_outlines
```

可直接生成前几章细纲：

```bash
novel trajectory-plan <workspace> --direction "灵感输入" --write-first 5
```

Phase 1 推荐流程：

```bash
novel init 我的新小说 --txt /path/to/参考小说.txt --distill-ready
novel reference-distill 我的新小说
novel trajectory-plan 我的新小说 --direction "灵感输入"
novel trajectory-audit 我的新小说
novel write 我的新小说 --volume 1 --start 1 --max 5
```

## 已完成：Reference Prepare / Distill 基础链路

为让 `trajectory-plan` 不只读取参考大纲，而是能读取参考小说的追读机制，新增 reference 侧结构化资产。

新增模型：

- `ReferenceManifest`
- `ReferenceChapterCard`
- `ReferenceArcCard`
- `MechanicsProfile`
- `MechanicsEvent`
- `ReferencePatternBank`
- `MechanicsPatternBank`

新增文件：

- `core/reference_repository.py`
- `training/reference_prepare.py`
- `training/reference_distiller.py`
- `core/prompts/reference_mechanics_detect/prompt.txt`
- `core/prompts/reference_chapter_card_extract/prompt.txt`
- `core/prompts/reference_arc_card_extract/prompt.txt`
- `core/prompts/reference_pattern_distill/prompt.txt`
- `core/prompts/reference_mechanics_pattern_distill/prompt.txt`

新增 CLI：

```bash
novel reference-prepare <workspace> [--lite] [--max-chapters N] [--max-arcs N] [--force]
novel reference-distill <workspace> [--volumes 1,2] [--max-arcs N] [--force]
```

`novel init` 新增：

```bash
novel init <workspace> --txt <path> --distill-ready
```

reference 侧新增产物：

```text
reference/reference_manifest.json
reference/cards/chapters/
reference/cards/arcs/
reference/mechanics/mechanics_profile.json
reference/mechanics/events/
reference/distill_inputs/arcs/
reference/pattern_bank/reference_patterns.json
reference/pattern_bank/mechanics_patterns.json
```

`training/phase1_builder.py` 的 `trajectory-plan` 已改为优先读取：

```text
reference/pattern_bank/reference_patterns.json
reference/pattern_bank/mechanics_patterns.json
```

如果不存在 PatternBank，会降级读取参考大纲/世界观，并提示建议运行 `novel reference-distill`。

`trajectory-audit` 已增加轻量 mechanics presence audit：如果参考小说检测到 mechanics enabled，但生成章节帧缺少 `mechanics_events`，会输出审计问题。

## 当前两条生成路线

### 新路线：Phase 1 叙事轨迹流

```text
init
→ trajectory-plan
→ trajectory-audit
→ write
```

特点：

- 直接围绕结构化状态轨迹生成
- 更接近 diffusion-like planner
- 先生成章节关键帧，再生成 1000-2000 字章节故事梗概，最后才进入正文渲染

### 旧路线：传统拆书仿写流

```text
init
→ novel-outline
→ story-arcs
→ chapter-outlines
→ write
```

特点：

- 继续保留旧流程
- 已接入自动同步结构化状态帧
- 适合继续利用原有 prompt 与拆书资产

## 后续 Phase 2：Critic / Repair 去噪循环

目标：把 diffusion 思路真正变成“生成 → 审计 → 修复 → 再审计”的局部去噪闭环。

建议新增模块：

```text
critics/
  continuity_critic.py
  emotion_critic.py
  hook_critic.py
  genre_critic.py
  similarity_critic.py
  longline_critic.py

repair/
  frame_repairer.py
```

或先保持当前包结构，新增：

```text
training/trajectory_critic.py
training/trajectory_repair.py
core/prompts/trajectory_repair/prompt.txt
```

Phase 2 流程：

```text
ChapterFrame / StageFrame
→ deterministic critic + LLM critic
→ CriticReport
→ repair instruction
→ 局部重写 frame
→ 再审计
```

新增 CLI 建议：

```bash
novel trajectory-repair <workspace> [--volume N] [--max-rounds 2]
```

验收标准：

- critic 能指出具体章节的问题
- repair 后 failed reports 数量下降
- 不必整卷重写，可以局部修复章节帧

## 后续 Phase 3：轨迹编辑器

目标：让用户编辑的是故事轨迹，而不是只编辑正文。

核心视图：

- 全书情绪曲线
- 舞台地图
- ChapterFrame 列表
- 伏笔账本
- 角色状态表
- 能力/资源变化表
- critic 问题面板

可先做 CLI/HTML 静态报告，不急着做完整 UI。

建议命令：

```bash
novel trajectory-report <workspace> [--volume N]
```

输出：

```text
file_system/reports/trajectory_report.html
```

## 后续 Phase 4：数据引擎

目标：为训练真正的 denoiser 积累数据。

需要沉淀的数据：

```text
idea → StoryContract
StoryContract + StoryBible → NovelSpine
NovelSpine → VolumeRoadmap
VolumeRoadmap → ArcFrame sequence
ArcFrame sequence → ChapterFrame sequence
bad_frame + critic_report → repaired_frame
ChapterFrame → outline
ChapterFrame + outline → prose
```

重点是 repair 数据：

```text
broken_frame + critic_report → repaired_frame
```

这会成为后续 structured denoiser 的核心训练样本。

## 后续 Phase 5：Structured Denoiser

目标：训练第一个真正的去噪模型。

输入：

```text
损坏的 ChapterFrame
+ StoryBible
+ Ledger
+ CriticReport
```

输出：

```text
修复后的 ChapterFrame
```

加噪方式：

- 删除章末钩子
- 打乱情绪曲线
- 制造能力断裂
- 提前泄露伏笔
- 让角色关系突变
- 让章节目标变空

## 后续 Phase 6：Latent Trajectory Diffusion

目标：训练真正的 latent trajectory diffusion。

结构：

```text
Condition Encoder
→ latent trajectory noise
→ DiT / Transformer denoiser
→ ChapterFrame sequence
→ SceneFrame
→ Text Decoder
```

注意：

这一阶段不应该直接生成正文 token，而应该生成结构化状态帧的 latent sequence。

## 重要设计原则

1. 正文是渲染层，不是核心状态。
2. 长篇创作的核心是状态轨迹，不是单章续写。
3. Critic 比 Writer 更关键。
4. diffusion 思想先作为工程范式落地，再训练成模型。
5. 所有关键资产都要可读、可编辑、可审计、可导出训练数据。
6. 旧流程保留，但新路线优先发展 `trajectory-plan → trajectory-audit → trajectory-repair → write`。

## 当前验证记录

已执行：

```bash
python3 -m compileall core training novel_cli.py
python3 novel_cli.py trajectory-plan --help
git diff --check
```

已做 smoke test：

- `StoryContract` / `SceneFrame` dataclass 可序列化
- `ChapterFrame` 可解码为旧格式章纲
- `global_chapter` 按真实舞台章节数计算

未执行：

- 未实际调用线上 LLM 完整跑 `trajectory-plan`
- 未用真实工作区验证 `--write-first`

后续第一次继续实现时，建议先用小规模命令真实试跑：

```bash
novel init 测试小说 --txt /path/to/参考小说.txt --distill-ready --max-prepare-chapters 5 --max-prepare-arcs 2
novel reference-distill 测试小说 --max-arcs 2
novel trajectory-plan 测试小说 --direction "一个一句话灵感" --stages 1 --chapters-per-stage 3 --force
novel trajectory-audit 测试小说
novel write 测试小说 --volume 1 --start 1 --max 1 --no-humanize
```
