import hashlib
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.prompt_loader import PromptLoader
from core.text_utils import normalize_text


SUPPORTED_TEXT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
}

CHAPTER_HEADER_RE = re.compile(
    r'^[ \t　]*(\d+\.)?第[一二三四五六七八九十百千零\d]+[章回节]'
    r'(\s*[（(]\d+[）)])?\s*.+',
    re.MULTILINE,
)
CHAPTER_HEADER_FALLBACK = re.compile(
    r'(^[ \t　]*第[一二三四五六七八九十百千零0-9]+[章回节].{0,60}?)\n',
    re.MULTILINE,
)
VOLUME_TITLE_RE = re.compile(r'^[ \t　]*第[一二三四五六七八九十百千零0-9]+卷\b')

WORLD_SECTIONS = [
    ("世界观", "资料的宇宙结构、时代背景、天地规则、历史阶段、核心矛盾和世界运行逻辑。"),
    ("力量体系", "修行层级、境界结构、力量来源、晋升方式、战力差异、限制条件。"),
    ("关键人物", "重要角色的身份、立场、关系、能力、剧情作用和主要经历。"),
    ("势力描述", "门派、教派、族群、王朝、联盟等势力的定位、关系、利益和冲突。"),
    ("故事主线", "主线事件、阶段性冲突、因果链、转折、关键战役或关键剧情推进。"),
    ("关键物品", "法宝、资源、道具、神器、丹药、功法载体等物品的属性、归属和剧情作用。"),
    ("技能体系", "法术、神通、功法、秘术、阵法、炼器炼丹等能力类型和使用规则。"),
]

SECTION_LOOKUP = dict(WORLD_SECTIONS)
WORLD_SECTION_NAMES = tuple(name for name, _ in WORLD_SECTIONS)
CANON_INDEX_SECTIONS = (
    "公共人物", "公共势力", "公共地点", "公共事件与历史线",
    "公共物品与法宝", "公共技能与法术", "力量体系关键词",
    "世界观规则关键词", "待补充类别",
)


# ── 路径工具 ──

def _world_root(ws):
    return os.path.join(ws.file_system, "world_knowledge")


def _imports_dir(ws):
    return os.path.join(_world_root(ws), "imports")


def _cards_dir(ws):
    return os.path.join(_world_root(ws), "cards")


def _partials_dir(ws):
    return os.path.join(_world_root(ws), "partials")


def _worlds_dir(ws):
    return os.path.join(_world_root(ws), "worlds")


def _audits_dir(ws):
    return os.path.join(_world_root(ws), "audits")


def _manifest_path(ws):
    return os.path.join(_world_root(ws), "manifest.json")


# ── 文件 IO ──

def _read_file(path):
    for encoding in ["utf-8", "utf-8-sig", "gb18030"]:
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n")


def _require_headings(content, headings, label):
    missing = [
        heading for heading in headings
        if not re.search(rf"(?m)^#\s*{re.escape(heading)}\s*$", content or "")
    ]
    if missing:
        raise RuntimeError(f"{label}缺少必要栏目：{'、'.join(missing)}。本轮结果未写入，请重试。")


def _has_meaningful_file(path):
    return bool(os.path.exists(path) and _read_file(path).strip())


def _run_prompt(llm, folder, prompt_vars, output_path, required_headings=None):
    """加载 prompt → llm.generate → normalize_text → _write_file，返回 normalize 后内容。

    纯生成+落盘。不含 print、不含 mtime 跳过、不读回文件。
    print 顺序 / skip 分支 / 返回值语义(path vs content)由调用点保留。
    """
    prompt = PromptLoader.load(folder, **prompt_vars)
    content = normalize_text(llm.generate(prompt))
    if not content:
        raise RuntimeError(f"{folder} 未返回有效内容，本轮结果未写入，请检查模型配置或重试。")
    if required_headings:
        _require_headings(content, required_headings, folder)
    _write_file(output_path, content)
    return content


# ── Manifest 与资料命名 ──

def _load_manifest(ws):
    path = _manifest_path(ws)
    if not os.path.exists(path):
        return {"version": 1, "sources": [], "enabled": True}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "sources": [], "enabled": True}
        data.setdefault("version", 1)
        data.setdefault("sources", [])
        # enabled 默认 True（导入资料后即视为启用）；老 manifest 没有该字段时补上。
        if "enabled" not in data:
            data["enabled"] = True
        return data
    except Exception:
        return {"version": 1, "sources": [], "enabled": True}


