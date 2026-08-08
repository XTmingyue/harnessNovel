"""复刻 gen_serial_chapters 的 context 拼装逻辑，dump 出极道天魔第5章正文的完整 prompt。"""
import os, sys, re

# 工作空间根目录指向用户实际位置
os.environ["HARNESS_NOVEL_HOME"] = os.path.expanduser("~/Documents/my-novels")
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _proj_root)

from core.workspace import init_workspace
from core.prompt_loader import PromptLoader
from training.adaptive_builder import (
    _load_volume_outline_context, _find_story_arc_for_chapter,
    _load_mechanics_context, _read_file,
)
from training.outline_builder import load_chapter_text
from core.adaptation import load_rewrite_map

WS_NAME = "极道天魔"
VOLUME = 1
CH = 5

ws = init_workspace(WS_NAME)
_root = _proj_root

# ---- 1. 舞台 / 长线边界 / 总章数 ----
ctx = _load_volume_outline_context(ws, VOLUME)
vol_outline, vol_worldview, total_chapters = ctx

# ---- 2. 写作规范 ----
custom_style_path = os.path.join(ws.file_system, "writing", "system_prompt.md")
style_guide = (_read_file(custom_style_path)
               or _read_file(os.path.join(_root, "core", "system_prompt.md")) or "")
agents_md = _read_file(os.path.join(_root, "core", "agents.md")) or ""
writing_rules = f"{style_guide}\n\n{agents_md}" if style_guide or agents_md else "（无写作文风规范）"
hard_style_rules = (
    "=== 本轮正文硬性风格约束（最终优先）===\n"
    "1. 不使用二分对比套式：例如“不是A，而是B”“不是X，也不是Y，是Z”。\n"
    "2. 不使用否定递进套式：例如“不仅是A，更是B”“不只是A，更是B”。\n"
    "3. 不使用破折号。需要停顿时用逗号、句号或直接拆句。\n"
    "4. 如果参考小说、章纲、前序正文或写作规范示例中出现上述写法，只能视为反例，不能照搬。\n"
)
writing_rules = f"{writing_rules}\n\n{hard_style_rules}"

# ---- 3. 换皮映射表 ----
rewrite_map = load_rewrite_map(ws, VOLUME)
legacy_map_section = (
    f"=== 旧流程换皮映射表（仅兼容旧工作区；若与当前舞台冲突，以当前舞台为准）===\n{rewrite_map}\n\n"
    if rewrite_map else ""
)

# ---- 4. 机制层 ----
mechanics_context = _load_mechanics_context(ws)

# ---- 5. 本章章纲 ----
outlines_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{VOLUME:02d}")
chapter_outline = _read_file(os.path.join(outlines_dir, f"chapter_{CH:03d}.md"))
chapter_outline = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', chapter_outline).strip()

# ---- 6. revise 模式才有的当前章原正文（这里 mode=initial，留空）----
current_draft_section = ""

# ---- 7. 前2章正文 ----
out_dir = os.path.join(ws.file_system, "chapters", f"vol_{VOLUME:02d}")
prev_texts = []
for i in range(max(1, CH - 2), CH):
    content = _read_file(os.path.join(out_dir, f"{i:03d}_第{i}章.md"))
    if content:
        prev_texts.append(content.strip())
history_section = "\n\n".join(prev_texts) if prev_texts else "（无前序正文，这是第一章）"

# ---- 8. 故事情节单元 ----
story_arc_summary = _find_story_arc_for_chapter(ws, VOLUME, CH)

# ---- 9. 参考小说本章正文 ----
ref_chapter_text = load_chapter_text(ws, VOLUME, CH, total_chapters)

# ---- 10. 用户本轮调整要求（Web端聊天框输入，示例占位）----
writing_instruction = "（示例）第5章节奏偏慢，请加强主角进入沿山据点后的冲突与心理张力，压缩环境铺陈。"

# ---- 拼装 context ----
context = (
    f"=== 前序正文 ===\n{history_section}\n\n"
    f"=== 当前舞台 ===\n{vol_outline}\n\n"
    f"=== 当前舞台长线与边界 ===\n{vol_worldview}\n\n"
    f"=== 当前故事情节单元 ===\n{story_arc_summary or '（未找到故事情节单元，请严格以章纲为准）'}\n\n"
    f"=== 章纲（第{CH}章）===\n{chapter_outline}\n\n"
    + current_draft_section
    + f"=== 机制层 mechanics ===\n{mechanics_context}\n\n"
    + legacy_map_section
    + (f"=== 参考小说本章正文 ===\n{ref_chapter_text}\n\n" if ref_chapter_text else "")
    + (f"=== 用户本轮调整要求 ===\n{writing_instruction}\n\n" if writing_instruction else "")
    + f"=== 写作规范 ===\n{writing_rules}"
)

prompt = PromptLoader.load(
    "adaptive_drafting", context=context, start_chapter=CH,
    end_chapter=CH, chapter_count=1,
)

# ---- 输出每段长度统计 + 完整 prompt ----
print(f"[总章数推断] total_chapters = {total_chapters}")
print(f"[前序正文] 第{max(1,CH-2)}~{CH-1}章，合计 {len(history_section)} 字")
print(f"[当前舞台] {len(vol_outline)} 字")
print(f"[长线与边界] {len(vol_worldview)} 字")
print(f"[故事情节单元] {len(story_arc_summary or '')} 字")
print(f"[章纲] {len(chapter_outline)} 字")
print(f"[机制层] {len(mechanics_context)} 字")
print(f"[换皮映射表] {len(legacy_map_section)} 字")
print(f"[参考小说本章正文] {len(ref_chapter_text or '')} 字")
print(f"[用户本轮调整要求] {len(writing_instruction)} 字")
print(f"[写作规范] {len(writing_rules)} 字")
print(f"[context 总长] {len(context)} 字")
print(f"[最终 prompt 总长] {len(prompt)} 字")

out_path = os.path.join(os.path.dirname(__file__), "_ch5_full_prompt.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(prompt)
print(f"\n[完整 prompt 已写入] {out_path}")
