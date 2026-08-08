import sys
import os
import re
import argparse
import json
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.llm_provider import LLMProvider
from core.prompt_loader import PromptLoader
from core.config import ConfigLoader
from core.text_utils import normalize_text
from core.workspace import NovelWorkspace, init_workspace

# 独立行且长度合理的卷标题：如 "第一卷 斩落金锁听玄音"
VOLUME_HEADER_RE = re.compile(r'^[ \t　]*第[一二三四五六七八九十百千零0-9]+卷\s+\S+', re.MULTILINE)

# 章节标题：如 "1.第一章 标题"、"第一章 标题"、"第一章（1）标题"、"第一章 (2) 标题"
CHAPTER_HEADER_RE = re.compile(r'^[ \t　]*(\d+\.)?第[一二三四五六七八九十百千零\d]+[章回节](\s*[（(]\d+[）)])?\s*.+', re.MULTILINE)
CHAPTER_HEADER_FALLBACK = re.compile(r'(^[ \t　]*第[一二三四五六七八九十百千零0-9]+[章回节卷].{0,40}?)\n', re.MULTILINE)
VOLUME_TITLE_RE = re.compile(r'^[ \t　]*第[一二三四五六七八九十百千零0-9]+卷\b')

# 卷目录名格式：vol_01_卷名
VOL_DIR_RE = re.compile(r'^vol_(\d+)_(.+)$')
ARC_FILE_RE = re.compile(r'^arc_(\d+)_ch(\d+)_(\d+)\.md$')
ARC_HEADER_RE = re.compile(
    r'^【情节(?:\d+)?[：:]\s*第(\d+)-(\d+)章(?:[｜|：:](.*?))?】',
    re.MULTILINE,
)


def _read_and_clean(txt_path):
    with open(txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    skip_markers = {"[file content begin]", "[file content end]"}
    return "".join(line for line in lines if line.strip() not in skip_markers)


def _find_volumes(text):
    volumes = []
    for m in VOLUME_HEADER_RE.finditer(text):
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.start())
        if line_end == -1:
            line_end = len(text)
        line_text = text[line_start:line_end].strip()
        if len(line_text) > 40 or m.start() != line_start:
            continue
        volumes.append({"title": line_text, "start": m.start()})
    return volumes


def _find_chapters(text):
    matches = list(CHAPTER_HEADER_RE.finditer(text))
    if not matches:
        parts = CHAPTER_HEADER_FALLBACK.split(text)
        chapters = []
        for i in range(1, len(parts), 2):
            title = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            content = f"{title}\n{body}"
            # 跳过卷标题（含引言超过50字的卷标题仍需过滤）
            if VOLUME_TITLE_RE.match(title):
                continue
            # 跳过过短的条目
            if len(content) < 50:
                continue
            chapters.append({
                "title": title,
                "content": content,
                "pos": text.find(title),
                "volume_idx": -1,
            })
        return chapters

    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = normalize_text(text[start:end])
        first_newline = content.find('\n')
        title = content[:first_newline].strip() if first_newline != -1 else content[:50]
        # 跳过卷标题
        if VOLUME_TITLE_RE.match(title):
            continue
        # 跳过过短的条目
        if len(content) < 50:
            continue
        chapters.append({
            "title": title,
            "content": content,
            "pos": start,
            "volume_idx": -1,
        })
    return chapters


def _assign_volumes_by_position(chapters, volumes):
    if not volumes:
        for ch in chapters:
            ch["volume_idx"] = 0
        return

    vol_starts = sorted(v["start"] for v in volumes)
    for ch in chapters:
        pos = ch["pos"]
        assigned = 0
        for vi, vs in enumerate(vol_starts):
            if vs <= pos:
                assigned = vi
            else:
                break
        ch["volume_idx"] = assigned

    for ch in chapters:
        ch.pop("pos", None)


def split_chapters(txt_path, max_chapters=None):
    text = _read_and_clean(txt_path)
    volumes = _find_volumes(text)
    chapters = _find_chapters(text)
    _assign_volumes_by_position(chapters, volumes)
    if max_chapters is not None:
        if max_chapters < 1:
            raise ValueError("章节上限必须是正整数。")
        chapters = chapters[:max_chapters]
    return volumes, chapters


def group_chapters_by_volume(chapters, volumes):
    if not volumes:
        return [{"title": "全书", "chapters": chapters}]

    num_volumes = len(volumes)
    groups = []
    for vi in range(num_volumes):
        vol_chapters = [ch for ch in chapters if ch["volume_idx"] == vi]
        if vol_chapters:
            groups.append({"title": volumes[vi]["title"], "chapters": vol_chapters})

    unassigned = [ch for ch in chapters if ch["volume_idx"] < 0 or ch["volume_idx"] >= num_volumes]
    if unassigned:
        if groups:
            groups[-1]["chapters"].extend(unassigned)
        else:
            groups.append({"title": "全书", "chapters": unassigned})

    return groups


