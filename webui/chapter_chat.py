"""逐章章纲的对话管理。

每个工作区 + 卷号 + 情节单元独立维护对话。首条消息生成该情节单元的所有章纲，
后续消息基于当前章纲进行调整。
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


def _chapter_outlines_exist(ws, volume: int, arc_idx: int) -> bool:
    """检查指定情节单元的章纲是否已生成。"""
    from training.adaptive_builder import _list_novel_story_arcs
    arcs = _list_novel_story_arcs(ws, volume)
    for arc in arcs:
        if arc["idx"] == arc_idx:
            ch_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
            if not os.path.isdir(ch_dir):
                return False
            for ch in range(arc["start_ch"], arc["end_ch"] + 1):
                if os.path.exists(os.path.join(ch_dir, f"chapter_{ch:03d}.md")):
                    return True
            return False
    return False


def _conversation_path(root: Path, workspace: str, volume: int, arc_idx: int) -> Path:
    return (root / workspace / "file_system" / "chapter_outlines"
            / f"vol_{volume:02d}" / f"conversation_arc_{arc_idx}.json")


class ChapterOutlineConversation:
    def __init__(self, volume: int, arc_idx: int, path: Path):
        self.volume = volume
        self.arc_idx = arc_idx
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
                {"volume": self.volume, "arc_idx": self.arc_idx, "turns": self.turns,
                 "updated_at": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def history(self) -> dict[str, Any]:
        return {"volume": self.volume, "arc_idx": self.arc_idx, "turns": self.turns}

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


class ChapterOutlineChatManager:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)
        self._cache: dict[tuple[str, int, int], ChapterOutlineConversation] = {}
        self._jobs: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def get(self, workspace: str, volume: int, arc_idx: int) -> ChapterOutlineConversation:
        key = (workspace, volume, arc_idx)
        if key not in self._cache:
            self._cache[key] = ChapterOutlineConversation(volume, arc_idx, _conversation_path(self.root, workspace, volume, arc_idx))
        return self._cache[key]

    def history(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        ws = init_workspace(workspace)
        history = self.get(workspace, volume, arc_idx).history()
        history["has_outlines"] = _chapter_outlines_exist(ws, volume, arc_idx)
        return history

    def start_message(self, workspace: str, volume: int, arc_idx: int, message: str,
                      resume_incomplete: bool = False) -> dict[str, Any]:
        key = (workspace, volume, arc_idx)
        display_text = message.strip()
        if not display_text:
            raise ValueError("请输入内容后再发送。")
        with self._jobs_lock:
            current = self._jobs.get(key)
            if current and current["status"] in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前情节单元已有章纲任务正在进行。")
            pause_event = threading.Event()
            pause_event.set()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            job = {
                "id": uuid.uuid4().hex, "status": "running", "phase": "queued",
                "completed": 0, "total": 0, "progress_kind": "chapters",
                "message": "任务已创建，正在启动", "pause_event": pause_event,
                "stop_event": stop_event, "cancel_event": cancel_event,
                "prompt_history": [], "prompt_count": 0, "error": "",
            }
            self._jobs[key] = job
        conv = self.get(workspace, volume, arc_idx)
        if not resume_incomplete:
            conv.append_user(display_text)
            conv.save()

        def update(phase: str, completed: int, total: int, detail: str) -> None:
            with self._jobs_lock:
                active = self._jobs.get(key)
                if not active or active["id"] != job["id"]:
                    return
                active.update(
                    phase=phase, completed=completed, total=total, message=detail,
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
                from training.adaptive_builder import (
                    gen_chapter_outlines_for_arc, refine_chapter_outlines_serial,
                )
                initial = resume_incomplete or not _chapter_outlines_exist(ws, volume, arc_idx)
                if initial:
                    result = gen_chapter_outlines_for_arc(
                        ws, volume, arc_idx, progress_callback=update,
                        pause_event=pause_event, stop_event=stop_event,
                        cancel_event=cancel_event,
                    )
                    mode = "resume" if resume_incomplete else "initial"
                else:
                    with self._jobs_lock:
                        active = self._jobs.get(key)
                        if active and active["id"] == job["id"]:
                            active["progress_kind"] = "serial_chapter_refine"
                    result = refine_chapter_outlines_serial(
                        ws, volume, arc_idx, display_text, progress_callback=update,
                        pause_event=pause_event, stop_event=stop_event,
                        cancel_event=cancel_event,
                    )
                    mode = "refine"
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(str(result["error"]))
                if not result:
                    raise RuntimeError("未配置可用模型，请先在右上角配置大模型 API。")
                note = str(result.get("adjustment_note") or "").strip() or "章纲处理完成。"
                conv.append_assistant(note, result.get("artifacts") or [])
                conv.save()
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        stopped = bool(result.get("stopped"))
                        active.update(
                            status="stopped" if stopped else "completed",
                            phase="stopped" if stopped else "completed",
                            message=note, result={"mode": mode},
                        )
            except Exception as exc:
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        active.update(status="failed", phase="failed", message="生成失败", error=str(exc))
            finally:
                trace_context.__exit__(None, None, None)

        threading.Thread(
            target=worker, name=f"chapters-chat-{volume}-{arc_idx}", daemon=True,
        ).start()
        return self.job_status(workspace, volume, arc_idx)

    def job_status(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, volume, arc_idx))
            if job:
                return {
                    k: v for k, v in job.items()
                    if k not in {"pause_event", "stop_event", "cancel_event", "prompt_history"}
                }
        from training.adaptive_builder import chapter_outline_resume_status
        return {
            "status": "idle", "phase": "idle", "message": "",
            **chapter_outline_resume_status(init_workspace(workspace), volume, arc_idx),
        }

    def prompts(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, volume, arc_idx))
            return {
                "job_id": job.get("id") if job else None,
                "items": [dict(item) for item in (job or {}).get("prompt_history", [])],
            }

    def continue_incomplete(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        from training.adaptive_builder import chapter_outline_resume_status
        resume = chapter_outline_resume_status(init_workspace(workspace), volume, arc_idx)
        if not resume.get("can_resume"):
            raise ValueError("当前情节单元没有可继续的未完成章纲。")
        return self.start_message(
            workspace, volume, arc_idx, "继续生成未完成章纲", resume_incomplete=True,
        )

    def pause(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        key = (workspace, volume, arc_idx)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing"}:
                raise ValueError("当前没有可暂停的章纲任务。")
            job["pause_event"].clear()
            job["cancel_event"].set()
            job.update(status="pausing", message="正在暂停当前模型请求")
        return self.job_status(workspace, volume, arc_idx)

    def resume(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        key = (workspace, volume, arc_idx)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"paused", "pausing"}:
                raise ValueError("当前没有已暂停的章纲任务。")
            job["cancel_event"].clear()
            job["pause_event"].set()
            job.update(status="running", phase="generating", message="已继续生成")
        return self.job_status(workspace, volume, arc_idx)

    def stop(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        key = (workspace, volume, arc_idx)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing", "paused"}:
                raise ValueError("当前没有可结束的章纲任务。")
            job["stop_event"].set()
            job["cancel_event"].set()
            job["pause_event"].set()
            job.update(status="stopping", phase="stopping", message="正在结束本轮生成")
        return self.job_status(workspace, volume, arc_idx)

    def run_message(self, workspace: str, volume: int, arc_idx: int, message: str) -> dict[str, Any]:
        ws = init_workspace(workspace)
        conv = self.get(workspace, volume, arc_idx)
        display_text = message.strip()
        if not display_text:
            raise ValueError("请输入内容后再发送。")

        conv.append_user(display_text)
        from training.adaptive_builder import gen_chapter_outlines_for_arc, refine_chapter_outlines

        is_initial = not _chapter_outlines_exist(ws, volume, arc_idx)
        if is_initial:
            result = gen_chapter_outlines_for_arc(ws, volume, arc_idx)
            mode = "initial"
        else:
            result = refine_chapter_outlines(ws, volume, arc_idx, instruction=display_text)
            mode = "refine"
        if not result:
            raise RuntimeError("未配置可用模型，请先在右上角配置大模型 API。")

        note = str(result.get("adjustment_note") or "").strip()
        if not note:
            note = "已生成章纲。" if mode == "initial" else "已按指令调整。"
        artifacts = result.get("artifacts") or []
        conv.append_assistant(note, artifacts)
        conv.save()
        return {"mode": mode, "result": result, "conversation": conv.history()}

    def reset(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        """清空对话，并删除该情节单元的章纲及对应系统面板快照。"""
        key = (workspace, volume, arc_idx)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if job and job.get("status") in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前章纲仍在生成，请先结束任务再重置。")
            if job:
                job["prompt_history"] = []
                job["prompt_count"] = 0
                for field in ("current_prompt_id", "prompt_model", "prompt_created_at"):
                    job.pop(field, None)
        ws = init_workspace(workspace)
        from training.adaptive_builder import _list_novel_story_arcs
        arcs = _list_novel_story_arcs(ws, volume)
        target = None
        for arc in arcs:
            if arc["idx"] == arc_idx:
                target = arc
                break
        if target:
            ch_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
            panel_dir = os.path.join(ws.file_system, "system_panels", f"vol_{volume:02d}")
            for ch in range(target["start_ch"], target["end_ch"] + 1):
                for path in (
                    os.path.join(ch_dir, f"chapter_{ch:03d}.md"),
                    os.path.join(panel_dir, f"chapter_{ch:03d}.json"),
                ):
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass
            from training.adaptive_builder import clear_finalized_chapters
            clear_finalized_chapters(
                ws, "outlines", volume,
                range(target["start_ch"], target["end_ch"] + 1),
            )
        conv = self.get(workspace, volume, arc_idx)
        conv.clear()
        return {"reset": True, "conversation": conv.history()}

    def clear(self, workspace: str, volume: int, arc_idx: int) -> dict[str, Any]:
        conv = self.get(workspace, volume, arc_idx)
        conv.clear()
        return {"cleared": True, "conversation": conv.history()}
