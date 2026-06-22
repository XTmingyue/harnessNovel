<p align="center">
  <img src="docs/logo.png" width="100">
  &nbsp;&nbsp;
  <img src="docs/name.png" width="300">
</p>

<h1 align="center">AI Agent for Long-form Web Novel Writing</h1>

<h2 align="center">Long-form Web Novel Writing AI Agent</h2>

<div align="center">

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-green.svg)](LICENSE)

</div>

<div align="center">

English | [中文](README.md)

</div>

***

<h3 align="center">Teach AI to truly write good web novels</h3>

<p align="center">
  An AI-assisted tool focused on high-quality web novel creation. Through a two-stage "deconstruct + imitate" workflow, it significantly improves the creative quality of AI-generated fiction.
</p>

***

## Project Background

Most AI novel writing tools currently on the market share several common pain points:

- **Weak worldbuilding**: When relying purely on LLM generation, models struggle to independently build logically consistent, richly detailed, and convincing worlds without enough context.
- **Severe averaging, lack of creativity and distinctive style**: Because models are trained on massive average corpora, they tend to output the "most average" content, leading to flat characters, formulaic plots, and little uniqueness.
- **Lack of professional taste and judgment**: AI training does not clearly define or distinguish good fiction from mediocre fiction, so the generated text may look like a novel while still falling short of excellent fiction.

**harnessNovel's solution: deconstruct first, then imitate.**

Instead of asking AI to create from nothing, harnessNovel first lets it systematically study the essence of an excellent novel, then create new work on a stronger foundation.

## Current Iteration

This iteration changes the imitation flow from “traditional full-book outline + volume outline + batch summary” to “core gameplay + long/short lines + stages + story-arc units”.

The goal is to reduce direct reskin similarity, make long web novels easier to adjust while writing, and provide stable numeric/state constraints for system novels.

Key changes:

- **Core gameplay and long/short lines replace the old outline-centered design**: `novel-outline` no longer treats a one-shot full-book outline as the central asset. It first designs core gameplay, then generates the long-running mainline, stage roadmap, and character arcs. The long line maintains suspense and expectation; stage-level short lines create local payoffs, conflicts, and emotional beats.
- **Stage-driven story-arc units**: Each stage in `stage_roadmap.md` replaces the role of the old volume outline. `story-arcs` abstracts narrative patterns from reference story arcs, then regenerates new story arcs against the current stage instead of renaming reference plots.
- **Mechanics layer for system novels**: `mechanics-init` adds an optional mechanics layer. System novels, game novels, lord-management novels, and infinite-flow novels can use structured rules and state to constrain panels, exp, skills, tasks, resources, and other numeric/state elements instead of relying fully on the model for calculation.
- **Chapter humanization post-processing**: `write` now runs a humanization pass after each generated chapter by default. The rules are sourced from [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) to reduce formulaic structures, summary tone, promotional tone, and mechanical emotion labels.
- **Target-world knowledge remains optional**: `world-import` / `world-build` can import target-genre materials to calibrate the plausibility of core gameplay, stage roadmap, and character arcs. Without a knowledge base, the flow falls back to reference novel + user direction.

## Core Features

**Structured Novel Deconstruction**

Supports multi-granularity deconstruction of excellent web novels, extracting:

- Overall structure and gameplay loop of the reference novel
- Complete worldview settings: rules, factions, systems, background, and more
- Story structure and stage-progression patterns
- Story-arc summaries
- Chapter-level core summaries
- Key plot pacing and emotional beats

**High-quality Imitative Writing**

Uses deconstruction results as high-quality context, combined with user inspiration, to generate:

- Core gameplay
- Long-running mainline
- Stage roadmap
- Character arcs
- Story arcs
- Detailed chapter outlines
- Full text content

**Writing Style & Writing Rules**

Deeply analyzes and distills style features and writing rules from multiple novels, helping remove the "AI flavor" from generated writing.

- Language style: word choice habits, sentence patterns, rhetorical preferences
- Narrative pacing and point-of-view control
- Emotional expression and detail density
- Dialogue style and character voices
- Overall prose conventions

**Flexible LLM Support**

Supports Claude, GPT-4o, DeepSeek, Qwen, and other mainstream models.

## Workflow

1. **Deconstruction stage**: Choose a high-quality novel and deconstruct it into structured knowledge with one command.
2. **Imitation stage**: Input your core inspiration + deconstruction results, then let AI create while "standing on the shoulders of giants."
3. **Iterative refinement**: Adjust core gameplay, stages, character lines, mechanics, and chapter content at any time to gradually improve the work.

