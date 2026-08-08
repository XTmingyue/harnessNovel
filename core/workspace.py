import os


def get_novels_dir():
    """返回工作区根目录。

    命令行模式保持原有约定：未配置时使用当前目录下的 ``my-novels``。
    Web 工作台可通过 ``HARNESS_NOVEL_HOME`` 指向用户选择的固定目录，避免
    服务器启动目录改变后找不到既有小说。
    """
    configured = os.getenv("HARNESS_NOVEL_HOME")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.getcwd(), "my-novels")


# 保留旧常量，兼容可能直接引用它的外部脚本；本项目内部统一走 get_novels_dir()。
NOVELS_DIR = get_novels_dir()


class NovelWorkspace:
    """一本小说的独立工作区，包含所有数据目录的路径解析。"""

    def __init__(self, name):
        self.name = name
        self.root = os.path.join(get_novels_dir(), name)
        self.file_system = os.path.join(self.root, "file_system")
        self.creative_direction = os.path.join(self.root, "creative_direction.md")
        self.reference = os.path.join(self.root, "reference")
        self.reference_outlines = os.path.join(self.reference, "outlines")
        self.reference_sample = os.path.join(self.reference, "sample_novel.txt")
        self.reference_chapters = os.path.join(self.reference, "chapters")

    # ── 目录初始化 ──

    def ensure_dirs(self):
        """确保所有必要的子目录存在。其他派生子目录由写入时自动创建。"""
        for d in [self.root, self.file_system, self.reference, self.reference_outlines, self.reference_chapters]:
            os.makedirs(d, exist_ok=True)


def list_novels():
    """列出所有已有工作区名称。"""
    novels_dir = get_novels_dir()
    if not os.path.isdir(novels_dir):
        return []
    return sorted(
        d for d in os.listdir(novels_dir)
        if os.path.isdir(os.path.join(novels_dir, d))
    )


def init_workspace(name):
    """创建或返回已有工作区。"""
    ws = NovelWorkspace(name)
    ws.ensure_dirs()
    return ws