def _save_manifest(ws, manifest):
    _write_file(_manifest_path(ws), json.dumps(manifest, ensure_ascii=False, indent=2))


def _iter_source_files(paths):
    for raw_path in paths:
        path = os.path.abspath(os.path.expanduser(raw_path))
        if not os.path.exists(path):
            yield path, False
            continue
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in sorted(files):
                    file_path = os.path.join(root, name)
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in SUPPORTED_TEXT_EXTS:
                        yield file_path, True
        else:
            ext = os.path.splitext(path)[1].lower()
            yield path, ext in SUPPORTED_TEXT_EXTS


def _source_id(path):
    return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]


def _safe_name(name):
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name, flags=re.UNICODE).strip("_")
    return name or "source.txt"


def _source_name(record):
    file_name = record.get("file_name") or "source"
    stem = os.path.splitext(file_name)[0] or file_name
    return _safe_name(stem)


def _section_file_name(section_name):
    return f"{_safe_name(section_name)}.md"


def _source_world_dir(ws, record):
    return os.path.join(_worlds_dir(ws), _source_name(record))


def _source_section_path(ws, record, section_name):
    return os.path.join(_source_world_dir(ws, record), _section_file_name(section_name))


def _source_partials_dir(ws, record):
    return os.path.join(_partials_dir(ws), _source_name(record))


def _final_partials_dir(ws):
    return os.path.join(_partials_dir(ws), "_final")


def _final_world_dir(ws):
    return os.path.join(_worlds_dir(ws), "_final")


def _final_section_path(ws, section_name):
    return os.path.join(_final_world_dir(ws), _section_file_name(section_name))


def _canon_index_path(ws):
    return os.path.join(_world_root(ws), "canon_index.md")


# ── 公共入口：导入资料 ──

def import_world_sources(ws, paths, force=False):
    """Copy one or more target-world source files into the workspace."""
    os.makedirs(_imports_dir(ws), exist_ok=True)
    manifest = _load_manifest(ws)
    by_source = {item.get("source_path"): item for item in manifest.get("sources", [])}

    imported = []
    skipped = []
    missing = []
    unsupported = []

    for source_path, supported in _iter_source_files(paths):
        if not os.path.exists(source_path):
            missing.append(source_path)
            continue
        if not supported:
            unsupported.append(source_path)
            continue

        abs_path = os.path.abspath(source_path)
        existing = by_source.get(abs_path)
        if existing and not force and os.path.exists(existing.get("imported_path", "")):
            skipped.append(abs_path)
            continue

        sid = _source_id(abs_path)
        dest_name = f"{sid}_{_safe_name(os.path.basename(abs_path))}"
        dest_path = os.path.join(_imports_dir(ws), dest_name)
        shutil.copy2(abs_path, dest_path)

        record = {
            "id": sid,
            "source_path": abs_path,
            "imported_path": dest_path,
            "file_name": os.path.basename(abs_path),
            "size": os.path.getsize(dest_path),
            "mtime": os.path.getmtime(dest_path),
            "imported_at": datetime.now().isoformat(timespec="seconds"),
        }

        if existing:
            manifest["sources"] = [
                record if item.get("source_path") == abs_path else item
                for item in manifest["sources"]
            ]
        else:
            manifest["sources"].append(record)
        by_source[abs_path] = record
        imported.append(abs_path)

    _save_manifest(ws, manifest)
    return {
        "imported": imported,
        "skipped": skipped,
        "missing": missing,
        "unsupported": unsupported,
        "manifest": _manifest_path(ws),
    }


# ── 文本切分 ──

def _split_text(text, chunk_size):
    text = text.strip()
    if not text:
        return []

    paragraphs = re.split(r"\n{2,}", text)
    chunks = []
    current = []
    current_len = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            for i in range(0, len(paragraph), chunk_size):
                chunks.append(paragraph[i:i + chunk_size])
            continue
        projected = current_len + len(paragraph) + 2
        if current and projected > chunk_size:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len = projected

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _find_chapters(text):
    matches = list(CHAPTER_HEADER_RE.finditer(text))
    if not matches:
        parts = CHAPTER_HEADER_FALLBACK.split(text)
        chapters = []
        for i in range(1, len(parts), 2):
            title = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            content = normalize_text(f"{title}\n{body}")
            if VOLUME_TITLE_RE.match(title) or len(content) < 80:
                continue
            chapters.append({"title": title, "content": content})
        return chapters

    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = normalize_text(text[start:end])
        first_newline = content.find("\n")
        title = content[:first_newline].strip() if first_newline != -1 else content[:60]
        if VOLUME_TITLE_RE.match(title) or len(content) < 80:
            continue
        chapters.append({"title": title, "content": content})
    return chapters