def split_chapters_to_files(ws, output_dir_name="chapters", max_chapters=None, refresh=False):
    """拆分参考小说为逐章文件，保存到 reference/{output_dir_name}/ 下。"""
    from core.chapter_utils import _fix_chapter_numbering, _int_to_cn, MAX_CHAPTERS_PER_VOLUME

    base_dir = os.path.join(ws.reference, output_dir_name)
    meta_path = os.path.join(base_dir, "_volumes.json")
    if os.path.exists(meta_path) and not refresh:
        print(f"章节拆分已存在，跳过。")
        return
    if refresh and os.path.isdir(base_dir):
        shutil.rmtree(base_dir)

    sample_path = ws.reference_sample
    if not os.path.exists(sample_path):
        print(f"错误：未找到参考小说文件 {sample_path}")
        return

    volumes, chapters = split_chapters(sample_path, max_chapters=max_chapters)
    groups = group_chapters_by_volume(chapters, volumes)
    scope = f"（仅处理前 {max_chapters} 章）" if max_chapters is not None else ""
    print(f"解析出 {len(volumes)} 卷，{len(chapters)} 章{scope}")

    _fix_chapter_numbering(groups)

    # 拆分超大卷
    split_groups = []
    for g in groups:
        vol_chapters = g["chapters"]
        if len(vol_chapters) <= MAX_CHAPTERS_PER_VOLUME:
            split_groups.append(g)
            continue
        num_parts = (len(vol_chapters) + MAX_CHAPTERS_PER_VOLUME - 1) // MAX_CHAPTERS_PER_VOLUME
        part_labels = ["（上）", "（中）", "（下）"] if num_parts <= 3 else \
                      [f"（第{_int_to_cn(i + 1)}部分）" for i in range(num_parts)]
        for pi in range(num_parts):
            start = pi * MAX_CHAPTERS_PER_VOLUME
            end = start + MAX_CHAPTERS_PER_VOLUME
            label = part_labels[pi] if pi < len(part_labels) else f"（第{pi + 1}部分）"
            split_groups.append({
                "title": g["title"] + label,
                "chapters": vol_chapters[start:end],
            })
        print(f"  {g['title']}（{len(vol_chapters)} 章）→ 拆分为 {num_parts} 个子卷")

    base_dir = os.path.join(ws.reference, output_dir_name)
    vol_meta = []
    saved = 0
    vol_offset = 0
    for vi, g in enumerate(split_groups):
        vol_chapters = g["chapters"]
        vol_dir_name = _vol_dir_name(vi, g["title"])
        vol_dir = os.path.join(base_dir, vol_dir_name)
        os.makedirs(vol_dir, exist_ok=True)

        vol_meta.append({"title": g["title"], "dir": vol_dir_name})

        for ci, ch in enumerate(vol_chapters):
            global_ch = ci + 1 + vol_offset
            safe_title = re.sub(r'[\\/:*?"<>|\s]', '_', ch["title"])[:50]
            fname = f"{global_ch:03d}_{safe_title}.md"
            fpath = os.path.join(vol_dir, fname)
            lines = ch["content"].split("\n", 1)
            corrected_content = ch["content"]
            if len(lines) >= 2 and lines[0].strip() != ch["title"]:
                corrected_content = f"{ch['title']}\n{lines[1]}" if len(lines) > 1 else ch["title"]
            _write_file(fpath, corrected_content)
            saved += 1

        vol_offset += len(vol_chapters)
        print(f"  {g['title']}: {len(vol_chapters)} 章 → {vol_dir_name}/")

    with open(os.path.join(base_dir, "_volumes.json"), "w", encoding="utf-8") as f:
        json.dump(vol_meta, f, ensure_ascii=False, indent=2)

    print(f"\n共保存 {saved} 个章节文件到 {base_dir}")


def load_chapter_text(ws, volume, chapter_num, total_chapters):
    """从持久化的章节文件中加载参考小说对应章节正文。

    使用卷内比例映射定位参考章节。找不到时返回空字符串。
    """
    base_dir = ws.reference_chapters
    meta_path = os.path.join(base_dir, "_volumes.json")

    if not os.path.exists(meta_path):
        return ""

    with open(meta_path, "r", encoding="utf-8") as f:
        vol_meta = json.load(f)

    vol_idx = volume - 1
    if vol_idx >= len(vol_meta):
        return ""

    vol_dir = os.path.join(base_dir, vol_meta[vol_idx]["dir"])
    if not os.path.isdir(vol_dir):
        return ""

    chapter_files = sorted(
        f for f in os.listdir(vol_dir) if f.endswith(".md") and not f.startswith("_")
    )
    ref_vol_total = len(chapter_files)

    if ref_vol_total == 0 or total_chapters <= 0:
        return ""

    ref_local_idx = int((chapter_num - 1) / total_chapters * ref_vol_total)
    ref_local_idx = min(ref_local_idx, ref_vol_total - 1)

    content = _read_file(os.path.join(vol_dir, chapter_files[ref_local_idx]))
    return content if content else ""


def _vol_dir_name(vol_idx, title):
    """生成卷目录名，如 vol_01_斩落金锁听玄音。"""
    safe = re.sub(r'[\\/:*?"<>|\s]', '_', title)[:30]
    return f"vol_{vol_idx + 1:02d}_{safe}"


def _batch_file_name(batch_start, batch_end):
    return f"batch_{batch_start + 1:03d}_{batch_end:03d}.md"


def _arc_dir(vol_dir):
    return os.path.join(vol_dir, "story_arcs")


def _arc_file_name(arc_idx, start_ch, end_ch):
    return f"arc_{arc_idx:03d}_ch{start_ch:03d}_{end_ch:03d}.md"


def _read_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    return content if content else None


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content + "\n")


def _format_chapters_for_arc_window(chapters, start_idx, end_idx):
    parts = []
    for i in range(start_idx, end_idx):
        ch_num = i + 1
        parts.append(f"=== 第{ch_num}章 ===\n{chapters[i]['content']}")
    return "\n\n".join(parts)


