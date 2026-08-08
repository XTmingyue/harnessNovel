"""文本导入时的编码识别与 UTF-8 规范化。"""

from __future__ import annotations

from pathlib import Path

try:
    from charset_normalizer import from_bytes
except ImportError:  # 兼容已安装的旧版本，仍可使用内置中文编码回退。
    from_bytes = None


_BOM_ENCODINGS = (
    (b"\xef\xbb\xbf", "utf-8-sig", "UTF-8 with BOM"),
    (b"\xff\xfe\x00\x00", "utf-32-le", "UTF-32 LE"),
    (b"\x00\x00\xfe\xff", "utf-32-be", "UTF-32 BE"),
    (b"\xff\xfe", "utf-16-le", "UTF-16 LE"),
    (b"\xfe\xff", "utf-16-be", "UTF-16 BE"),
)
_COMMON_CJK = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说"
    "這個們來時國為著與讓從於後還開發體說學會應測試"
)


def _cjk_score(text: str) -> tuple[int, int]:
    """为中文候选解码打分，避免短 GBK 文本被误判成 Big5。"""
    cjk_count = sum("\u4e00" <= char <= "\u9fff" for char in text)
    common_count = sum(char in _COMMON_CJK for char in text)
    return common_count, cjk_count


def decode_text_bytes(raw: bytes) -> tuple[str, str]:
    """解码常见网文文本编码，并返回内容及识别出的编码名称。"""
    for marker, encoding, label in _BOM_ENCODINGS:
        if raw.startswith(marker):
            return raw.decode(encoding), label

    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass

    candidates: list[tuple[str, str]] = []
    if from_bytes is not None:
        detected = from_bytes(raw).best()
        if detected and detected.encoding:
            candidates.append((str(detected), detected.encoding.upper()))

    # GB18030 覆盖 GBK/GB2312，是中文小说最常见的兼容选择；与探测结果一起评分。
    for encoding, label in (("gb18030", "GB18030/GBK"), ("big5", "Big5")):
        try:
            candidates.append((raw.decode(encoding), label))
        except UnicodeDecodeError:
            continue

    chinese_candidates = [candidate for candidate in candidates if _cjk_score(candidate[0])[1] > 0]
    if chinese_candidates:
        return max(chinese_candidates, key=lambda candidate: _cjk_score(candidate[0]))
    if candidates:
        return candidates[0]

    raise ValueError("无法识别参考小说编码。请先转换为 UTF-8 后重新导入。")


def copy_as_utf8(source: str | Path, destination: str | Path) -> str:
    """读取源文本并以 UTF-8 写入目标路径，返回源文件识别编码。"""
    source_path = Path(source)
    destination_path = Path(destination)
    text, encoding = decode_text_bytes(source_path.read_bytes())
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(text, encoding="utf-8")
    return encoding