<p align="center">
  <img src="docs/workflow.png" width="900" alt="Workflow" style="border-radius: 12px;">
</p>

## Features

- **End-to-end automation**: From novel analysis and gameplay design to full text generation, complete a long-form web novel with chained commands.
- **Reference-based imitation**: Generate new content based on the pacing, structure, and tension curve of the reference novel instead of creating from nothing.
- **Target-world knowledge base (optional enhancement)**: Import target-genre materials/settings/sample web novels, structure them into a knowledge base, and use it to validate the core gameplay, long mainline, stage roadmap, and character arcs. Without a knowledge base, the workflow automatically falls back to reference novel + user direction.
- **Narrative abstraction against hard reskins**: Reference arcs are first abstracted into narrative patterns, then regenerated against the current stage context to reduce direct rename-and-copy behavior. Story-arc auditing is currently disabled while the audit criteria are being refined.
- **Story arcs**: During reference deconstruction, story units are extracted by natural plot boundaries and can continue across reading windows.
- **Gameplay/stage/character lines**: The new novel first gets core gameplay, a long-running mainline, a stage roadmap, and character arcs. Each stage naturally becomes the scope for later story-arc generation.
- **Narrative-pattern imitation**: During imitation, the current-volume gameplay/stage context is compressed first; reference story arcs are then abstracted into narrative patterns and regenerated as new-novel story arcs to reduce hard reskin similarity.
- **Stage-based progression**: Design the full-book stages first, then generate story arcs and chapter outlines for the current stage. This fits long web novels that evolve during writing.
- **Mechanics layer**: System novels, game novels, lord-management novels, and similar genres can initialize structured mechanics to constrain panels, exp, skills, tasks, resources, and state changes.
- **Chapter humanization**: Based on [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh), newly generated chapters are refined by default and raw drafts are backed up.
- **Resume from breakpoint**: Every stage automatically skips existing output and supports continuing after interruption.

## Requirements

- Python 3.9+
- LLM API: must support an OpenAI-compatible interface, such as DeepSeek, Zhipu GLM, Kimi, etc.

## Installation

```bash
pip install harnessNovel
```

Update:

```bash
pip install --upgrade harnessNovel
```

After installation, the `novel` command is globally available.

## Configuration

```bash
novel config
```

This command automatically creates the global config file `~/.harnessNovel/.env`. Edit it and fill in your API keys:

```ini
# Reference novel story-arc extraction (flash model recommended for speed and low cost)
DATA_BUILDER_MODEL=deepseek-v4-flash
DATA_BUILDER_BASE_URL=https://api.deepseek.com
DATA_BUILDER_API_KEY=your-api-key

# Imitation auxiliary tasks: worldview extraction (flash model recommended)
ADAPTIVE_BUILDER_LITE_MODEL=deepseek-v4-flash
ADAPTIVE_BUILDER_LITE_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_LITE_API_KEY=your-api-key

# Imitation core tasks: gameplay, stages, story arcs, chapter outlines, full text (pro model recommended for quality)
ADAPTIVE_BUILDER_MODEL=deepseek-v4-pro
ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
ADAPTIVE_BUILDER_API_KEY=your-api-key
```

You can also override these settings with environment variables of the same names. The three config groups can use different models and providers.

## Quick Start

```bash
# 1. Initialize a workspace
#    Automatically deconstructs the reference novel: chapter splitting -> story arcs -> smart volume splitting -> reference worldview extraction
novel init my-new-novel --txt /path/to/reference-novel.txt

# 2. Generate core gameplay + long mainline + stage roadmap + character arcs
novel novel-outline my-new-novel --direction "inspiration input"

# 3. Generate story arcs for a stage
#    This reads the matching stage from stage_roadmap.md and abstracts reference arcs into narrative patterns.
novel story-arcs my-new-novel --volume 1

# 4. Generate chapter outlines from the story arcs.
novel chapter-outlines my-new-novel --volume 1

# 5. Generate full text. By default, each generated chapter is humanized afterward.
novel write my-new-novel --volume 1 --start 1
```

## Story-arc Generation Flow

`novel story-arcs my-new-novel --volume 1` converts the narrative experience extracted from the reference novel into executable plot blueprints for the current stage of the new novel.

The current flow no longer generates a traditional volume outline and then imitates coarse batch summaries. Each stage in `stage_roadmap.md` is the basic generation unit:

- It defines the current space, rules, enemies, resources, character nodes, long-line progress, and local short lines.
- `story-arcs` reads the current volume/stage and compresses it into a reusable `arc_context`.

