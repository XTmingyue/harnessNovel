"""按故事情节串行生成正文的异步对话管理。"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.llm_provider import LLMCallCancelled
from core.prompt_trace import capture_prompts
from core.workspace import init_workspace


def _conversation_path(root: Path, workspace: str, volume: int, arc_idx: int) -> Path:
    return root / workspace / "file_system" / "chapters" / f"vol_{volume:02d}" / f"conversation_arc_{arc_idx}.json"


class DraftConversation:
    def __init__(self, volume: int, arc_idx: int, path: Path):
        self.volume, self.arc_idx, self.path = volume, arc_idx, path
        self.turns: list[dict[str, Any]] = []
        self.load()

    def load(self):
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.turns = [item for item in data.get("turns", []) if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, AttributeError):
            self.turns = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "volume": self.volume, "arc_idx": self.arc_idx, "turns": self.turns,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def history(self):
        return {"volume": self.volume, "arc_idx": self.arc_idx, "turns": self.turns}


class DraftChatManager:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)
        self._cache: dict[tuple[str, int, int], DraftConversation] = {}
        self._jobs: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, workspace, volume, arc_idx):
        key = (workspace, volume, arc_idx)
        if key not in self._cache:
            self._cache[key] = DraftConversation(volume, arc_idx, _conversation_path(self.root, workspace, volume, arc_idx))
        return self._cache[key]

    def history(self, workspace, volume, arc_idx):
        history = self.get(workspace, volume, arc_idx).history()
        history["writing_guide"] = self.writing_guide_status(workspace)
        from training.adaptive_builder import chapter_draft_resume_status
        status = chapter_draft_resume_status(init_workspace(workspace), volume, arc_idx)
        history["has_drafts"] = bool(status.get("completed"))
        return history

    def writing_guide_status(self, workspace):
        ws = init_workspace(workspace)
        custom = Path(ws.file_system) / "writing" / "system_prompt.md"
        return {
            "custom": custom.is_file() and bool(custom.read_text(encoding="utf-8").strip()),
            "name": "自定义生文规范" if custom.is_file() else "项目默认 system_prompt.md",
        }

    def save_writing_guide(self, workspace, content, source_name):
        if not content.strip():
            raise ValueError("生文规范文件为空。")
        ws = init_workspace(workspace)
        target = Path(ws.file_system) / "writing" / "system_prompt.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + "\n", encoding="utf-8")
        meta = target.parent / "guide_meta.json"
        meta.write_text(json.dumps({"source_name": source_name, "updated_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.writing_guide_status(workspace)

    def reset_writing_guide(self, workspace):
        ws = init_workspace(workspace)
        writing_dir = Path(ws.file_system) / "writing"
        (writing_dir / "system_prompt.md").unlink(missing_ok=True)
        (writing_dir / "guide_meta.json").unlink(missing_ok=True)
        return self.writing_guide_status(workspace)

    def start_message(
        self, workspace, volume, arc_idx, message, resume_incomplete=False,
        humanize=True,
    ):
        display = message.strip()
        if not display:
            raise ValueError("请输入内容后再发送。")
        key = (workspace, volume, arc_idx)
        with self._lock:
            old = self._jobs.get(key)
            if old and old["status"] in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前故事情节已有正文任务正在进行。")
            pause, stop, cancel = threading.Event(), threading.Event(), threading.Event()
            pause.set()
            job = {
                "id": uuid.uuid4().hex, "status": "running", "phase": "queued",
                "completed": 0, "total": 0, "progress_kind": "drafts",
                "message": "任务已创建，正在启动", "pause_event": pause,
                "stop_event": stop, "cancel_event": cancel,
                "prompt_history": [], "prompt_count": 0, "error": "",
            }
            self._jobs[key] = job
        conv = self.get(workspace, volume, arc_idx)
        if not resume_incomplete:
            conv.turns.append({"role": "user", "content": display, "at": datetime.now().isoformat(timespec="seconds")})
            conv.save()

        def update(phase, completed, total, detail):
            with self._lock:
                active = self._jobs.get(key)
                if active and active["id"] == job["id"]:
                    active.update(phase=phase, completed=completed, total=total, message=detail,
                                  status="paused" if phase == "paused" else active["status"])

        def worker():
            def trace_prompt(event: dict) -> None:
                with self._lock:
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
                from training.adaptive_builder import (
                    _finalized_chapter_boundary, _list_novel_story_arcs, chapter_draft_resume_status,
                    gen_serial_chapters, route_chapter_draft_refinement,
                )
                ws = init_workspace(workspace)
                arc = next((item for item in _list_novel_story_arcs(ws, volume) if item["idx"] == arc_idx), None)
                if not arc:
                    raise ValueError("未找到故事情节单元。")
                resume = chapter_draft_resume_status(ws, volume, arc_idx)
                any_existing = resume["completed"] > 0
                if resume_incomplete or not any_existing:
                    start = resume.get("next_chapter") if resume_incomplete else arc["start_ch"]
                    mode, instruction = ("resume" if resume_incomplete else "initial"), display
                else:
                    with self._lock:
                        self._jobs[key]["progress_kind"] = "serial_draft_refine"
                    update("routing", 0, resume["total"], "正在判断最早受影响章节")
                    while True:
                        try:
                            start, refinement_mode, reason = route_chapter_draft_refinement(
                                ws, volume, arc_idx, display, cancel,
                            )
                            break
                        except LLMCallCancelled:
                            if stop.is_set():
                                start = None
                                break
                            update("paused", 0, resume["total"], "范围分析已暂停；继续后重新分析")
                            pause.wait()
                            cancel.clear()
                    if start is None:
                        result = {"stopped": True, "artifacts": [], "adjustment_note": "已结束本轮正文调整。"}
                    else:
                        start = max(
                            start,
                            _finalized_chapter_boundary(
                                ws, "drafts", volume, arc["start_ch"], arc["end_ch"],
                            ) + 1,
                        )
                        mode, instruction = "refine", display
                if start is not None:
                    result = gen_serial_chapters(
                        ws, volume=volume, start_chapter=start, end_chapter=arc["end_ch"],
                        max_chapters=arc["end_ch"] - start + 1,
                        humanize=bool(humanize),
                        regenerate_existing=(mode == "refine"),
                        refinement_mode=(
                            refinement_mode if mode == "refine" else "regenerate"
                        ),
                        writing_instruction=instruction,
                        progress_callback=update, pause_event=pause, stop_event=stop, cancel_event=cancel,
                    )
                if not result:
                    raise RuntimeError("没有可生成的正文，请确认所选范围已有逐章章纲。")
                note = str(result.get("adjustment_note") or "正文处理完成。")
                conv.turns.append({"role": "assistant", "content": note, "artifacts": result.get("artifacts") or [], "at": datetime.now().isoformat(timespec="seconds")})
                conv.save()
                with self._lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        stopped = bool(result.get("stopped"))
                        active.update(status="stopped" if stopped else "completed", phase="stopped" if stopped else "completed", message=note)
            except Exception as exc:
                with self._lock:
                    active = self._jobs.get(key)
                    if active and active["id"] == job["id"]:
                        active.update(status="failed", phase="failed", message="生成失败", error=str(exc))
            finally:
                trace_context.__exit__(None, None, None)

        threading.Thread(target=worker, name=f"draft-chat-{volume}-{arc_idx}", daemon=True).start()
        return self.job_status(workspace, volume, arc_idx)

    def job_status(self, workspace, volume, arc_idx):
        with self._lock:
            job = self._jobs.get((workspace, volume, arc_idx))
            if job:
                return {key: value for key, value in job.items() if key not in {"pause_event", "stop_event", "cancel_event", "prompt_history"}}
        from training.adaptive_builder import chapter_draft_resume_status
        return {"status": "idle", "phase": "idle", "message": "", **chapter_draft_resume_status(init_workspace(workspace), volume, arc_idx)}

    def prompts(self, workspace, volume, arc_idx):
        with self._lock:
            job = self._jobs.get((workspace, volume, arc_idx))
            return {
                "job_id": job.get("id") if job else None,
                "items": [dict(item) for item in (job or {}).get("prompt_history", [])],
            }

    def _control(self, workspace, volume, arc_idx, action):
        key = (workspace, volume, arc_idx)
        with self._lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing", "paused"}:
                raise ValueError("当前没有可控制的正文任务。")
            if action == "pause":
                job["pause_event"].clear(); job["cancel_event"].set()
                job.update(status="pausing", message="正在暂停当前模型请求")
            elif action == "resume":
                job["cancel_event"].clear(); job["pause_event"].set()
                job.update(status="running", phase="generating", message="已继续生成")
            else:
                job["stop_event"].set(); job["cancel_event"].set(); job["pause_event"].set()
                job.update(status="stopping", phase="stopping", message="正在结束本轮生成")
        return self.job_status(workspace, volume, arc_idx)

    def pause(self, *args): return self._control(*args, "pause")
    def resume(self, *args): return self._control(*args, "resume")
    def stop(self, *args): return self._control(*args, "stop")

    def continue_incomplete(self, workspace, volume, arc_idx):
        from training.adaptive_builder import chapter_draft_resume_status
        if not chapter_draft_resume_status(init_workspace(workspace), volume, arc_idx).get("can_resume"):
            raise ValueError("当前故事情节没有可继续的未完成正文。")
        return self.start_message(workspace, volume, arc_idx, "继续生成未完成正文", True)

    def clear(self, workspace, volume, arc_idx):
        conv = self.get(workspace, volume, arc_idx)
        conv.turns = []; conv.save()
        return {"cleared": True, "conversation": conv.history()}

    def reset(self, workspace, volume, arc_idx):
        """删除当前情节单元的正式正文、精修前快照、历史版本和最终版标记。"""
        key = (workspace, volume, arc_idx)
        with self._lock:
            job = self._jobs.get(key)
            if job and job["status"] in {"running", "pausing", "paused", "stopping"}:
                raise ValueError("当前故事情节正在生成正文，请先结束任务再重置。")
            if job:
                job["prompt_history"] = []
                job["prompt_count"] = 0
                for field in ("current_prompt_id", "prompt_model", "prompt_created_at"):
                    job.pop(field, None)

        from training.adaptive_builder import (
            _list_novel_story_arcs,
            clear_finalized_chapters,
        )
        ws = init_workspace(workspace)
        arc = next(
            (item for item in _list_novel_story_arcs(ws, volume) if item["idx"] == arc_idx),
            None,
        )
        if not arc:
            raise ValueError("未找到当前故事情节单元。")

        chapters = list(range(arc["start_ch"], arc["end_ch"] + 1))
        refined_dir = Path(ws.file_system) / "chapters" / f"vol_{volume:02d}"
        refined_versions = refined_dir / "versions"
        raw_dir = Path(ws.file_system) / "drafts" / f"vol_{volume:02d}" / "raw_chapters"
        raw_versions = raw_dir / "versions"
        deleted = 0
        for chapter in chapters:
            targets = [
                refined_dir / f"{chapter:03d}_第{chapter}章.md",
                raw_dir / f"{chapter:03d}_第{chapter}章.raw.md",
            ]
            targets.extend(refined_versions.glob(f"{chapter:03d}_第{chapter}章.md_*"))
            targets.extend(raw_versions.glob(f"{chapter:03d}_第{chapter}章_*.raw.md"))
            for path in targets:
                if path.is_file():
                    path.unlink()
                    deleted += 1

        clear_finalized_chapters(ws, "drafts", volume, chapters)
        conv = self.get(workspace, volume, arc_idx)
        conv.turns = []
        conv.save()
        with self._lock:
            self._jobs.pop(key, None)
        return {
            "reset": True,
            "deleted": deleted,
            "start_chapter": arc["start_ch"],
            "end_chapter": arc["end_ch"],
            "conversation": conv.history(),
        }