def _parse_story_arc_result(result):
    """解析 story_arc_extract 输出，返回 completed arcs 和 carryover。"""
    if not result:
        return [], ""

    carryover = ""
    carry_match = re.search(r'^# 未闭合情节续接区\s*$', result, re.MULTILINE)
    arc_part = result
    if carry_match:
        arc_part = result[:carry_match.start()]
        carryover = result[carry_match.end():].strip()
        if carryover in {"无", "无。", "（无）"}:
            carryover = ""

    matches = list(ARC_HEADER_RE.finditer(arc_part))
    arcs = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(arc_part)
        text = arc_part[start:end].strip()
        if not text:
            continue
        title = (match.group(3) or "").strip()
        arcs.append({
            "start_ch": int(match.group(1)),
            "end_ch": int(match.group(2)),
            "title": title,
            "content": text,
        })
    return arcs, carryover


def _story_arc_files(vol_dir):
    arc_path = _arc_dir(vol_dir)
    if not os.path.isdir(arc_path):
        return []
    items = []
    for fname in sorted(os.listdir(arc_path)):
        m = ARC_FILE_RE.match(fname)
        if not m:
            continue
        items.append({
            "idx": int(m.group(1)),
            "start_ch": int(m.group(2)),
            "end_ch": int(m.group(3)),
            "file": fname,
            "path": os.path.join(arc_path, fname),
        })
    return items


def _load_story_arc_texts(vol_dir):
    texts = []
    for item in _story_arc_files(vol_dir):
        content = _read_file(item["path"])
        if content:
            copied = dict(item)
            copied["content"] = content
            texts.append(copied)
    return texts


def _write_story_arc_index(vol_dir, arc_items):
    index_path = os.path.join(_arc_dir(vol_dir), "arcs_index.json")
    payload = []
    for item in arc_items:
        payload.append({
            "id": item["idx"],
            "start_ch": item["start_ch"],
            "end_ch": item["end_ch"],
            "file": item["file"],
        })
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _extract_story_arcs_for_volume(vol_idx, volume_title, chapters, llm, outlines_dir, batch_size=20):
    """按读取窗口提取自然故事情节单元，并从已有片段的末章继续。"""
    vol_dir = os.path.join(outlines_dir, _vol_dir_name(vol_idx, volume_title))
    arc_path = _arc_dir(vol_dir)
    existing_arcs = _load_story_arc_texts(vol_dir)
    total = len(chapters)
    existing_end = max((item["end_ch"] for item in existing_arcs), default=0)
    if existing_end >= total:
        print(f"    -> 已存在 {len(existing_arcs)} 个故事情节单元，覆盖至第 {existing_end} 章，跳过提取。")
        return existing_arcs

    if existing_arcs:
        print(f"    -> 已存在 {len(existing_arcs)} 个故事情节单元，续拆第 {existing_end + 1}-{total} 章...")
    carryover = ""
    arc_items = list(existing_arcs)
    arc_idx = max((item["idx"] for item in existing_arcs), default=0) + 1
    last_result = ""
    os.makedirs(arc_path, exist_ok=True)

    for start_idx in range(existing_end, total, batch_size):
        end_idx = min(start_idx + batch_size, total)
        start_ch = start_idx + 1
        end_ch = end_idx
        is_final_window = "是" if end_idx >= total else "否"
        print(f"    -> 识别故事情节（第 {start_ch}-{end_ch} 章，读取窗口 {batch_size} 章）...")

        prompt = PromptLoader.load(
            "story_arc_extract",
            previous_carryover=carryover or "无",
            start_chapter=start_ch,
            end_chapter=end_ch,
            is_final_window=is_final_window,
            chapters_text=_format_chapters_for_arc_window(chapters, start_idx, end_idx),
        )
        result = normalize_text(llm.generate(prompt))
        last_result = result
        arcs, carryover = _parse_story_arc_result(result)

        for arc in arcs:
            # 防止模型偶尔输出反向或越界范围；不强改文本，只约束文件名和索引。
            arc_start = max(start_ch, min(arc["start_ch"], arc["end_ch"]))
            arc_end = min(total, max(arc["start_ch"], arc["end_ch"]))
            if arc_end < arc_start:
                arc_end = arc_start
            fname = _arc_file_name(arc_idx, arc_start, arc_end)
            fpath = os.path.join(arc_path, fname)
            _write_file(fpath, arc["content"])
            arc_items.append({
                "idx": arc_idx,
                "start_ch": arc_start,
                "end_ch": arc_end,
                "file": fname,
                "path": fpath,
                "content": arc["content"],
            })
            arc_idx += 1

        _write_story_arc_index(vol_dir, arc_items)

    if len(arc_items) == len(existing_arcs) and last_result:
        fname = _arc_file_name(arc_idx, existing_end + 1, total)
        fpath = os.path.join(arc_path, fname)
        fallback = (
            f"【情节{arc_idx}：第{existing_end + 1}-{total}章｜格式兜底情节】\n"
            "情节功能：模型未按标准格式输出，以下保留原始分析结果供后续人工检查。\n\n"
            + last_result
        )
        _write_file(fpath, fallback)
        arc_items.append({
            "idx": arc_idx,
            "start_ch": existing_end + 1,
            "end_ch": total,
            "file": fname,
            "path": fpath,
            "content": fallback,
        })
        _write_story_arc_index(vol_dir, arc_items)
        carryover = ""

    carryover_path = os.path.join(arc_path, "_carryover.md")
    if carryover:
        _write_file(carryover_path, carryover)
        print(f"    -> 仍有未闭合情节续接区：{carryover_path}")
    elif os.path.exists(carryover_path):
        os.remove(carryover_path)

    print(f"    -> 故事情节单元已保存：{len(arc_items)} 个")
    return arc_items


