import json
import re


def clean_markdown_symbols(text: str) -> str:
    """清洗文本中的 Markdown 格式符号（加粗、斜体、列表标记等），保留 # 标题。"""
    if not text:
        return text
    # 移除 **加粗** 和 *斜体* 标记（保留内部文字）
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # 移除行首的 - 列表标记（保留内容）
    text = re.sub(r'^(\s*)-\s+', r'\1', text, flags=re.MULTILINE)
    # 移除行首的 > 引用标记
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    return text


def normalize_text(text: str) -> str:
    """统一文本格式：去除全角空格缩进、压缩多余空行、去除行尾空白。"""
    if not text:
        return text

    # 去除全角空格（U+3000），中文网文中仅用于段落缩进
    text = text.replace('　', '')

    # 连续3个以上换行压缩为2个（保留段落分隔）
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 每行去除末尾空白
    lines = text.split('\n')
    lines = [line.rstrip() for line in lines]
    text = '\n'.join(lines)

    # 整体去除首尾空白
    text = text.strip()

    return text


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline != -1:
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _extract_json_candidate(text: str) -> str:
    """Extract the first top-level JSON object/array from noisy LLM text."""
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not starts:
        return text
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    stack = [closing]
    in_string = False
    escape = False
    for idx in range(start + 1, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return text[start:idx + 1]
    return text[start:]


def _escape_control_chars_inside_strings(text: str) -> str:
    """Escape raw newlines/tabs inside JSON strings without changing formatting outside strings."""
    out = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            out.append(ch)
            in_string = not in_string
            continue
        if in_string and ch == "\n":
            out.append("\\n")
        elif in_string and ch == "\r":
            out.append("\\r")
        elif in_string and ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def _light_json_repair(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', repaired)
    repaired = repaired.replace("，}", "}").replace("，]", "]")
    repaired = repaired.replace(",}", "}").replace(",]", "]")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    return repaired


def parse_json_response(raw: str) -> dict:
    """Parse JSON returned by an LLM, with repair for common JSON-ish outputs."""
    if raw is None:
        raise json.JSONDecodeError("empty JSON response", "", 0)

    cleaned = _strip_code_fence(str(raw))
    candidate = _extract_json_candidate(cleaned)
    variants = [
        cleaned,
        candidate,
        _light_json_repair(candidate),
        _light_json_repair(_escape_control_chars_inside_strings(candidate)),
    ]

    last_error = None
    seen = set()
    for item in variants:
        if item in seen:
            continue
        seen.add(item)
        try:
            return json.loads(item)
        except json.JSONDecodeError as e:
            last_error = e
            decoder = json.JSONDecoder()
            try:
                parsed, _ = decoder.raw_decode(item)
                return parsed
            except json.JSONDecodeError:
                pass

    if last_error:
        raise last_error
    return json.loads(candidate)
