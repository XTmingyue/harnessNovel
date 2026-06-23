import os
import re
import glob
import json


DEFAULT_OUTLINES_DIR = os.path.join(os.path.dirname(__file__), 'data', 'outlines')

# 卷目录名格式：vol_01_第一卷_斩落金锁听玄音
VOL_DIR_RE = re.compile(r'^vol_(\d+)_(.+)$')

# 批次文件名格式：batch_001_030.md
BATCH_FILE_RE = re.compile(r'^batch_(\d+)_(\d+)\.md$')
ARC_FILE_RE = re.compile(r'^arc_(\d+)_ch(\d+)_(\d+)\.md$')


def _load_volume_meta(dir_path):
    """加载虚拟卷元数据。如果不存在返回 None。"""
    meta_path = os.path.join(dir_path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_reference_volumes(outlines_dir=None):
    """扫描参考大纲目录，返回 [{vol_idx, title, dir_path}] 列表。"""
    if outlines_dir is None:
        outlines_dir = DEFAULT_OUTLINES_DIR

    if not os.path.isdir(outlines_dir):
        return []

    volumes = []
    for name in sorted(os.listdir(outlines_dir)):
        m = VOL_DIR_RE.match(name)
        if not m:
            continue
        vol_idx = int(m.group(1))
        title = m.group(2).replace('_', ' ')
        dir_path = os.path.join(outlines_dir, name)

        # 虚拟卷：从 meta.json 获取章节数
        meta = _load_volume_meta(dir_path)
        if meta:
            chapter_count = meta["end_ch"] - meta["start_ch"] + 1
        else:
            chapter_count = 0
            # 新版：从故事情节单元文件名推断章节数
            for arc in _story_arc_files(dir_path):
                chapter_count = max(chapter_count, arc["end_ch"])
            # 旧版：从批次文件名推断章节数
            batch_files = glob.glob(os.path.join(dir_path, "batch_*.md"))
            for bf in batch_files:
                bm = BATCH_FILE_RE.match(os.path.basename(bf))
                if bm:
                    chapter_count = max(chapter_count, int(bm.group(2)))

        volumes.append({
            "vol_idx": vol_idx,
            "title": title,
            "chapter_count": chapter_count,
            "dir_path": dir_path,
        })

    return sorted(volumes, key=lambda v: v["vol_idx"])


def load_reference_novel_outline(outlines_dir=None):
    """加载参考小说的完整大纲。"""
    if outlines_dir is None:
        outlines_dir = DEFAULT_OUTLINES_DIR

    path = os.path.join(outlines_dir, "novel_outline.md")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_reference_volume_outline(outlines_dir=None, vol_idx=1):
    """加载参考小说指定卷的卷纲。"""
    if outlines_dir is None:
        outlines_dir = DEFAULT_OUTLINES_DIR

    volumes = list_reference_volumes(outlines_dir)
    for vol in volumes:
        if vol["vol_idx"] == vol_idx:
            path = os.path.join(vol["dir_path"], "volume_outline.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
    return ""


def _read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _story_arc_dir(vol_dir):
    return os.path.join(vol_dir, "story_arcs")


def _story_arc_files(vol_dir):
    arc_dir = _story_arc_dir(vol_dir)
    if not os.path.isdir(arc_dir):
        return []
    items = []
    for fname in sorted(os.listdir(arc_dir)):
        m = ARC_FILE_RE.match(fname)
        if not m:
            continue
        items.append({
            "idx": int(m.group(1)),
            "start_ch": int(m.group(2)),
            "end_ch": int(m.group(3)),
            "path": os.path.join(arc_dir, fname),
        })
    return items


def list_reference_story_arcs(outlines_dir, vol_idx):
    """加载参考小说指定卷的故事情节单元。

    新版工作区优先读取 story_arcs/arc_*.md；旧工作区回退 batch_*.md，
    并把旧批次当成粗粒度故事情节单元返回。
    """
    volumes = list_reference_volumes(outlines_dir)
    vol_info = None
    for vol in volumes:
        if vol["vol_idx"] == vol_idx:
            vol_info = vol
            break

    if vol_info is None:
        return []

    items = []
    for arc in _story_arc_files(vol_info["dir_path"]):
        content = _read_file(arc["path"])
        if not content:
            continue
        copied = dict(arc)
        copied["content"] = content
        copied["source_type"] = "story_arc"
        items.append(copied)
    if items:
        return items

    for bf in sorted(glob.glob(os.path.join(vol_info["dir_path"], "batch_*.md"))):
        bm = BATCH_FILE_RE.match(os.path.basename(bf))
        if not bm:
            continue
        content = _read_file(bf)
        if not content:
            continue
        items.append({
            "idx": len(items) + 1,
            "start_ch": int(bm.group(1)),
            "end_ch": int(bm.group(2)),
            "path": bf,
            "content": content,
            "source_type": "legacy_batch",
        })
    return items


def find_reference_batch(outlines_dir, vol_idx, prod_start, prod_end,
                         prod_vol_total, ref_vol_total=None):
    """按比例映射，优先找到对应的参考故事情节单元，旧工作区回退参考批次文件。

    参数：
        outlines_dir: 参考大纲目录
        vol_idx: 参考卷号
        prod_start, prod_end: 生产小说的段落章节范围（1-indexed）
        prod_vol_total: 生产小说本卷总章数
        ref_vol_total: 参考小说本卷总章数（若为 None 则自动获取）

    返回：拼接的参考故事情节/批次内容字符串
    """
    volumes = list_reference_volumes(outlines_dir)
    vol_info = None
    for vol in volumes:
        if vol["vol_idx"] == vol_idx:
            vol_info = vol
            break

    if vol_info is None:
        return ""

    if ref_vol_total is None:
        ref_vol_total = vol_info["chapter_count"]

    if ref_vol_total == 0 or prod_vol_total == 0:
        return ""

    # 按比例映射到参考章节范围（本地编号）
    frac_start = (prod_start - 1) / prod_vol_total
    frac_end = prod_end / prod_vol_total

    ref_start = max(1, int(frac_start * ref_vol_total) + 1)
    ref_end = min(ref_vol_total, int(frac_end * ref_vol_total))

    # 同时加载前后各一个小窗口，避免边界切割过碎
    window = max(1, ref_vol_total // 20)  # 5% 的窗口
    ref_start = max(1, ref_start - window)
    ref_end = min(ref_vol_total, ref_end + window)

    # 虚拟卷：将本地编号转为全局编号（批次文件使用全局编号）
    meta = _load_volume_meta(vol_info["dir_path"])
    if meta:
        offset = meta["start_ch"] - 1
        ref_start += offset
        ref_end += offset

    # 新版：找到覆盖该范围的故事情节单元
    arc_contents = []
    for arc in _story_arc_files(vol_info["dir_path"]):
        if arc["end_ch"] >= ref_start and arc["start_ch"] <= ref_end:
            content = _read_file(arc["path"])
            if content:
                arc_contents.append(content)
    if arc_contents:
        return "\n\n---\n\n".join(arc_contents)

    # 旧版：找到覆盖该范围的批次文件
    batch_contents = []
    for bf in sorted(glob.glob(os.path.join(vol_info["dir_path"], "batch_*.md"))):
        bm = BATCH_FILE_RE.match(os.path.basename(bf))
        if not bm:
            continue
        batch_start = int(bm.group(1))
        batch_end = int(bm.group(2))
        # 检查是否有重叠
        if batch_end >= ref_start and batch_start <= ref_end:
            content = _read_file(bf)
            if content:
                batch_contents.append(content)

    return "\n\n---\n\n".join(batch_contents)


def find_reference_chapter_outlines(outlines_dir, vol_idx, start_ch, end_ch):
    """查找参考小说指定卷、指定章节范围内的章纲并拼接返回。

    章纲文件路径格式：outlines/vol_XX_卷名/chapter_outlines/chapter_NNN.md

    参数：
        outlines_dir: 参考大纲目录
        vol_idx: 参考卷号
        start_ch, end_ch: 章节范围（1-indexed）

    返回：拼接的章纲内容字符串
    """
    volumes = list_reference_volumes(outlines_dir)
    vol_info = None
    for vol in volumes:
        if vol["vol_idx"] == vol_idx:
            vol_info = vol
            break

    if vol_info is None:
        return ""

    ch_dir = os.path.join(vol_info["dir_path"], "chapter_outlines")
    if not os.path.isdir(ch_dir):
        return ""

    outlines = []
    for ch_num in range(start_ch, end_ch + 1):
        ch_file = os.path.join(ch_dir, f"chapter_{ch_num:03d}.md")
        content = _read_file(ch_file)
        if content:
            outlines.append(f"【参考第{ch_num}章章纲】\n{content}")

    return "\n\n".join(outlines)