At this stage, the reference novel does not provide plots to rename. It provides narrative patterns to learn from.

The system selects one reference story arc by default as the narrative sample, abstracts its plot function, conflict structure, information gap, emotion curve, payoff mechanism, key turn, and ending hook, then regenerates a new story-arc unit against the current stage.

## Chapter Humanization Post-processing

`novel write` adds a humanization refinement step. The rules are sourced from [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh).

Core principles include: removing filler phrases, breaking formulaic structures, varying sentence rhythm, trusting the reader, and removing quote-like slogans. For web-novel output, it also protects plot events, payoff beats, ending hooks, and mechanics numbers from being changed.

After AI-flavor removal, Zhuque AI detection can ensure that an average of **80%+** content is judged as suspected AI.

- The refined result is written to the final chapter directory: `file_system/chapters/vol_xx/`.
- The raw draft is backed up under `file_system/drafts/vol_xx/raw_chapters/`.

```bash
# Default: generate and humanize each new chapter.
novel write my-new-novel --volume 1 --start 1

# Disable humanization and keep the raw draft.
novel write my-new-novel --volume 1 --start 1 --no-humanize

# Humanize existing chapter files.
novel write my-new-novel --volume 1 --start 1 --max 3 --humanize-existing
```

## Optional: Mechanics Layer

If the new novel is a system novel, game novel, lord-management novel, infinite-flow novel, or needs stable tracking for realms, resources, skills, tasks, or relationship state, initialize the optional mechanics layer.

**Non-system novels can disable it; later workflow stages will ignore it automatically.**

```bash
# Automatically decide whether mechanics are needed: none / light_state / explicit_mechanics
novel mechanics-init my-new-novel

# Specify mechanics with a short direction
novel mechanics-init my-new-novel --direction "vampire devouring progression system with exp, blood purity, and skill tree"

# Read mechanics settings from a file. This has higher priority than --direction.
novel mechanics-init my-new-novel --file /path/to/mechanics.md

# Explicitly disable the mechanics layer
novel mechanics-init my-new-novel --none --force
```

Outputs:

- `file_system/mechanics/profile.json`: enabled state, mode, visible panel, precision
- `file_system/mechanics/design.md`: mechanics design notes
- `file_system/mechanics/rules.json`: computable events, display rules, constraints the model must not alter
- `file_system/mechanics/state.json`: initial state

Modes:

- `none`: Mechanics disabled. No system panel.
- `light_state`: No visible panel; internally tracks realms, resources, relationships, injuries, clue state, etc.
- `explicit_mechanics`: Visible system/panel/exp/tasks/points/skill tree. Chapter outlines output mechanics event drafts; exact values should be calculated by later program logic.

`story-arcs`, `chapter-outlines`, and `write` automatically read `file_system/mechanics/`. If mechanics are disabled, they receive a disabled notice and should not force a system panel into the novel.

## Optional: Target-world Knowledge Base

If the new novel needs to move into a target world that requires supporting materials, import and build the knowledge base before running `novel-outline`. Without a knowledge base, the workflow automatically uses only the reference novel + inspiration input.

```bash
# Import one file, multiple files, or a material directory.
novel world-import my-new-novel /path/to/main-source.txt
novel world-import my-new-novel /path/to/supplement-source.txt

# Structure the target-world knowledge base. --primary specifies the main source.
novel world-build my-new-novel --primary main-source.txt

# Then generate the new outline as usual; the knowledge base is loaded automatically.
novel novel-outline my-new-novel --direction "inspiration input"
```

## Existing Workspace Rebuilds

Use these commands only when an existing workspace needs to rebuild the knowledge base, overwrite old output, or regenerate a specific new asset.

```bash
# Rebuild the target-world knowledge base.
novel world-build my-new-novel --force --primary main-source.txt --chapter-batch-size 20

# Re-merge the final knowledge base from existing worlds/<source>/*.md files only.
novel world-build my-new-novel --merge-only --primary main-source.txt

# Overwrite core gameplay, long mainline, stage roadmap, and character arcs.
novel novel-outline my-new-novel --force --direction "inspiration input"

# Regenerate only core gameplay, long mainline, stage roadmap, and character arcs.
novel story-design my-new-novel --force

# Insert a new stage from inspiration.
novel stage-insert my-new-novel --direction "new stage idea" --after-stage 1

# Initialize or overwrite the mechanics layer.
novel mechanics-init my-new-novel --force --file /path/to/mechanics.md

# Overwrite story arcs for a volume/stage.
novel story-arcs my-new-novel --volume 1 --force

# Overwrite chapter outlines for a volume/stage.
novel chapter-outlines my-new-novel --volume 1 --force

# Humanize existing chapter files.
novel write my-new-novel --volume 1 --start 1 --max 3 --humanize-existing
```