def _generate_volume_outline_from_arcs(vol_dir, volume_title, total_chapters, llm,
                                       start_chapter=1, end_chapter=None, force=False):
    """读取故事情节单元，合并生成卷纲。"""
    vol_outline_path = os.path.join(vol_dir, "volume_outline.md")
    existing_outline = _read_file(vol_outline_path)
    if existing_outline and not force:
        print(f"    -> 卷纲已存在，跳过合并。")
        return existing_outline

    arc_items = _load_story_arc_texts(vol_dir)
    if not arc_items:
        return ""

    end_chapter = end_chapter or total_chapters
    arc_summaries = [item["content"] for item in arc_items]
    if len(arc_summaries) == 1:
        outline = arc_summaries[0]
    else:
        print(f"    -> 合并 {len(arc_summaries)} 个故事情节单元为卷纲...")
        all_subs = "\n\n---\n\n".join(arc_summaries)
        merge_prompt = PromptLoader.load(
            "volume_merge",
            volume_title=volume_title,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            total_chapters=total_chapters,
            total_batches=len(arc_summaries),
            batch_summaries=all_subs,
        )
        outline = normalize_text(llm.generate(merge_prompt))

    _write_file(vol_outline_path, outline)
    print(f"    -> 卷纲已保存：{vol_outline_path}")
    return outline


def extract_volume_outline(vol_idx, volume_title, chapters, llm, outlines_dir, batch_size=20, force=False):
    """提取单卷卷纲。先抽取故事情节单元，再合并为卷纲。"""
    vol_dir = os.path.join(outlines_dir, _vol_dir_name(vol_idx, volume_title))
    total = len(chapters)
    print(f"    [{volume_title}] 共 {total} 章")
    _extract_story_arcs_for_volume(vol_idx, volume_title, chapters, llm, outlines_dir, batch_size)
    return _generate_volume_outline_from_arcs(vol_dir, volume_title, total, llm, force=force)


def extract_novel_outline(volume_outlines, llm, outlines_dir, force=False):
    """汇总所有卷纲，生成完整大纲。"""
    novel_outline_path = os.path.join(outlines_dir, "novel_outline.md")
    existing = _read_file(novel_outline_path)
    if existing and not force:
        print(f"  -> 完整大纲已存在，跳过。")
        return existing

    print(f"  -> 汇总 {len(volume_outlines)} 卷卷纲，生成完整大纲...")
    all_outlines = "\n\n---\n\n".join(
        f"【{vo['title']}】\n{vo['outline']}"
        for vo in volume_outlines
    )
    prompt = PromptLoader.load("novel_extract", all_volume_outlines=all_outlines)
    novel_outline = normalize_text(llm.generate(prompt))
    _write_file(novel_outline_path, novel_outline)
    print(f"  -> 完整大纲已保存：{novel_outline_path}")
    return novel_outline


def _volume_dirs(outlines_dir):
    items = []
    if not os.path.isdir(outlines_dir):
        return items
    for name in sorted(os.listdir(outlines_dir)):
        m = VOL_DIR_RE.match(name)
        if not m:
            continue
        vol_path = os.path.join(outlines_dir, name)
        if os.path.isdir(vol_path):
            items.append((name, vol_path))
    return items


def _parse_virtual_volumes(llm_result):
    """解析 LLM 虚拟分卷输出为 [(vol_idx, title, start_ch, end_ch), ...]。"""
    volumes = []
    for line in llm_result.strip().split('\n'):
        line = line.strip()
        m = re.match(r'卷(\d+)：(.+?)\s*\|\s*第(\d+)-(\d+)章', line)
        if m:
            vol_idx = int(m.group(1))
            title = m.group(2).strip()
            start_ch = int(m.group(3))
            end_ch = int(m.group(4))
            volumes.append((vol_idx, title, start_ch, end_ch))
    return volumes


def _extract_segment_endpoints(batch_dir):
    """从故事情节单元或旧批次摘要中提取所有片段结束章节号。"""
    endpoints = set()
    for item in _story_arc_files(batch_dir):
        endpoints.add(item["end_ch"])
    for bf in sorted(os.listdir(batch_dir)):
        if not re.match(r'^batch_\d+_\d+\.md$', bf):
            continue
        content = _read_file(os.path.join(batch_dir, bf))
        if not content:
            continue
        for m in re.finditer(r'[【]?片段\d+[：:]\s*第(\d+)-(\d+)章', content):
            endpoints.add(int(m.group(2)))
    return sorted(endpoints)


def _snap_to_segments(virtual_volumes, segment_endpoints, total_chapters):
    """将虚拟卷的章节边界对齐到最近的片段端点，确保不拆碎片段。"""
    if not segment_endpoints:
        return virtual_volumes

    snapped = []
    for i, (vi, title, start_ch, end_ch) in enumerate(virtual_volumes):
        # 第一卷的起始章节保持 1
        s = 1 if i == 0 else snapped[-1][3] + 1
        # 结束章节对齐到最近的片段端点（不超过自身太多）
        candidates = [ep for ep in segment_endpoints if ep >= s]
        if candidates:
            # 找最近的端点，偏向不超过原值太多
            nearest = min(candidates, key=lambda x: abs(x - end_ch))
            e = nearest
        else:
            e = end_ch
        snapped.append((vi, title, s, e))
    return snapped


