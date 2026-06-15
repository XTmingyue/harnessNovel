import os
import re


DEFAULT_FORBIDDEN_TERMS = [
    "西游",
    "方寸山",
    "斜月三星洞",
    "菩提祖师",
    "孙悟空",
    "唐三藏",
    "东汉三藏",
    "取经人",
    "金蝉子",
    "花果山",
    "如意金箍棒",
    "金箍棒",
    "大品天仙诀",
    "紫霄玄真悟元功",
]

TERM_EXTRACT_STOPWORDS = {
    "章纲",
    "正文",
    "批次摘要",
    "卷纲",
    "后续生成",
    "参考小说",
    "映射说明",
    "输出",
    "处理方式",
}


def _read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _candidate_files(ws, volume=None):
    adaptation_dir = os.path.join(ws.file_system, "adaptation")
    rewrite_dir = os.path.join(ws.file_system, "rewrite_maps")

    names = [
        "rewrite_map.md",
        "rewrite_map.txt",
        "rewrite_map.jsonl",
    ]
    if volume is not None:
        names.extend([
            f"rewrite_map_vol_{volume:02d}.md",
            f"rewrite_map_vol_{volume:02d}.txt",
            f"rewrite_map_vol_{volume:02d}.jsonl",
            f"vol_{volume:02d}_map.md",
            f"vol_{volume:02d}_map.txt",
            f"vol_{volume:02d}_map.jsonl",
        ])

    for base in [adaptation_dir, rewrite_dir]:
        for name in names:
            yield os.path.join(base, name)


def load_rewrite_map(ws, volume=None):
    """Load global and volume-specific rewrite map text, if present."""
    parts = []
    seen = set()
    for path in _candidate_files(ws, volume):
        if path in seen:
            continue
        seen.add(path)
        content = _read_file(path)
        if content:
            parts.append(f"【来源：{path}】\n{content}")
    return "\n\n---\n\n".join(parts) if parts else "（未找到换皮映射表，请严格以新小说大纲和世界观为准。）"


def _load_forbidden_term_files(ws, volume=None):
    adaptation_dir = os.path.join(ws.file_system, "adaptation")
    rewrite_dir = os.path.join(ws.file_system, "rewrite_maps")
    names = [
        "forbidden_terms.txt",
        "forbidden_terms.md",
        "forbidden_terms.jsonl",
    ]
    if volume is not None:
        names.extend([
            f"forbidden_terms_vol_{volume:02d}.txt",
            f"forbidden_terms_vol_{volume:02d}.md",
            f"forbidden_terms_vol_{volume:02d}.jsonl",
        ])

    chunks = []
    for base in [adaptation_dir, rewrite_dir]:
        for name in names:
            content = _read_file(os.path.join(base, name))
            if content:
                chunks.append(content)
    return chunks


def extract_forbidden_terms_from_text(text):
    """Extract quoted or delimited forbidden terms from rewrite-map style text."""
    if not text:
        return []

    terms = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (
            stripped.startswith("禁止残留参考元素")
            or stripped.startswith("硬禁用元素")
            or stripped.startswith("不得直接出现")
            or stripped.startswith("禁用词")
            or stripped.lower().startswith("forbidden")
        ):
            continue

        quoted = re.findall(r"[“\"']([^”\"']+)[”\"']", line)
        bracketed = re.findall(r"《([^》]+)》", line)
        terms.extend(quoted)
        terms.extend(bracketed)

        if "：" in line:
            tail = line.split("：", 1)[1]
        elif ":" in line:
            tail = line.split(":", 1)[1]
        else:
            tail = ""
        for item in re.split(r"[、,，/；;]", tail):
            item = item.strip(" \t。.!！?？[]【】（）()“”\"'")
            if (
                2 <= len(item) <= 20
                and item not in TERM_EXTRACT_STOPWORDS
                and not any(x in item for x in ["必须", "改写", "替换", "出现", "参考", "输出"])
            ):
                terms.append(item)

    return _dedupe_terms(terms)


def _dedupe_terms(terms):
    seen = set()
    result = []
    for term in terms:
        term = str(term).strip()
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def load_forbidden_terms(ws, volume=None):
    """Load configured forbidden terms plus high-risk default reference leftovers."""
    chunks = _load_forbidden_term_files(ws, volume)
    rewrite_map = load_rewrite_map(ws, volume)
    terms = []
    for chunk in chunks:
        for line in chunk.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            terms.extend(re.split(r"[、,，/；;]", line))
    terms.extend(extract_forbidden_terms_from_text(rewrite_map))
    terms.extend(DEFAULT_FORBIDDEN_TERMS)
    return _dedupe_terms(terms)


def format_forbidden_terms(terms):
    if not terms:
        return "（无显式禁用词。仍需避免继承参考小说专有名词和事件因果。）"
    return "\n".join(f"- {term}" for term in terms)


def scan_forbidden_terms(text, terms, exempt_line_patterns=None):
    """Return forbidden terms found in text. Optional line patterns exempt reference-comparison lines."""
    if not text or not terms:
        return []
    exempt_line_patterns = tuple(exempt_line_patterns or [])
    found = []
    for line in text.splitlines():
        if exempt_line_patterns and any(pat in line for pat in exempt_line_patterns):
            continue
        for term in terms:
            if term and term in line:
                found.append(term)
    return _dedupe_terms(found)


def append_adaptation_report(ws, title, message):
    report_dir = os.path.join(ws.file_system, "adaptation")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "adaptation_report.md")
    with open(report_path, "a", encoding="utf-8") as f:
        f.write(f"\n# {title}\n\n{message.strip()}\n")
    return report_path