## Notes

- Reference novels currently only support `.txt` format and must use UTF-8 encoding.

## Command Reference

| Command                                                               | Description                                      |
| --------------------------------------------------------------------- | ------------------------------------------------ |
| `novel config`                                                        | Initialize the global config file                |
| `novel list`                                                          | List all workspaces                              |
| `novel init <ws> --txt <path> [--batch-size N]`                       | Create a workspace and automatically deconstruct the reference novel + extract worldview |
| `novel world-import <ws> <paths...> [--force]`                        | Import target-genre material files or directories |
| `novel world-build <ws> [--force] [--merge-only] [--primary NAME] [--chapter-batch-size N] [--chunk-size N] [--max-workers N]` | Structure target-genre materials into a sectioned knowledge base |
| `novel novel-outline <ws> [--direction TEXT] [--direction-file PATH]` | Generate core gameplay, long mainline, stage roadmap, and character arcs |
| `novel story-design <ws> [--force] [--direction TEXT] [--direction-file PATH]` | Generate core gameplay, long mainline, stage roadmap, and character arcs |
| `novel stage-insert <ws> [--direction TEXT] [--direction-file PATH] [--after-stage N] [--before-stage N]` | Design a new stage from inspiration and insert it into the stage roadmap |
| `novel mechanics-init <ws> [--file PATH] [--direction TEXT] [--none] [--force]` | Initialize or disable the optional mechanics layer |
| `novel volume-outline <ws> [--volume N] [--force]`                    | Legacy flow: generate volume outline, per-volume worldview, and per-volume stage plan |
| `novel story-arcs <ws> [--volume N] [--force]`                        | Generate story arcs and narrative patterns for a volume/stage |
| `novel chapter-outlines <ws> [--volume N] [--force]`                  | Generate chapter outlines from story arcs |
| `novel write <ws> [--volume N] [--start N] [--max N] [--no-humanize] [--humanize-existing]` | Generate full text serially and humanize each new chapter by default |

### Parameters

- `--txt <path>`: Reference novel file path. Used only by `init`.
- `--batch-size N`: Chapters per reading window for story-arc detection. Default: 20. Used only by `init`.
- `--direction TEXT`: Creative direction, for example "change to a modern urban setting". In `novel-outline`, it affects the full-book plan; in `story-design`, it only tunes gameplay/stage/character assets.
- `--direction-file PATH`: Read creative direction from a file. Used by `novel-outline` and `story-design`.
- `--file PATH`: Mechanics settings file path. Used by `mechanics-init`.
- `--none`: Explicitly disable the mechanics layer. Used by `mechanics-init`.
- `--chapter-batch-size N`: Number of chapters per batch for chapter-like materials. Default: 20. Falls back to character chunks when chapters cannot be detected. Used only by `world-build`.
- `--chunk-size N`: Target-genre material chunk size in characters. Default: 12000. Used only by `world-build`.
- `--max-workers N`: Compatibility parameter. The current `world-build` uses all-section summarization and usually does not need this.
- `--primary NAME`: Specify the main source for `world-build`. Accepts file name, path, or material ID. If omitted, the largest file is used by default.
- `--merge-only`: Rebuild only `worlds/_final/*.md` and audits from existing `worlds/<source>/*.md`; does not re-extract cards.
- `--volume N`: Volume number. Default: 1. In the new flow, one volume corresponds to one stage in `stage_roadmap.md`.
- `--stage N`: Backward-compatible alias for `--volume`; it does not mean a stage inside a volume. Used by `story-arcs`, `chapter-outlines`, and `write`.
- `--after-stage N` / `--before-stage N`: Relative insertion position for a new stage. Used only by `stage-insert`.
- `--start N`: Starting chapter number. Default: 1. Used only by `write`.
- `--max N`: Maximum number of chapters to generate. Used only by `write`.
- `--no-humanize`: Disable automatic humanization after chapter generation. Used only by `write`.
- `--humanize-existing`: Humanize existing chapter files. By default, only newly generated chapters are humanized. Used only by `write`.
- `--force`: Force regeneration and overwrite existing content.

## About the Author

飞鸟 one the way — Explorer

<p align="left">
  <img src="docs/qrcode.png" width="400" alt="QR code">
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
