import os

_GLOBAL_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".harnessNovel")
_GLOBAL_ENV_PATH = os.path.join(_GLOBAL_CONFIG_DIR, ".env")


def _load_env():
    """按优先级查找 .env：~/.harnessNovel/.env → 当前目录兼容回退。"""
    for env_path in [
        _GLOBAL_ENV_PATH,
        os.path.join(os.getcwd(), ".env"),
    ]:
        env = {}
        if not os.path.exists(env_path):
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
        return env
    return {}


class ConfigLoader:
    _env = None

    @classmethod
    def reload(cls):
        """清除进程内 .env 缓存，使 Web 端保存的新配置可被下一次调用读取。"""
        cls._env = None

    @classmethod
    def activate(cls, updates):
        """应用运行时配置，使当前进程及后续子进程立即使用新值。"""
        for key, value in updates.items():
            os.environ[str(key)] = str(value)
        cls.reload()

    @classmethod
    def _get_env(cls):
        if cls._env is None:
            cls._env = _load_env()
        return cls._env

    @classmethod
    def _build_config(cls, prefix):
        """根据前缀从环境变量/.env 构建 LLM 配置字典。"""
        env = cls._get_env()
        return {
            "model": os.getenv(f"{prefix}_MODEL") or env.get(f"{prefix}_MODEL", ""),
            "base_url": os.getenv(f"{prefix}_BASE_URL") or env.get(f"{prefix}_BASE_URL", ""),
            "api_key": os.getenv(f"{prefix}_API_KEY") or env.get(f"{prefix}_API_KEY", ""),
        }

    @classmethod
    def get_data_builder_config(cls):
        """参考小说批次摘要提取的模型配置（init 流程）。"""
        return cls._build_config("DATA_BUILDER")

    @classmethod
    def get_adaptive_builder_config(cls):
        """全书设计与舞台设计配置（推荐 pro 模型）。"""
        return cls._build_config("ADAPTIVE_BUILDER")

    @classmethod
    def get_adaptive_builder_lite_config(cls):
        """故事情节、章纲、正文及轻量辅助任务配置（推荐 flash 模型）。"""
        return cls._build_config("ADAPTIVE_BUILDER_LITE")
