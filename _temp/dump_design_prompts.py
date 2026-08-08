"""复刻四步骤的 prompt 拼装，用极道天魔真实数据生成四份完整 prompt。"""
import os, sys, json

os.environ["HARNESS_NOVEL_HOME"] = os.path.expanduser("~/Documents/my-novels")
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _proj_root)

from core.workspace import init_workspace
from core.prompt_loader import PromptLoader
from training.adaptive_builder import (
    _load_creative_direction, _load_reference_context, _reference_volume_structure_context,
    _load_world_knowledge_optional, _load_outline_rules, _design_structure_guidance,
    _rough_outline_path, _worldview_path, _read_file, _unused_reference_arcs,
    _arc_context_path, _reference_story_arc_average_chars, _plan_story_arcs,
    _load_volume_outline_context, _load_mechanics_context, _previous_system_panel,
)
from core.adaptation import load_rewrite_map

WS = "极道天魔"
VOLUME = 1
ws = init_workspace(WS)
OUT_DIR = os.path.join(_proj_root, "_temp", "design_prompts")
os.makedirs(OUT_DIR, exist_ok=True)


def save(name, prompt, stats):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"\n{'='*60}\n【{name}】 总长 {len(prompt)} 字\n{'='*60}")
    for k, v in stats.items():
        print(f"  {k:42} {v}")


# ============================================================
# 步骤1：全书设计 design_concept
# ============================================================
direction = _load_creative_direction(ws) or "（用户未提供具体方向）"
world_knowledge_c = _load_world_knowledge_optional(ws, "全书设计") or "（未提供目标世界知识库）"
ref_outline_c, ref_worldview_c = _load_reference_context(ws)
ref_vol_struct_c = _reference_volume_structure_context(ws)
outline_rules_c = _load_outline_rules(ws)
struct_c = _design_structure_guidance(ws)

p1 = PromptLoader.load(
    "design_concept",
    creative_direction=direction,
    reference_outline=ref_outline_c,
    reference_volume_structures=ref_vol_struct_c,
    reference_worldview=ref_worldview_c,
    world_knowledge=world_knowledge_c,
    outline_rules=outline_rules_c,
    **struct_c,
)
save("1_design_concept.txt", p1, {
    "creative_direction（来源 creative_direction.md）": f"{len(direction)} 字",
    "reference_outline（参考小说全书大纲）": f"{len(ref_outline_c)} 字",
    "reference_volume_structures（参考分卷结构）": f"{len(ref_vol_struct_c)} 字",
    "reference_worldview（参考世界观 reference_worldview.md）": f"{len(ref_worldview_c)} 字",
    "world_knowledge（目标世界知识库）": f"{len(world_knowledge_c)} 字",
    "outline_rules（OUTLINE_RULES.md）": f"{len(outline_rules_c)} 字",
    "reference_volume_count / stage_range / map_range": f"{struct_c['reference_volume_count']} / {struct_c['stage_range']} / {struct_c['map_range']}",
})

# ============================================================
# 步骤2：舞台设计 stage_design
# ============================================================
rough = _read_file(_rough_outline_path(ws))
worldview = _read_file(_worldview_path(ws))
candidate_arcs = _unused_reference_arcs(ws)
if candidate_arcs:
    ref_outline_s = "\n\n".join(
        f"【片段ID：{a['path']}｜第{a['start_ch']}-{a['end_ch']}章】\n{a['content']}" for a in candidate_arcs
    )
    ref_src_s = f"_unused_reference_arcs 共 {len(candidate_arcs)} 个未用片段"
else:
    ref_outline_s, _ = _load_reference_context(ws)
    ref_src_s = "无未用片段，回退 _load_reference_context（参考全书大纲）"
world_knowledge_s = _load_world_knowledge_optional(ws, "舞台设计") or "（未提供目标世界知识库）"

p2 = PromptLoader.load(
    "stage_design",
    creative_direction=direction,
    rough_outline=rough,
    worldview=worldview,
    reference_outline=ref_outline_s,
    world_knowledge=world_knowledge_s,
)
save("2_stage_design.txt", p2, {
    "creative_direction": f"{len(direction)} 字",
    "rough_outline（rough_outline.md，全书设计产出）": f"{len(rough)} 字",
    "worldview（worldview.md，全书设计产出）": f"{len(worldview)} 字",
    f"reference_outline（{ref_src_s}）": f"{len(ref_outline_s)} 字",
    "world_knowledge": f"{len(world_knowledge_s)} 字",
})

