import os


NOVELS_DIR = os.path.join(os.getcwd(), "my-novels")


class NovelWorkspace:
    """一本小说的独立工作区，包含所有数据目录的路径解析。"""

    def __init__(self, name):
        self.name = name
        self.root = os.path.join(NOVELS_DIR, name)
        self.file_system = os.path.join(self.root, "file_system")
        self.creative_direction = os.path.join(self.root, "creative_direction.md")
        self.reference = os.path.join(self.root, "reference")
        self.reference_outlines = os.path.join(self.reference, "outlines")
        self.reference_sample = os.path.join(self.reference, "sample_novel.txt")
        self.reference_chapters = os.path.join(self.reference, "chapters")

    # ── 目录初始化 ──

    def ensure_dirs(self):
        """确保所有必要的子目录存在。子目录（worldviews、new_volume_outlines 等）由写入时自动创建。"""
        for d in [self.root, self.file_system, self.reference, self.reference_outlines, self.reference_chapters]:
            os.makedirs(d, exist_ok=True)


def list_novels():
    """列出所有已有工作区名称。"""
    if not os.path.isdir(NOVELS_DIR):
        return []
    return sorted(
        d for d in os.listdir(NOVELS_DIR)
        if os.path.isdir(os.path.join(NOVELS_DIR, d))
    )


def init_workspace(name):
    """创建或返回已有工作区。"""
    ws = NovelWorkspace(name)
    ws.ensure_dirs()
    return ws