def _split_source_slices(text, chapter_batch_size, fallback_chunk_size):
    chapters = _find_chapters(text)
    if len(chapters) >= 2:
        slices = []
        batch = []
        batch_chars = 0
        batch_start = 1

        def flush_batch(end_index):
            nonlocal batch, batch_chars
            if not batch:
                return
            slices.append({
                "label": f"第{batch_start}-{end_index}章",
                "kind": "chapter_batch",
                "text": "\n\n".join(ch["content"] for ch in batch),
                "chapter_count": len(batch),
            })
            batch = []
            batch_chars = 0

        for chapter_index, chapter in enumerate(chapters, start=1):
            chapter_chars = len(chapter["content"])
            over_count = len(batch) >= chapter_batch_size
            over_chars = bool(batch) and batch_chars + chapter_chars + 2 > fallback_chunk_size
            if over_count or over_chars:
                flush_batch(chapter_index - 1)
                batch_start = chapter_index
            batch.append(chapter)
            batch_chars += chapter_chars + (2 if len(batch) > 1 else 0)
        flush_batch(len(chapters))
        return slices

    chunks = _split_text(text, fallback_chunk_size)
    return [
        {
            "label": f"字符分片{i + 1}",
            "kind": "text_chunk",
            "text": chunk,
            "chapter_count": 0,
        }
        for i, chunk in enumerate(chunks)
    ]


def _format_knowledge_items(items):
    return "\n\n---\n\n".join(
        f"【{title}】\n{text.strip()}"
        for title, text in items
        if text and text.strip()
    )


# ── 资料记录与角色 ──

def _source_records(ws):
    manifest = _load_manifest(ws)
    records = []
    for item in manifest.get("sources", []):
        imported_path = item.get("imported_path")
        if imported_path and os.path.exists(imported_path):
            records.append(item)
    if records:
        return records

    imports_dir = _imports_dir(ws)
    if not os.path.isdir(imports_dir):
        return []
    fallback = []
    for name in sorted(os.listdir(imports_dir)):
        path = os.path.join(imports_dir, name)
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in SUPPORTED_TEXT_EXTS:
            fallback.append({
                "id": _source_id(path),
                "source_path": path,
                "imported_path": path,
                "file_name": name,
                "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path),
            })
    return fallback


def _normalize_source_match(value):
    return os.path.abspath(os.path.expanduser(value)).lower() if value else ""