# ============================================================
# 步骤3：故事情节 novel_story_arc（以 arc_001 第1-5章为例）
# ============================================================
vol_outline, vol_worldview, total_chapters = _load_volume_outline_context(ws, VOLUME)
arc_plans = _plan_story_arcs(total_chapters)
arc1 = arc_plans[0]  # idx=1, start_ch=1, end_ch=5
arc_context = _read_file(_arc_context_path(ws, VOLUME)) or "（arc_context 缓存缺失，需先 _build_arc_context）"
previous_story_arc = "（无前序故事情节单元，这是本卷第一个情节单元）"
target_char_count = _reference_story_arc_average_chars(ws)

p3 = PromptLoader.load(
    "novel_story_arc",
    arc_context=arc_context,
    arc_index=arc1["idx"],
    start_chapter=arc1["start_ch"],
    end_chapter=arc1["end_ch"],
    previous_story_arc=previous_story_arc,
    target_char_count=target_char_count,
    target_field_chars=max(30, round(target_char_count / 10)),
)
save("3_novel_story_arc.txt", p3, {
    f"arc_context（adaptation/arc_contexts/vol_{VOLUME:02d}_context.md 缓存）": f"{len(arc_context)} 字",
    "arc_index / start / end": f"{arc1['idx']} / 第{arc1['start_ch']}-{arc1['end_ch']}章",
    "previous_story_arc（首个情节单元）": f"{len(previous_story_arc)} 字",
    "target_char_count（参考片段平均字数）": f"{target_char_count} 字",
    "target_field_chars": f"{max(30, round(target_char_count/10))} 字",
    "（注 total_chapters 由舞台推断）": f"{total_chapters} 章，共规划 {len(arc_plans)} 个情节单元",
})

# ============================================================
# 步骤4：逐章章纲 serial_chapter_outline（以第5章为例）
# ============================================================
CH = 5
rewrite_map = load_rewrite_map(ws, VOLUME)
mechanics_context = _load_mechanics_context(ws)
prev_panel = _previous_system_panel(ws, VOLUME, CH)
prev_panel_json = json.dumps(prev_panel, ensure_ascii=False, indent=2)
# 第5章属 arc_001
arc1_content = _read_file(os.path.join(
    ws.file_system, "story_arcs", f"vol_{VOLUME:02d}",
    f"arc_{arc1['idx']:03d}_ch{arc1['start_ch']:03d}_{arc1['end_ch']:03d}.md"))
# 前2章章纲
ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{VOLUME:02d}")
prev_outlines = []
for i in range(max(1, CH - 2), CH):
    content = _read_file(os.path.join(ch_out_dir, f"chapter_{i:03d}.md"))
    if content:
        import re as _re
        clean = _re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', content).strip()
        prev_outlines.append(f"【第{i}章 章纲】\n{clean}")
previous_text = "\n\n".join(prev_outlines) if prev_outlines else "（无前序章纲，这是本章节范围内第一章）"

p4 = PromptLoader.load(
    "serial_chapter_outline",
    volume_outline=vol_outline,
    volume_worldview=vol_worldview,
    rewrite_map=rewrite_map,
    forbidden_terms="章纲阶段不执行禁用词扫描。请以当前舞台、当前故事情节单元、角色线和长线主线为准，保持剧情合理性，不要主动引入与当前阶段不符的旧世界因果。",
    mechanics_context=mechanics_context,
    previous_system_panel=prev_panel_json,
    batch_summary=arc1_content,
    previous_chapter_outlines=previous_text,
    chapter_num=CH,
)
save("4_serial_chapter_outline.txt", p4, {
    "volume_outline（当前舞台 stage_roadmap 舞台1）": f"{len(vol_outline)} 字",
    "volume_worldview（长线+舞台边界）": f"{len(vol_worldview)} 字",
    "rewrite_map（load_rewrite_map）": f"{len(rewrite_map)} 字",
    "forbidden_terms（固定串）": "固定（章纲不扫禁用词）",
    "mechanics_context（system_panel.json）": f"{len(mechanics_context)} 字",
    "previous_system_panel（第4章面板 chapter_004.json）": f"{len(prev_panel_json)} 字",
    "batch_summary（arc_001 故事情节单元）": f"{len(arc1_content)} 字",
    "previous_chapter_outlines（前2章章纲）": f"{len(previous_text)} 字",
    "chapter_num": f"第 {CH} 章",
})

print(f"\n四份 prompt 已写入目录：{OUT_DIR}")