def _assign_batches_to_volumes(src_dir, virtual_volumes):
    """将批次文件分配给覆盖比例最大的虚拟卷，避免同一批次出现在多个卷中。

    Returns:
        dict: {vol_dir: [batch_file_name, ...]}
    """
    # 收集所有批次文件信息
    batches = []
    for bf in sorted(os.listdir(src_dir)):
        m = re.match(r'^batch_(\d+)_(\d+)\.md$', bf)
        if not m:
            continue
        batches.append((bf, int(m.group(1)), int(m.group(2))))

    assignment = {i: [] for i in range(len(virtual_volumes))}

    for bf, b_start, b_end in batches:
        best_vol = -1
        best_overlap = 0
        for i, (vi, title, start_ch, end_ch) in enumerate(virtual_volumes):
            overlap_start = max(b_start, start_ch)
            overlap_end = min(b_end, end_ch)
            overlap = max(0, overlap_end - overlap_start + 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_vol = i
        if best_vol >= 0:
            assignment[best_vol].append(bf)

    return assignment


def _assign_story_arcs_to_volumes(src_dir, virtual_volumes):
    """将 story arc 文件分配给覆盖比例最大的虚拟卷。"""
    arcs = _story_arc_files(src_dir)
    assignment = {i: [] for i in range(len(virtual_volumes))}

    for arc in arcs:
        best_vol = -1
        best_overlap = 0
        for i, (vi, title, start_ch, end_ch) in enumerate(virtual_volumes):
            overlap_start = max(arc["start_ch"], start_ch)
            overlap_end = min(arc["end_ch"], end_ch)
            overlap = max(0, overlap_end - overlap_start + 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_vol = i
        if best_vol >= 0:
            assignment[best_vol].append(arc)

    return assignment


def _copy_chapter_outlines_for_volume(src_dir, dst_dir, start_ch, end_ch):
    """从 src_dir/chapter_outlines/ 复制 [start_ch, end_ch] 范围的章纲到 dst_dir/chapter_outlines/。"""
    src_ch_dir = os.path.join(src_dir, "chapter_outlines")
    dst_ch_dir = os.path.join(dst_dir, "chapter_outlines")
    if not os.path.isdir(src_ch_dir):
        return
    os.makedirs(dst_ch_dir, exist_ok=True)
    for ch_num in range(start_ch, end_ch + 1):
        src_file = os.path.join(src_ch_dir, f"chapter_{ch_num:03d}.md")
        if os.path.exists(src_file):
            shutil.copy2(src_file, os.path.join(dst_ch_dir, f"chapter_{ch_num:03d}.md"))


def _generate_virtual_volume_outline(vol_dir, start_ch, end_ch, llm):
    """读取虚拟卷覆盖的情节单元或旧批次摘要，调用 LLM 生成卷纲。"""
    vol_outline_path = os.path.join(vol_dir, "volume_outline.md")
    existing = _read_file(vol_outline_path)
    if existing:
        return existing

    arc_items = _load_story_arc_texts(vol_dir)
    if arc_items:
        return _generate_volume_outline_from_arcs(
            vol_dir,
            "虚拟卷",
            end_ch - start_ch + 1,
            llm,
            start_chapter=start_ch,
            end_chapter=end_ch,
        )

    batch_summaries = []
    for bf in sorted(os.listdir(vol_dir)):
        m = re.match(r'^batch_\d+_\d+\.md$', bf)
        if not m:
            continue
        content = _read_file(os.path.join(vol_dir, bf))
        if content:
            batch_summaries.append(content)

    if not batch_summaries:
        return ""

    if len(batch_summaries) == 1:
        outline = batch_summaries[0]
    else:
        all_subs = "\n\n---\n\n".join(batch_summaries)
        total = end_ch - start_ch + 1
        merge_prompt = PromptLoader.load(
            "volume_merge",
            volume_title="虚拟卷",
            start_chapter=start_ch,
            end_chapter=end_ch,
            total_chapters=total,
            total_batches=len(batch_summaries),
            batch_summaries=all_subs,
        )
        outline = normalize_text(llm.generate(merge_prompt))

    _write_file(vol_outline_path, outline)
    return outline


def _extract_segment_ranges(batch_dir):
    """从故事情节单元或旧批次摘要中提取故事片段章节范围。"""
    segments = []
    for item in _story_arc_files(batch_dir):
        segments.append((item["start_ch"], item["end_ch"]))
    for bf in sorted(os.listdir(batch_dir)):
        if not re.match(r'^batch_\d+_\d+\.md$', bf):
            continue
        content = _read_file(os.path.join(batch_dir, bf))
        if not content:
            continue
        for m in re.finditer(r'[【]?片段\d+[：:]\s*第(\d+)-(\d+)章', content):
            segments.append((int(m.group(1)), int(m.group(2))))
    return segments


def _parse_batch_chapter_outlines(result):
    """解析多章章纲的 LLM 输出，返回 {chapter_num: outline_text}。"""
    outlines = {}
    parts = re.split(r'[【]?第(\d+)章\s*章纲[】]?', result)
    for i in range(1, len(parts) - 1, 2):
        ch_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            outlines[ch_num] = content
    return outlines


def _generate_chapter_outlines_batch(chapters_batch, llm):
    """批量生成多章章纲。chapters_batch: [(global_ch_num, chapter_dict), ...]。
    返回与输入顺序对应的 {global_ch_num: outline_text}，不依赖 LLM 返回的编号。
    """
    chapters_text_parts = []
    for ch_num, ch in chapters_batch:
        chapters_text_parts.append(f"=== 第{ch_num}章 ===\n{ch['content']}")
    chapters_text = "\n\n".join(chapters_text_parts)

    prompt = PromptLoader.load("chapter_outline_extract", chapters_text=chapters_text)
    result = normalize_text(llm.generate(prompt))
    parsed = _parse_batch_chapter_outlines(result)

    # 按输入顺序匹配：先尝试精确匹配编号，再按顺序兜底
    outlines = {}
    used_indices = set()
    # 第一轮：精确匹配
    for i, (ch_num, _) in enumerate(chapters_batch):
        if ch_num in parsed and i not in used_indices:
            outlines[ch_num] = parsed[ch_num]
            used_indices.add(i)
    # 第二轮：未匹配的输入按顺序取未使用的解析结果
    parsed_values = [v for k, v in sorted(parsed.items()) if k not in outlines]
    pi = 0
    for i, (ch_num, _) in enumerate(chapters_batch):
        if i not in used_indices and pi < len(parsed_values):
            outlines[ch_num] = parsed_values[pi]
            pi += 1

    return outlines


def _load_existing_volumes(outlines_dir, groups, chapters):
    """检查是否已有完整的情节单元/旧批次摘要和卷纲。如果有，返回 {volume_outlines, groups}。

    支持两种情况：
    1. 新版：vol_XX_<title>/story_arcs/ 下有 arc 文件和 volume_outline.md
    2. 旧版：vol_XX_<title>/ 下有 batch 文件和 volume_outline.md
    """
    if not os.path.isdir(outlines_dir):
        return None

    # 扫描已有的卷目录
    vol_dirs = _volume_dirs(outlines_dir)

    if not vol_dirs:
        return None

    # 检查每个卷目录是否有完整的批次文件和卷纲
    volume_outlines = []
    vol_groups = []
    all_complete = True

    for name, vol_path in vol_dirs:
        m = VOL_DIR_RE.match(name)
        vol_idx = int(m.group(1))
        title = m.group(2).replace('_', ' ')

        # 检查卷纲
        vol_outline = _read_file(os.path.join(vol_path, "volume_outline.md"))
        if not vol_outline:
            all_complete = False
            break

        # 检查新版故事情节单元或旧版批次文件
        arc_files = _story_arc_files(vol_path)
        batch_files = [f for f in os.listdir(vol_path) if re.match(r'^batch_\d+_\d+\.md$', f)]
        if not arc_files and not batch_files:
            all_complete = False
            break

        volume_outlines.append({"title": title, "outline": vol_outline})

        # 根据是否有 meta.json 判断是虚拟卷还是自然卷
        meta = None
        meta_path = os.path.join(vol_path, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

        if meta:
            # 虚拟卷：从 meta.json 获取章节范围
            start_ch = meta["start_ch"]
            end_ch = meta["end_ch"]
            vol_chapters = [chapters[i] for i in range(len(chapters))
                            if start_ch <= (i + 1) <= end_ch]
        else:
            # 自然卷：按卷索引分组
            vol_chapters = [ch for ch in chapters if ch.get("volume_idx", -1) == vol_idx - 1]

        vol_groups.append({"title": title, "chapters": vol_chapters})

    if not all_complete:
        return None

    return {"volume_outlines": volume_outlines, "groups": vol_groups}


def _run_legacy_outline_build(txt_path=None, output_dir=None, batch_size=20, skip_chapter_outlines=False,
                              max_chapters=None, resume=False):
    if txt_path is None:
        txt_path = os.path.join(DATA_DIR, "sample_novel.txt")
    if output_dir is None:
        output_dir = DATA_DIR

    if not os.path.exists(txt_path):
        print(f"错误：未找到小说文件 {txt_path}")
        return

    outlines_dir = os.path.join(output_dir, "outlines")

    print(f">>> 参考小说大纲梳理启动 <<<")
    print(f"读取文件：{txt_path}")
    print(f"输出目录：{outlines_dir}")

    # 1. 切分章节并识别卷
    volumes, chapters = split_chapters(txt_path, max_chapters=max_chapters)
    scope = f"仅处理前 {max_chapters} 章，" if max_chapters is not None else ""
    print(f"解析出 {len(volumes)} 卷，{len(chapters)} 章，{scope}每次读取 {batch_size} 章识别故事情节。")

    # 2. 按卷分组
    groups = group_chapters_by_volume(chapters, volumes)
    for g in groups:
        n = len(g['chapters'])
        windows = (n + batch_size - 1) // batch_size
        print(f"  {g['title']}：{n} 章 -> {windows} 个读取窗口")

    # 3. 检查是否已有完整的情节单元和卷纲（跳过阶段一）
    existing_volumes = None if resume else _load_existing_volumes(outlines_dir, groups, chapters)

    # 4. 初始化 LLM
    builder_config = ConfigLoader.get_data_builder_config()
    if not builder_config.get("api_key"):
        builder_config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not builder_config.get("api_key"):
        print("错误：未检测到 API Key。")
        return
    llm = LLMProvider(**builder_config)

    if existing_volumes:
        # 已有完整数据，跳过阶段一和虚拟分卷
        print(f"\n--- 阶段一：已跳过（检测到已有故事情节单元/旧批次摘要和卷纲） ---")
        volume_outlines = existing_volumes["volume_outlines"]
        groups = existing_volumes["groups"]
    else:
        # 4. 按卷提取故事情节单元和卷纲（增量保存）
        print(f"\n--- 阶段一：按卷提取故事情节单元和卷纲 ---")
        volume_outlines = []
        for vi, g in enumerate(groups):
            print(f"\n  处理：{g['title']}")
            outline = extract_volume_outline(
                vi, g["title"], g["chapters"], llm, outlines_dir, batch_size, force=resume,
            )
            volume_outlines.append({"title": g["title"], "outline": outline})

    # 汇总卷纲文件
    volume_outline_path = os.path.join(outlines_dir, "volume_outline.md")
    with open(volume_outline_path, "w", encoding="utf-8") as f:
        f.write("# 参考小说卷纲\n\n")
        for vo in volume_outlines:
            f.write(f"## {vo['title']}\n\n{vo['outline']}\n\n---\n\n")
    print(f"\n卷纲汇总已保存至：{volume_outline_path}")

    # 汇总生成完整大纲
    extract_novel_outline(volume_outlines, llm, outlines_dir, force=resume)


def run_outline_build(txt_path=None, output_dir=None, batch_size=20, skip_chapter_outlines=False,
                      max_chapters=None, resume=False, rebuild_reference=False):
    """执行可恢复的参考小说三阶段拆解。

    保持原有函数名和故事片段输出目录，确保后续舞台设计和叙事模式
    提取继续从 ``reference/outlines/vol_xx/story_arcs`` 读取数据。旧实现仅保留为
    内部兼容代码，不再作为默认入口。
    """
    if txt_path is None:
        txt_path = os.path.join(DATA_DIR, "sample_novel.txt")
    if output_dir is None:
        output_dir = DATA_DIR

    from training.reference_analyzer import run_reference_analysis

    return run_reference_analysis(
        txt_path=txt_path,
        output_dir=output_dir,
        batch_size=batch_size,
        max_chapters=max_chapters,
        resume=resume,
        rebuild=rebuild_reference,
    )

def resegment(outlines_dir):
    """基于已有故事情节单元或旧批次摘要重新执行虚拟分卷。

    两种情况：
    1. vol_01_全书/ 存在：直接从此目录重新分卷。
    2. 已有虚拟卷目录（含 meta.json）：将所有卷的情节单元/批次摘要汇总到 vol_01_全书/ 并去重，再重新分卷。
    """
    all_batch_dir = None
    for name in os.listdir(outlines_dir):
        if VOL_DIR_RE.match(name) and "全书" in name:
            all_batch_dir = os.path.join(outlines_dir, name)
            break

    if not all_batch_dir or not os.path.isdir(all_batch_dir):
        # 没有全书目录，查找虚拟卷目录并汇总情节单元/批次摘要
        vol_dirs = _volume_dirs(outlines_dir)

        if not vol_dirs:
            print("错误：未找到任何卷目录，无法执行重新分卷。")
            return

        print("  -> 未找到 vol_01_全书，从现有卷目录汇总故事情节单元...")
        all_batch_dir = os.path.join(outlines_dir, _vol_dir_name(0, "全书"))
        os.makedirs(all_batch_dir, exist_ok=True)
        os.makedirs(_arc_dir(all_batch_dir), exist_ok=True)

        # 收集所有 story arc 和旧 batch 文件并按文件名去重
        seen = set()
        seen_batches = set()
        for name, vol_path in vol_dirs:
            for arc in _story_arc_files(vol_path):
                if arc["file"] in seen:
                    continue
                shutil.copy2(arc["path"], os.path.join(_arc_dir(all_batch_dir), arc["file"]))
                seen.add(arc["file"])
            for bf in sorted(os.listdir(vol_path)):
                if re.match(r'^batch_\d+_\d+\.md$', bf) and bf not in seen_batches:
                    shutil.copy2(os.path.join(vol_path, bf), os.path.join(all_batch_dir, bf))
                    seen_batches.add(bf)

        # 删除旧的虚拟卷目录
        for name, vol_path in vol_dirs:
            shutil.rmtree(vol_path, ignore_errors=True)
            print(f"  -> 已删除旧卷目录：{name}")

        print(f"  -> 已汇总 {len(seen)} 个故事情节单元、{len(seen_batches)} 个旧批次摘要到 vol_01_全书/")

    # 以下统一处理：优先从 story arcs 读取，旧工作区回退 batch 摘要
    arc_items = _load_story_arc_texts(all_batch_dir)
    segment_summaries = []
    if arc_items:
        segment_summaries = [item["content"] for item in arc_items]
    else:
        for bf in sorted(os.listdir(all_batch_dir)):
            if re.match(r'^batch_\d+_\d+\.md$', bf):
                content = _read_file(os.path.join(all_batch_dir, bf))
                if content:
                    segment_summaries.append(content)

    if not segment_summaries:
        print("错误：未找到故事情节单元或批次摘要。")
        return

    batch_summaries = []
    for bf in sorted(os.listdir(all_batch_dir)):
        if re.match(r'^batch_\d+_\d+\.md$', bf):
            content = _read_file(os.path.join(all_batch_dir, bf))
            if content:
                batch_summaries.append(content)

    # 初始化 LLM
    builder_config = ConfigLoader.get_data_builder_config()
    if not builder_config.get("api_key"):
        builder_config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not builder_config.get("api_key"):
        print("错误：未检测到 API Key。")
        return
    llm = LLMProvider(**builder_config)

    # 推算总章数
    total_ch = 0
    if arc_items:
        total_ch = max(item["end_ch"] for item in arc_items)
    else:
        for bf in sorted(os.listdir(all_batch_dir)):
            m = re.match(r'^batch_\d+_(\d+)\.md$', bf)
            if m:
                total_ch = max(total_ch, int(m.group(1)))

    print(f">>> 虚拟分卷（重新分卷）<<<")
    print(f"  故事情节单元/摘要：{len(segment_summaries)} 个文件，约 {total_ch} 章")

    all_batches_text = "\n\n---\n\n".join(segment_summaries)
    print(f"  -> 调用 LLM 分析故事情节单元，识别卷边界...")
    seg_prompt = PromptLoader.load("virtual_volume_segment", batch_summaries=all_batches_text)
    seg_result = normalize_text(llm.generate(seg_prompt))

    virtual_volumes = _parse_virtual_volumes(seg_result)
    if not virtual_volumes:
        print("  警告：LLM 未输出有效分卷结果，保持原状。")
        return

    # 将边界对齐到故事片段端点
    segment_endpoints = _extract_segment_endpoints(all_batch_dir)
    virtual_volumes = _snap_to_segments(virtual_volumes, segment_endpoints, total_ch)

    # 检查每卷章节数是否 >= 60，不满足则合并到相邻卷
    virtual_volumes = _ensure_min_chapters(virtual_volumes, min_chapters=60)

    # 确保覆盖全部章节：首卷从1开始，末卷到 total_ch 结束
    virtual_volumes = _ensure_full_coverage(virtual_volumes, total_ch)

    print(f"  -> 识别出 {len(virtual_volumes)} 卷（已对齐片段边界）：")
    for vi, title, sc, ec in virtual_volumes:
        print(f"     卷{vi}：{title}（第{sc}-{ec}章，{ec - sc + 1}章）")
    covered = sum(ec - sc + 1 for _, _, sc, ec in virtual_volumes)
    print(f"  -> 覆盖：{covered}/{total_ch} 章")

    # 分配故事情节单元/旧批次文件
    arc_assignment = _assign_story_arcs_to_volumes(all_batch_dir, virtual_volumes)
    batch_assignment = _assign_batches_to_volumes(all_batch_dir, virtual_volumes)

    # 为每个虚拟卷创建目录、复制文件、生成卷纲
    new_volume_outlines = []
    for i, (vi, vol_title, start_ch, end_ch) in enumerate(virtual_volumes):
        vol_dir_name = _vol_dir_name(vi - 1, vol_title)
        vol_dir = os.path.join(outlines_dir, vol_dir_name)

        print(f"  -> 组织卷{vi}（{vol_title}，第{start_ch}-{end_ch}章）...")
        os.makedirs(vol_dir, exist_ok=True)
        os.makedirs(_arc_dir(vol_dir), exist_ok=True)
        for arc in arc_assignment.get(i, []):
            shutil.copy2(arc["path"], os.path.join(_arc_dir(vol_dir), arc["file"]))
        for bf in batch_assignment.get(i, []):
            shutil.copy2(os.path.join(all_batch_dir, bf), os.path.join(vol_dir, bf))

        meta = {"start_ch": start_ch, "end_ch": end_ch}
        with open(os.path.join(vol_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        outline = _generate_virtual_volume_outline(vol_dir, start_ch, end_ch, llm)
        new_volume_outlines.append({"title": vol_title, "outline": outline})
        print(f"     卷纲已生成")

    # 删除原始"全书"伪卷目录
    shutil.rmtree(all_batch_dir, ignore_errors=True)

    # 重写汇总卷纲文件
    volume_outline_path = os.path.join(outlines_dir, "volume_outline.md")
    with open(volume_outline_path, "w", encoding="utf-8") as f:
        f.write("# 参考小说卷纲\n\n")
        for vo in new_volume_outlines:
            f.write(f"## {vo['title']}\n\n{vo['outline']}\n\n---\n\n")

    # 重新生成大纲
    print(f"\n  -> 重新汇总生成大纲...")
    extract_novel_outline(new_volume_outlines, llm, outlines_dir, force=True)

    print(f"\n>>> 虚拟分卷完成 <<<")
    print(f"  卷纲汇总：{volume_outline_path}")

def _ensure_full_coverage(virtual_volumes, total_ch):
    """确保虚拟卷覆盖全部章节范围：首卷从1开始，末卷到 total_ch 结束，中间无间隙。"""
    if not virtual_volumes:
        return virtual_volumes

    result = []
    for i, (vi, title, start_ch, end_ch) in enumerate(virtual_volumes):
        s = 1 if i == 0 else (result[-1][3] + 1)
        # 最后一卷确保延伸到 total_ch
        if i == len(virtual_volumes) - 1:
            e = max(end_ch, total_ch)
        else:
            e = end_ch
        result.append((vi, title, s, e))
    return result


def _ensure_min_chapters(virtual_volumes, min_chapters=60):
    """合并章节数不足 min_chapters 的虚拟卷到相邻卷。"""
    if not virtual_volumes:
        return virtual_volumes

    result = list(virtual_volumes)
    changed = True
    while changed:
        changed = False
        new_result = []
        i = 0
        while i < len(result):
            vi, title, start_ch, end_ch = result[i]
            ch_count = end_ch - start_ch + 1
            if ch_count < min_chapters:
                # 尝试合并到下一卷
                if i + 1 < len(result):
                    nvi, ntitle, ns, ne = result[i + 1]
                    merged = (nvi, ntitle, start_ch, ne)
                    new_result.append(merged)
                    print(f"  -> 卷{vi}（{ch_count}章）不足{min_chapters}章，合并到卷{nvi}")
                    i += 2
                    changed = True
                # 尝试合并到前一卷
                elif new_result:
                    pvi, ptitle, ps, pe = new_result[-1]
                    new_result[-1] = (pvi, ptitle, ps, end_ch)
                    print(f"  -> 卷{vi}（{ch_count}章）不足{min_chapters}章，合并到卷{pvi}")
                    i += 1
                    changed = True
                else:
                    new_result.append(result[i])
                    i += 1
            else:
                new_result.append(result[i])
                i += 1
        result = new_result

    # 重新编号
    final = []
    for idx, (vi, title, start_ch, end_ch) in enumerate(result):
        final.append((idx + 1, title, start_ch, end_ch))
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从参考小说中梳理大纲和卷纲")
    parser.add_argument("--novel", type=str, required=True, help="工作区名称")
    parser.add_argument("--batch-size", type=int, default=20, help="每次读取章节数，用于识别故事情节单元（默认20）")
    parser.add_argument("--max-chapters", type=int, default=None, help="只拆解前 N 章（默认整本）")
    parser.add_argument("--txt-path", type=str, default=None, help="小说文件路径（默认使用工作区 reference/sample_novel.txt）")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录（默认使用工作区 reference/）")
    args = parser.parse_args()

    ws = init_workspace(args.novel)
    run_outline_build(
        txt_path=args.txt_path or ws.reference_sample,
        output_dir=args.output_dir or ws.reference,
        batch_size=args.batch_size,
        max_chapters=args.max_chapters,
    )