def _record_matches_selector(record, selector):
    if not selector:
        return False

    selector_raw = selector.strip()
    selector_lower = selector_raw.lower()
    selector_abs = _normalize_source_match(selector_raw)
    candidates = [
        record.get("id", ""),
        record.get("file_name", ""),
        os.path.splitext(record.get("file_name", ""))[0],
        record.get("source_path", ""),
        record.get("imported_path", ""),
        os.path.basename(record.get("source_path", "")),
        os.path.basename(record.get("imported_path", "")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_lower = str(candidate).lower()
        if selector_lower == candidate_lower:
            return True
        if selector_abs and selector_abs == _normalize_source_match(str(candidate)):
            return True
    return False


def _select_primary_record(records, primary_source=None):
    if primary_source:
        matches = [record for record in records if _record_matches_selector(record, primary_source)]
        if len(matches) == 1:
            return matches[0], "用户指定"
        if len(matches) > 1:
            print(
                "  警告：--primary 匹配到多个资料，将使用第一个："
                + "、".join(record.get("file_name", "") for record in matches)
            )
            return matches[0], "用户指定"
        print(f"  警告：未找到 --primary 指定的资料：{primary_source}")
        print(
            "  可选资料："
            + "、".join(record.get("file_name", record.get("id", "")) for record in records)
        )
        print("  将回退为最大文件作为主资料。")
    return max(records, key=lambda item: item.get("size", 0)), "最大文件"


def _assign_source_roles(records, primary_source=None):
    if not records:
        return []
    primary, primary_reason = _select_primary_record(records, primary_source=primary_source)
    primary_id = primary.get("id")
    assigned = []
    for item in records:
        copied = dict(item)
        copied["role"] = "primary" if item.get("id") == primary_id else "supplement"
        copied["role_label"] = "主资料" if copied["role"] == "primary" else "补充资料"
        copied["role_reason"] = primary_reason if copied["role"] == "primary" else ""
        assigned.append(copied)
    return sorted(
        assigned,
        key=lambda item: (0 if item["role"] == "primary" else 1, item.get("file_name", "")),
    )


# ── 栏目文档处理 ──

def _render_section_document(section_name, content):
    content = (content or "").strip()
    if not content:
        return f"# {section_name}\n\n无"
    if content.startswith("#"):
        return content
    return f"# {section_name}\n\n{content}"


def _split_sections_from_document(content):
    sections = {}
    content = normalize_text(content or "")
    for idx, (section_name, _) in enumerate(WORLD_SECTIONS):
        pattern = re.compile(rf"(?m)^#\s*{re.escape(section_name)}\s*$")
        match = pattern.search(content)
        if not match:
            sections[section_name] = f"# {section_name}\n\n无"
            continue

        next_start = len(content)
        for next_section, _ in WORLD_SECTIONS[idx + 1:]:
            next_match = re.search(rf"(?m)^#\s*{re.escape(next_section)}\s*$", content[match.end():])
            if next_match:
                next_start = match.end() + next_match.start()
                break
        block = content[match.start():next_start].strip()
        sections[section_name] = _render_section_document(section_name, block)
    return sections


def _compact_world_document(content, max_chars=45000):
    """按栏目均衡压缩阶段摘要，避免串行汇总时单次上下文持续膨胀。"""
    content = normalize_text(content or "")
    if len(content) <= max_chars:
        return content
    sections = _split_sections_from_document(content)
    section_budget = max(1200, max_chars // len(WORLD_SECTIONS) - 80)
    parts = []
    for section_name, _ in WORLD_SECTIONS:
        block = sections.get(section_name, f"# {section_name}\n\n无")
        if len(block) > section_budget:
            block = block[:section_budget].rstrip() + "\n\n（本栏目阶段摘要过长，已均衡截断。）"
        parts.append(block)
    return "\n\n---\n\n".join(parts)


def _final_section_paths(ws):
    return [
        (section_name, _final_section_path(ws, section_name))
        for section_name, _ in WORLD_SECTIONS
        if _has_meaningful_file(_final_section_path(ws, section_name))
    ]


def _aggregate_sections(section_paths, max_chars=None):
    parts = []
    section_budget = None
    if max_chars and section_paths:
        section_budget = max(1200, max_chars // len(section_paths) - 80)

    for section_name, path in section_paths:
        content = _read_file(path).strip() if os.path.exists(path) else ""
        if section_budget and len(content) > section_budget:
            content = (
                content[:section_budget]
                + f"\n\n（{section_name}内容过长，以上为按栏目截断后的前置摘要。）"
            )
        parts.append(_render_section_document(section_name, content))
    result = "\n\n---\n\n".join(parts)
    if max_chars and len(result) > max_chars:
        return result[:max_chars] + "\n\n（目标世界知识库内容过长，以上为截断后的分栏摘要。）"
    return result


def _source_slices(record, chunk_size, chapter_batch_size):
    source_text = _read_file(record["imported_path"]).strip()
    return _split_source_slices(
        source_text,
        chapter_batch_size=chapter_batch_size,
        fallback_chunk_size=chunk_size,
    )


# ── Cards 与基准索引 ──

def _resolved_workers(max_workers, task_count):
    try:
        requested = int(max_workers or 4)
    except (TypeError, ValueError):
        requested = 4
    return max(1, min(requested, max(1, task_count)))


def _build_record_cards(ws, record, slices, llm, force=False, canon_index="",
                        dependency_mtime=None, max_workers=4):
    source_mtime = record.get("mtime") or os.path.getmtime(record["imported_path"])
    source_card_paths = []
    pending = []
    for idx, source_slice in enumerate(slices, start=1):
        card_path = os.path.join(_cards_dir(ws), f"{record['id']}_part_{idx:03d}.md")
        source_card_paths.append(card_path)
        card_is_fresh = (
            _has_meaningful_file(card_path)
            and os.path.getmtime(card_path) >= source_mtime
            and (not dependency_mtime or os.path.getmtime(card_path) >= dependency_mtime)
        )
        if card_is_fresh and not force:
            continue

        pending.append((idx, source_slice, card_path))

    if not pending:
        return source_card_paths

    workers = _resolved_workers(max_workers, len(pending))
    print(
        f"  并行结构化{record['role_label']}《{record['file_name']}》："
        f"共 {len(pending)} 个章节批次，并发 {workers}"
    )

    def extract_card(job):
        idx, source_slice, card_path = job
        print(
            f"  开始结构化{record['role_label']}：{record['file_name']} "
            f"{source_slice['label']}（{idx}/{len(slices)}）"
        )
        _run_prompt(
            llm,
            "world_knowledge_extract",
            dict(
                source_name=record["file_name"],
                source_role=record["role_label"],
                canon_index=canon_index or "（无。当前资料为主资料，或尚未生成主资料基准索引。）",
                slice_label=source_slice["label"],
                slice_kind=source_slice["kind"],
                chunk_index=idx,
                chunk_count=len(slices),
                source_text=source_slice["text"],
            ),
            card_path,
            required_headings=WORLD_SECTION_NAMES,
        )
        return idx, source_slice["label"]

    completed = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="world-card") as executor:
        futures = [executor.submit(extract_card, job) for job in pending]
        try:
            for future in as_completed(futures):
                idx, label = future.result()
                completed += 1
                print(f"  完成资料卡 {completed}/{len(pending)}：{label}（原批次 {idx}）")
        except Exception:
            for future in futures:
                future.cancel()
            raise
    return source_card_paths


def _build_canon_index(ws, primary_record, primary_card_paths, llm, force=False):
    existing_cards = [path for path in primary_card_paths if _has_meaningful_file(path)]
    if not existing_cards:
        return ""

    output_path = _canon_index_path(ws)
    newest_card_mtime = max(os.path.getmtime(path) for path in existing_cards)
    if (
        os.path.exists(output_path)
        and not force
        and os.path.getmtime(output_path) >= newest_card_mtime
    ):
        return _read_file(output_path).strip()

    print(f"  串行生成主资料基准索引：{primary_record['file_name']}")
    partial_dir = os.path.join(_partials_dir(ws), "_canon_index")
    os.makedirs(partial_dir, exist_ok=True)
    previous_index = "（无，这是第一批主资料卡片。）"
    total_steps = (len(existing_cards) + 1) // 2
    canon_index = ""
    for step_index, start in enumerate(range(0, len(existing_cards), 2), start=1):
        selected_paths = existing_cards[start:start + 2]
        card_items = [
            (os.path.basename(path), _read_file(path))
            for path in selected_paths
        ]
        print(f"  汇总主资料基准索引 {step_index}/{total_steps}")
        canon_index = _run_prompt(
            llm,
            "world_canon_index",
            dict(
                source_name=primary_record["file_name"],
                previous_index=previous_index,
                knowledge_cards=_format_knowledge_items(card_items),
            ),
            os.path.join(partial_dir, f"partial_{step_index:03d}.md"),
            required_headings=CANON_INDEX_SECTIONS,
        )
        previous_index = canon_index
    _write_file(output_path, canon_index)
    print(f"  -> 主资料基准索引已保存：{output_path}")
    return canon_index


# ── 单资料全栏目汇总 ──

def _write_sections_to_source(ws, record, section_documents):
    section_paths = {}
    for section_name, _ in WORLD_SECTIONS:
        output_path = _source_section_path(ws, record, section_name)
        _write_file(output_path, section_documents.get(section_name, f"# {section_name}\n\n无"))
        section_paths[section_name] = output_path
    return section_paths


def _write_sections_to_final(ws, section_documents):
    section_paths = {}
    for section_name, _ in WORLD_SECTIONS:
        output_path = _final_section_path(ws, section_name)
        _write_file(output_path, section_documents.get(section_name, f"# {section_name}\n\n无"))
        section_paths[section_name] = output_path
    return section_paths


def _build_source_all_sections(ws, record, card_paths, llm, force=False):
    existing_cards = [path for path in card_paths if _has_meaningful_file(path)]
    if not existing_cards:
        return None

    source_dir = _source_world_dir(ws, record)
    source_partials_dir = os.path.join(_source_partials_dir(ws, record), "_all_sections")
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(source_partials_dir, exist_ok=True)

    newest_card_mtime = max(os.path.getmtime(path) for path in existing_cards)
    section_paths = {
        section_name: _source_section_path(ws, record, section_name)
        for section_name, _ in WORLD_SECTIONS
    }
    if (
        all(_has_meaningful_file(path) for path in section_paths.values())
        and not force
        and min(os.path.getmtime(path) for path in section_paths.values()) >= newest_card_mtime
    ):
        return section_paths

    previous_summary = "（无，这是该资料的第一轮全栏目汇总。）"
    total_steps = (len(existing_cards) + 1) // 2
    current_summary = ""

    for step_index, start in enumerate(range(0, len(existing_cards), 2), start=1):
        selected_paths = existing_cards[start:start + 2]
        card_items = [
            (os.path.basename(path), _read_file(path))
            for path in selected_paths
        ]
        print(
            f"  汇总{record['role_label']}《{record['file_name']}》全栏目 "
            f"{step_index}/{total_steps}"
        )
        current_summary = _run_prompt(
            llm,
            "world_knowledge_merge_all_sections",
            dict(
                merge_task=(
                    f"资料级全栏目串行汇总：为{record['role_label']}《{record['file_name']}》"
                    "构建完整的7栏目资料知识库。本轮只读取2个新的资料卡片和上一轮阶段摘要；"
                    "请在同一资料内部去重、补充和纠错，不要与其他资料做主次裁决。"
                ),
                previous_summary=_compact_world_document(previous_summary),
                knowledge_cards=_format_knowledge_items(card_items),
            ),
            os.path.join(source_partials_dir, f"partial_{step_index:03d}.md"),
            required_headings=WORLD_SECTION_NAMES,
        )
        previous_summary = current_summary

    return _write_sections_to_source(ws, record, _split_sections_from_document(current_summary))


def _build_single_source_sections(ws, record, card_paths, llm, force=False, max_workers=None):
    existing_cards = [path for path in card_paths if _has_meaningful_file(path)]
    if not existing_cards:
        return None

    section_paths = _build_source_all_sections(ws, record, existing_cards, llm, force=force) or {}

    index_path = os.path.join(_source_world_dir(ws, record), "README.md")
    index_lines = [
        f"# {record['file_name']} 资料知识库",
        "",
        f"- 资料角色：{record.get('role_label', '资料')}",
        f"- 资料路径：{record.get('source_path') or record.get('imported_path')}",
        "",
        "## 栏目",
    ]
    for section_name, _ in WORLD_SECTIONS:
        if section_name in section_paths:
            index_lines.append(f"- [{section_name}]({_section_file_name(section_name)})")
    _write_file(index_path, "\n".join(index_lines))
    return {
        "record": record,
        "sections": section_paths,
        "index": index_path,
    }


def _load_existing_source_sections(ws, records):
    source_items = []
    for record in records:
        section_paths = {
            section_name: _source_section_path(ws, record, section_name)
            for section_name, _ in WORLD_SECTIONS
            if _has_meaningful_file(_source_section_path(ws, record, section_name))
        }
        if not section_paths:
            print(f"  警告：未找到资料分栏知识库，跳过：{record['file_name']}")
            continue
        source_items.append({
            "record": record,
            "sections": section_paths,
            "index": os.path.join(_source_world_dir(ws, record), "README.md"),
        })
    return source_items


# ── 最终融合与审计 ──

def _integrate_final_sections(ws, source_items, llm, force=False, max_workers=None):
    if not source_items:
        return None

    primary_item = next(
        (item for item in source_items if item["record"].get("role") == "primary"),
        source_items[0],
    )
    supplement_items = [
        item for item in source_items
        if item["record"].get("id") != primary_item["record"].get("id")
    ]

    source_section_paths = [
        path
        for item in source_items
        for path in item.get("sections", {}).values()
        if _has_meaningful_file(path)
    ]
    if not source_section_paths:
        print("错误：未能生成最终分栏世界知识库。")
        return None

    final_paths = {
        section_name: _final_section_path(ws, section_name)
        for section_name, _ in WORLD_SECTIONS
    }
    final_all_partials_dir = os.path.join(_final_partials_dir(ws), "_all_sections")
    has_final_trace = (
        not supplement_items
        or (
            os.path.isdir(final_all_partials_dir)
            and any(name.startswith("integrated_") for name in os.listdir(final_all_partials_dir))
        )
    )
    newest_source_mtime = max(os.path.getmtime(path) for path in source_section_paths)
    if (
        all(_has_meaningful_file(path) for path in final_paths.values())
        and not force
        and min(os.path.getmtime(path) for path in final_paths.values()) >= newest_source_mtime
        and has_final_trace
    ):
        print(f"目标世界分栏知识库已存在：{_final_world_dir(ws)}")
        print("使用 --force 可重新汇总。")
        return _final_world_dir(ws)

    primary_paths = [
        (section_name, primary_item["sections"][section_name])
        for section_name, _ in WORLD_SECTIONS
        if section_name in primary_item.get("sections", {}) and _has_meaningful_file(primary_item["sections"][section_name])
    ]
    current_summary = _aggregate_sections(primary_paths)
    if not supplement_items:
        _write_sections_to_final(ws, _split_sections_from_document(current_summary))
    else:
        os.makedirs(final_all_partials_dir, exist_ok=True)
        for idx, item in enumerate(supplement_items, start=1):
            record = item["record"]
            supplement_paths = [
                (section_name, item["sections"][section_name])
                for section_name, _ in WORLD_SECTIONS
                if section_name in item.get("sections", {}) and _has_meaningful_file(item["sections"][section_name])
            ]
            if not supplement_paths:
                continue
            print(
                f"  整合最终知识库全栏目：{record['file_name']} "
                f"{idx}/{len(supplement_items)}"
            )
            current_summary = _run_prompt(
                llm,
                "world_knowledge_merge_all_sections",
                dict(
                    merge_task=(
                        "最终全栏目串行整合：已有阶段摘要是主资料7栏目知识库及已整合补充资料，"
                        f"本轮只整合补充资料《{record['file_name']}》的7栏目知识库。"
                        "故事主线、核心事件顺序、核心因果、基础身份关系以主资料为准。"
                        "力量体系、技能体系、关键物品、角色实力/背景、世界观细节允许补充资料进行公共化校正和完善。"
                        "排除补充资料原创主角线、原创金手指和原创主线任务。"
                    ),
                    previous_summary=_compact_world_document(current_summary),
                    knowledge_cards=_aggregate_sections(supplement_paths, max_chars=40000),
                ),
                os.path.join(final_all_partials_dir, f"integrated_{idx:03d}_{record['id']}.md"),
                required_headings=WORLD_SECTION_NAMES,
            )
        _write_sections_to_final(ws, _split_sections_from_document(current_summary))

    legacy_path = os.path.join(_world_root(ws), "world_knowledge.md")
    if os.path.exists(legacy_path):
        os.remove(legacy_path)
        print(f"  -> 已移除旧版聚合知识库：{legacy_path}")
    print(f"  -> 最终分栏知识库目录：{_final_world_dir(ws)}")
    return _final_world_dir(ws)


def _build_supplement_usage_audit(ws, source_items, llm, force=False):
    primary_item = next(
        (item for item in source_items if item["record"].get("role") == "primary"),
        source_items[0] if source_items else None,
    )
    supplement_items = [
        item for item in source_items
        if primary_item and item["record"].get("id") != primary_item["record"].get("id")
    ]
    if not primary_item or not supplement_items:
        return None

    final_paths = _final_section_paths(ws)
    supplement_paths = [
        (f"{item['record'].get('file_name', '补充资料')} / {section_name}", path)
        for item in supplement_items
        for section_name, path in item.get("sections", {}).items()
        if _has_meaningful_file(path)
    ]
    if not final_paths or not supplement_paths:
        return None

    output_path = os.path.join(_audits_dir(ws), "supplement_usage_audit.md")
    source_paths = [path for _, path in final_paths + supplement_paths]
    canon_path = _canon_index_path(ws)
    if os.path.exists(canon_path):
        source_paths.append(canon_path)

    newest_mtime = max(os.path.getmtime(path) for path in source_paths)
    if os.path.exists(output_path) and not force and os.path.getmtime(output_path) >= newest_mtime:
        return output_path

    print("  审计补充资料利用情况...")
    _run_prompt(
        llm,
        "world_supplement_usage_audit",
        dict(
            primary_name=primary_item["record"].get("file_name", "主资料"),
            supplement_names="、".join(item["record"].get("file_name", "补充资料") for item in supplement_items),
            canon_index=_read_file(canon_path) if os.path.exists(canon_path) else "（无主资料基准索引）",
            final_knowledge=_aggregate_sections(final_paths, max_chars=40000),
            supplement_knowledge=_aggregate_sections(supplement_paths, max_chars=40000),
        ),
        output_path,
    )
    print(f"  -> 补充资料利用审计已保存：{output_path}")
    return output_path


# ── 公共入口：构建知识库 ──

def build_world_knowledge(ws, llm, force=False, chunk_size=36000, merge_chunk_size=50000,
                          chapter_batch_size=20, max_workers=4, primary_source=None,
                          merge_only=False):
    """Build structured target-world knowledge from imported source files."""
    _ = merge_chunk_size  # 保留旧参数兼容；当前合并固定按每轮2张 card 串行处理。
    records = _assign_source_roles(_source_records(ws), primary_source=primary_source)
    if not records:
        print("错误：未找到目标世界资料。请先运行 world-import。")
        return None

    os.makedirs(_cards_dir(ws), exist_ok=True)
    os.makedirs(_partials_dir(ws), exist_ok=True)
    os.makedirs(_worlds_dir(ws), exist_ok=True)

    primary = next((record for record in records if record.get("role") == "primary"), None)
    if primary:
        reason = primary.get("role_reason") or "最大文件"
        print(f"  主资料：{primary['file_name']}（{reason}，{primary.get('size', 0)} 字节）")
    supplements = [record for record in records if record.get("role") != "primary"]
    if supplements:
        print("  补充资料：" + "、".join(record["file_name"] for record in supplements))

    if merge_only:
        print("  -> merge-only：跳过 cards/canon/source worlds，直接基于已有 worlds/<资料名>/*.md 重建 _final。")
        source_items = _load_existing_source_sections(ws, records)
        if not source_items:
            print("错误：未找到可用于合并的资料级分栏知识库。请先完整运行 world-build。")
            return None
        final_dir = _integrate_final_sections(ws, source_items, llm, force=True, max_workers=max_workers)
        if final_dir:
            _build_supplement_usage_audit(ws, source_items, llm, force=True)
        return final_dir

    card_paths_by_source = {}
    source_slices_by_id = {}
    for record in records:
        slices = _source_slices(record, chunk_size=chunk_size, chapter_batch_size=chapter_batch_size)
        if slices:
            source_slices_by_id[record["id"]] = slices

    if primary and primary.get("id") in source_slices_by_id:
        card_paths_by_source[primary["id"]] = _build_record_cards(
            ws,
            primary,
            source_slices_by_id[primary["id"]],
            llm,
            force=force,
            canon_index="",
            max_workers=max_workers,
        )

    canon_index = _build_canon_index(
        ws,
        primary,
        card_paths_by_source.get(primary["id"], []),
        llm,
        force=force,
    ) if primary else ""
    canon_index_mtime = (
        os.path.getmtime(_canon_index_path(ws))
        if canon_index and os.path.exists(_canon_index_path(ws))
        else None
    )

    for record in records:
        if primary and record.get("id") == primary.get("id"):
            continue
        slices = source_slices_by_id.get(record["id"], [])
        if not slices:
            continue
        card_paths_by_source[record["id"]] = _build_record_cards(
            ws,
            record,
            slices,
            llm,
            force=force,
            canon_index=canon_index,
            dependency_mtime=canon_index_mtime,
            max_workers=max_workers,
        )

    existing_cards = [
        path
        for paths in card_paths_by_source.values()
        for path in paths
        if _has_meaningful_file(path)
    ]
    if not existing_cards:
        print("错误：资料分片为空，无法生成世界知识库。")
        return None

    source_items = []
    for record in records:
        source_world = _build_single_source_sections(
            ws,
            record,
            card_paths_by_source.get(record["id"], []),
            llm,
            force=force,
            max_workers=max_workers,
        )
        if source_world:
            source_items.append(source_world)

    if not source_items:
        print("错误：未能生成任何资料级分栏世界知识库。")
        return None

    final_dir = _integrate_final_sections(ws, source_items, llm, force=force, max_workers=max_workers)
    if final_dir:
        _build_supplement_usage_audit(ws, source_items, llm, force=force)
    return final_dir


# ── 公共入口：加载上下文 ──

def load_world_knowledge_context(ws, max_chars=80000):
    manifest = _load_manifest(ws)
    # 用户可在 Web 界面关闭资料库；关闭后下游设计流程不再注入资料。
    if manifest.get("enabled", True) is False:
        return ""
    section_paths = _final_section_paths(ws)
    if section_paths:
        return _aggregate_sections(section_paths, max_chars=max_chars)

    legacy_path = os.path.join(_world_root(ws), "world_knowledge.md")
    if not os.path.exists(legacy_path):
        return ""

    content = _read_file(legacy_path).strip()
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n\n（目标世界知识库内容过长，以上为截断后的前置摘要。）"


def world_knowledge_status(ws):
    """返回资料库是否已具备可注入下游生成的完整7栏目。"""
    manifest = _load_manifest(ws)
    source_count = len(_source_records(ws))
    final_section_count = len(_final_section_paths(ws))
    return {
        "enabled": bool(manifest.get("enabled", True)),
        "source_count": source_count,
        "final_section_count": final_section_count,
        "ready": final_section_count == len(WORLD_SECTIONS),
    }


def set_world_knowledge_enabled(ws, enabled: bool) -> bool:
    """切换资料库启用状态；持久化到 manifest。返回最终状态。"""
    manifest = _load_manifest(ws)
    manifest["enabled"] = bool(enabled)
    _save_manifest(ws, manifest)
    return bool(enabled)


def is_world_knowledge_enabled(ws) -> bool:
    """读取资料库启用状态。"""
    return bool(_load_manifest(ws).get("enabled", True))
