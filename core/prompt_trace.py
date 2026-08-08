"""记录模型调用的实际 Prompt，供 Web 工作台实时展示。"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Callable


_TRACE_CALLBACK: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "harness_novel_prompt_trace_callback", default=None,
)
_FILE_LOCK = threading.Lock()


def record_prompt(prompt: str, model: str = "", label: str = "") -> dict:
    event = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": str(model or ""),
        "label": str(label or "模型调用"),
        "prompt": str(prompt or ""),
    }
    trace_file = os.getenv("HARNESS_NOVEL_PROMPT_TRACE_FILE", "").strip()
    if trace_file:
        try:
            path = Path(trace_file)
            with _FILE_LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
    callback = _TRACE_CALLBACK.get()
    if callback:
        try:
            callback(dict(event))
        except Exception:
            # Prompt 展示属于观测能力，不能反向中断正文生成。
            pass
    return event


@contextmanager
def capture_prompts(callback: Callable[[dict], None]):
    """在当前后台任务线程中捕获模型 Prompt，不影响其他并发任务。"""
    token = _TRACE_CALLBACK.set(callback)
    try:
        yield
    finally:
        _TRACE_CALLBACK.reset(token)
