"""故事情节单元的对话管理。

每个工作区 + 卷号独立维护一段对话。首条消息生成整卷情节单元，
后续消息基于当前情节单元进行调整。历史对话仅作展示，不限制轮数。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.workspace import init_workspace
from core.prompt_trace import capture_prompts


def _read_text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _arc_files_exist(ws, volume: int) -> bool:
    """检查指定卷是否已有故事情节单元文件。"""
    arc_dir = os.path.join(ws.file_system, "story_arcs", f"vol_{volume:02d}")
    if not os.path.isdir(arc_dir):
        return False
    for fname in os.listdir(arc_dir):
        if fname.startswith("arc_") and fname.endswith(".md"):
            return True
    return False


def _conversation_path(root: Path, workspace: str, volume: int) -> Path:
    return root / workspace / "file_system" / "story_arcs" / f"vol_{volume:02d}" / "conversation.json"


class ArcsConversation:
    def __init__(self, volume: int, path: Path):
        self.volume = volume
        self.path = path
        self.turns: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self.turns = [t for t in data.get("turns", []) if isinstance(t, dict)]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"volume": self.volume, "turns": self.turns,
                 "updated_at": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def history(self) -> dict[str, Any]:
        return {"volume": self.volume, "turns": self.turns}

    def append_user(self, content: str) -> None:
        self.turns.append({"role": "user", "content": content, "at": datetime.now().isoformat(timespec="seconds")})

    def append_assistant(self, note: str, artifacts=None) -> None:
        self.turns.append({
            "role": "assistant",
            "content": note,
            "at": datetime.now().isoformat(timespec="seconds"),
            "artifacts": artifacts or [],
        })

    def clear(self) -> None:
        self.turns = []
        self.save()


class ArcsChatManager:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)
        self._cache: dict[tuple[str, int], ArcsConversation] = {}
        self._jobs: dict[tuple[str, int], dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def get(self, workspace: str, volume: int) -> ArcsConversation:
        key = (workspace, volume)
        if key not in self._cache:
            self._cache[key] = ArcsConversation(volume, _conversation_path(self.root, workspace, volume))
        return self._cache[key]

    def history(self, workspace: str, volume: int) -> dict[str, Any]:
        """返回对话，并附带当前舞台是否存在实际情节文件。"""
        ws = init_workspace(workspace)
        history = self.get(workspace, volume).history()
        history["has_arcs"] = _arc_files_exist(ws, volume)
        return history

    def run_message(self, workspace: str, volume: int, message: str) -> dict[str, Any]:
        """统一对话入口：首条消息生成整卷情节，后续消息调整。"""
        ws = init_workspace(workspace)
        conv = self.get(workspace, volume)
        display_text = message.strip()
        if not display_text:
            raise ValueError("请输入内容后再发送。")

        conv.append_user(display_text)
        from training.adaptive_builder import gen_story_arcs, refine_story_arcs

        is_initial = not _arc_files_exist(ws, volume)
        if is_initial:
            # 用消息内容生成整卷情节单元
            # gen_story_arcs 内部完成串行生成
            result = gen_story_arcs(ws, volume=volume)
            mode = "initial"
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(str(result["error"]))
            if not isinstance(result, dict) or not result.get("artifacts"):
                raise RuntimeError(
                    f"生成失败：未产生任何故事情节单元。请确认舞台{volume}已设计完成（stage_roadmap.md 中存在对应舞台且包含预计章节数），且已配置大模型 API。"
                )
        else:
            result = refine_story_arcs(ws, volume, instruction=display_text)
            mode = "refine"
        if not result:
            raise RuntimeError("未配置可用模型，请先在右上角配置大模型 API。")

        note = str(result.get("adjustment_note") or "").strip()
        if not note:
            note = f"已生成卷{volume}的故事情节单元。" if mode == "initial" else "已按指令调整。"

        # 提取 artifact 链接
        artifacts = result.get("artifacts") or []
        if not artifacts:
            # 从文件系统扫描该卷的 arc 文件
            arc_dir = os.path.join(ws.file_system, "story_arcs", f"vol_{volume:02d}")
            if os.path.isdir(arc_dir):
                for fname in sorted(os.listdir(arc_dir)):
                    if fname.startswith("arc_") and fname.endswith(".md"):
                        import re
                        m = re.match(r'arc_(\d+)_ch(\d+)_(\d+)\.md$', fname)
                        if m:
                            arc_idx = int(m.group(1))
                            s_ch = int(m.group(2))
                            e_ch = int(m.group(3))
                            artifacts.append({
                                "path": f"file_system/story_arcs/vol_{volume:02d}/{fname}",
                                "label": f"情节单元{arc_idx}（第{s_ch}-{e_ch}章）",
                            })
        conv.append_assistant(note, artifacts)
        conv.save()
        return {"mode": mode, "result": result, "conversation": conv.history()}

    def start_message(self, workspace: str, volume: int, message: str, resume_incomplete: bool = False) -> dict[str, Any]:
        """在后台执行聊天生成，使前端可以读取进度并暂停。"""
        key = (workspace, volume)
        display_text = message.strip()
        if not display_text:
            raise ValueError("请输入内容后再发送。")
        with self._jobs_lock:
            current = self._jobs.get(key)
            if current and current["status"] in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前舞台已有生成任务正在进行。")
            pause_event = threading.Event()
            pause_event.set()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            job = {
                "id": uuid.uuid4().hex,
                "status": "running",
                "phase": "queued",
                "completed": 0,
                "total": 0,
                "progress_kind": "story_arcs",
                "message": "任务已创建，正在启动",
                "pause_event": pause_event,
                "stop_event": stop_event,
                "cancel_event": cancel_event,
                "prompt_history": [],
                "prompt_count": 0,
                "error": "",
            }
            self._jobs[key] = job
        conv = self.get(workspace, volume)
        if not resume_incomplete:
            conv.append_user(display_text)
            conv.save()

        def update(phase: str, completed: int, total: int, detail: str) -> None:
            with self._jobs_lock:
                active = self._jobs.get(key)
                if not active or active["id"] != job["id"]:
                    return
                active.update(
                    phase=phase,
                    completed=completed,
                    total=total,
                    message=detail,
                    status="paused" if phase == "paused" else active["status"],
                )

        def worker() -> None:
            def trace_prompt(event: dict) -> None:
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if not active or active["id"] != job["id"]:
                        return
                    history = active.setdefault("prompt_history", [])
                    history.append(event)
                    del history[:-50]
                    active.update(
                        prompt_count=len(history), current_prompt_id=event.get("id"),
                        prompt_model=event.get("model", ""),
                        prompt_created_at=event.get("created_at", ""),
                    )
            trace_context = capture_prompts(trace_prompt)
            trace_context.__enter__()
            try:
                ws = init_workspace(workspace)
                conv = self.get(workspace, volume)
                from training.adaptive_builder import gen_story_arcs, refine_story_arcs_serial
                is_initial = resume_incomplete or not _arc_files_exist(ws, volume)
                if is_initial:
                    result = gen_story_arcs(
                        ws, volume=volume, progress_callback=update,
                        pause_event=pause_event, stop_event=stop_event,
                        cancel_event=cancel_event,
                    )
                    mode = "resume" if resume_incomplete else "initial"
                else:
                    with self._jobs_lock:
                        active = self._jobs.get(key)
                        if active and active["id"] == job["id"]:
                            active["progress_kind"] = "serial_refine"
                    result = refine_story_arcs_serial(
                        ws, volume, instruction=display_text,
                        progress_callback=update,
                        pause_event=pause_event,
                        stop_event=stop_event,
                        cancel_event=cancel_event,
                    )
                    mode = "refine"
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(str(result["error"]))
                if not result:
                    raise RuntimeError("未配置可用模型，请先在右上角配置大模型 API。")
                artifacts = result.get("artifacts") or []
                note = str(result.get("adjustment_note") or "").strip()
                if not note:
                    note = f"已生成卷{volume}的故事情节单元。" if mode == "initial" else "已按指令调整。"
                conv.append_assistant(note, artifacts)
                conv.save()
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        stopped = bool(result.get("stopped"))
                        active.update(
                            status="stopped" if stopped else "completed",
                            phase="stopped" if stopped else "completed",
                            message=note,
                            result={"mode": mode},
                        )
            except Exception as exc:
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        active.update(status="failed", phase="failed", message="生成失败", error=str(exc))
            finally:
                trace_context.__exit__(None, None, None)

        threading.Thread(target=worker, name=f"arcs-chat-{volume}", daemon=True).start()
        return self.job_status(workspace, volume)

    def job_status(self, workspace: str, volume: int) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, volume))
            if not job:
                from training.adaptive_builder import story_arc_resume_status
                ws = init_workspace(workspace)
                resume = story_arc_resume_status(ws, volume)
                return {
                    "status": "idle",
                    "phase": "idle",
                    "message": "",
                    **resume,
                }
            return {
                k: v for k, v in job.items()
                if k not in {"pause_event", "stop_event", "cancel_event", "prompt_history"}
            }

    def prompts(self, workspace: str, volume: int) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, volume))
            return {
                "job_id": job.get("id") if job else None,
                "items": [dict(item) for item in (job or {}).get("prompt_history", [])],
            }

    def continue_incomplete(self, workspace: str, volume: int) -> dict[str, Any]:
        from training.adaptive_builder import story_arc_resume_status
        ws = init_workspace(workspace)
        resume = story_arc_resume_status(ws, volume)
        if not resume.get("can_resume"):
            raise ValueError("当前舞台没有可继续的未完成故事情节。")
        return self.start_message(
            workspace, volume, "继续生成未完成的故事情节",
            resume_incomplete=True,
        )

    def pause(self, workspace: str, volume: int) -> dict[str, Any]:
        key = (workspace, volume)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing"}:
                raise ValueError("当前没有可暂停的生成任务。")
            job["pause_event"].clear()
            job["cancel_event"].set()
            job.update(status="pausing", message="正在暂停当前模型请求")
        return self.job_status(workspace, volume)

    def resume(self, workspace: str, volume: int) -> dict[str, Any]:
        key = (workspace, volume)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"paused", "pausing"}:
                raise ValueError("当前没有已暂停的生成任务。")
            job["cancel_event"].clear()
            job["pause_event"].set()
            job.update(status="running", phase="generating", message="已继续生成")
        return self.job_status(workspace, volume)

    def stop(self, workspace: str, volume: int) -> dict[str, Any]:
        key = (workspace, volume)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing", "paused"}:
                raise ValueError("当前没有可结束的生成任务。")
            job["stop_event"].set()
            job["cancel_event"].set()
            job["pause_event"].set()
            job.update(status="stopping", phase="stopping", message="正在结束本轮生成")
        return self.job_status(workspace, volume)

    def reset(self, workspace: str, volume: int) -> dict[str, Any]:
        """只清空当前舞台的对话和故事情节单元，不影响其他舞台。"""
        import re
        key = (workspace, volume)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if job and job.get("status") in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前舞台仍在生成，请先结束任务再重置。")
            if job:
                job["prompt_history"] = []
                job["prompt_count"] = 0
                for field in ("current_prompt_id", "prompt_model", "prompt_created_at"):
                    job.pop(field, None)
        ws = init_workspace(workspace)
        arc_dir = os.path.join(ws.file_system, "story_arcs", f"vol_{volume:02d}")
        if os.path.isdir(arc_dir):
            for fname in list(os.listdir(arc_dir)):
                if re.match(r'^arc_\d+_ch\d+_\d+\.md$', fname) or fname == "arcs_index.json":
                    try:
                        os.remove(os.path.join(arc_dir, fname))
                    except FileNotFoundError:
                        pass
        conv = self.get(workspace, volume)
        conv.clear()
        return {"reset": True, "conversation": conv.history()}

    def clear(self, workspace: str, volume: int) -> dict[str, Any]:
        conv = self.get(workspace, volume)
        conv.clear()
        return {"cleared": True, "conversation": conv.history()}
