"""全书设计 / 舞台设计的对话管理。

每个工作区 + 步骤（concept / stage）独立维护一段对话。每次输入都会基于当前
最新产物重新生成，历史对话仅作展示用途，不限制轮数、不压缩。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.workspace import init_workspace
from core.prompt_trace import capture_prompts


# 路由 3 关键词：匹配任一即走续写追加路径（仅 scope=stage 生效）
_EXTEND_KEYWORDS = ("续写", "新增", "继续添加", "往后加", "加舞台", "追加舞台", "下一个舞台", "新舞台")

_SCOPE_FILES = {
    "concept": ("worldview.md", "rough_outline.md", "stage_outline.md"),
    "stage": ("long_mainline.md", "stage_roadmap.md"),
}


def _read_text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _is_real_content(text: str) -> bool:
    """判断文件内容是否是真实设计，而非空值或模型未返回的占位符。"""
    if not text or not text.strip():
        return False
    t = text.strip()
    if "模型未返回" in t and "请重试或人工补充" in t:
        return False
    return True


def _design_files_exist(ws, scope: str) -> bool:
    base = os.path.join(ws.file_system, "story_design")
    if not all(_is_real_content(_read_text(os.path.join(base, name))) for name in _SCOPE_FILES.get(scope, ())):
        return False
    if scope == "stage":
        state_path = os.path.join(base, "design_state.json")
        try:
            design_state = json.loads(_read_text(state_path) or "{}")
        except json.JSONDecodeError:
            design_state = {}
        if int(design_state.get("stage_pipeline_version") or 0) != 2:
            return False
        stage_outline = _read_text(os.path.join(base, "stage_outline.md"))
        stage_roadmap = _read_text(os.path.join(base, "stage_roadmap.md"))
        expected = sorted({
            int(value) for value in re.findall(
                r"^#{1,6}\s*(?:第\s*)?阶段\s*0*(\d+)\b",
                stage_outline, re.IGNORECASE | re.MULTILINE,
            )
        })
        generated = [
            int(value) for value in re.findall(
                r"^#{1,6}\s*(?:舞台|stage)\s*0*(\d+)\b",
                stage_roadmap, re.IGNORECASE | re.MULTILINE,
            )
        ]
        # 中途结束留下的是有效断点，不应被当成完整舞台设计后进入微调路径。
        if not expected or generated != list(range(1, len(expected) + 1)):
            return False
    return True


def _design_dir(ws) -> str:
    return os.path.join(ws.file_system, "story_design")


def _clear_system_panel_artifacts(ws) -> None:
    """清理依赖全书/舞台设计生成的系统面板定义与章节快照。"""
    try:
        os.remove(os.path.join(ws.file_system, "mechanics", "system_panel.json"))
    except FileNotFoundError:
        pass
    snapshots_dir = os.path.join(ws.file_system, "system_panels")
    if os.path.isdir(snapshots_dir):
        shutil.rmtree(snapshots_dir)


def _stage_resume_status(ws) -> dict[str, Any]:
    """根据已落盘的连续舞台判断是否存在可恢复断点。"""
    base = _design_dir(ws)
    stage_outline = _read_text(os.path.join(base, "stage_outline.md"))
    stage_roadmap = _read_text(os.path.join(base, "stage_roadmap.md"))
    expected = len({
        int(value) for value in re.findall(
            r"^#{1,6}\s*(?:第\s*)?阶段\s*0*(\d+)\b",
            stage_outline, re.IGNORECASE | re.MULTILINE,
        )
    })
    generated = [
        int(value) for value in re.findall(
            r"^#{1,6}\s*(?:舞台|stage)\s*0*(\d+)\b",
            stage_roadmap, re.IGNORECASE | re.MULTILINE,
        )
    ]
    completed = 0
    for number in generated:
        if number != completed + 1:
            break
        completed += 1
    return {
        "can_resume": expected > 0 and completed < expected,
        "completed": completed,
        "total": expected,
        "next_stage": completed + 1 if expected > completed else None,
    }


class DesignConversation:
    def __init__(self, scope: str, path: Path):
        self.scope = scope
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
        if not isinstance(data, dict):
            return
        self.turns = [t for t in data.get("turns", []) if isinstance(t, dict)]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"scope": self.scope, "turns": self.turns,
                 "updated_at": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def history(self) -> dict[str, Any]:
        return {"scope": self.scope, "turns": self.turns}

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


# 生成产物 → 审阅路径 + 展示标签
_RESULT_ARTIFACTS = {
    "concept": {
        "worldview": ("file_system/story_design/worldview.md", "世界观"),
        "rough_outline": ("file_system/story_design/rough_outline.md", "粗略大纲"),
        "stage_outline": ("file_system/story_design/stage_outline.md", "阶段粗纲"),
    },
    "stage": {
        "long_mainline": ("file_system/story_design/long_mainline.md", "长线主线"),
        "stage_roadmap": ("file_system/story_design/stage_roadmap.md", "舞台路线图"),
        "name_synopsis": ("file_system/novel_name_synopsis.md", "书名与简介"),
    },
}


def _extract_artifacts(scope: str, result: dict) -> list:
    """从生成/微调结果里提取本次保存的产物（路径 + 标签）。"""
    mapping = _RESULT_ARTIFACTS.get(scope, {})
    artifacts = []
    for key, (path, label) in mapping.items():
        if isinstance(result, dict) and result.get(key):
            artifacts.append({"path": path, "label": label})
    return artifacts


def _conversation_path(root: Path, workspace: str, scope: str) -> Path:
    return root / workspace / "file_system" / "story_design" / "conversation" / f"{scope}.json"


def _is_extend_intent(message: str) -> bool:
    return any(kw in message for kw in _EXTEND_KEYWORDS)


class DesignChatManager:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)
        self._cache: dict[tuple[str, str], DesignConversation] = {}
        self._jobs: dict[tuple[str, str], dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def get(self, workspace: str, scope: str) -> DesignConversation:
        key = (workspace, scope)
        if key not in self._cache:
            self._cache[key] = DesignConversation(scope, _conversation_path(self.root, workspace, scope))
        return self._cache[key]

    def run_message(
        self, workspace: str, scope: str, message: str, attachments=None,
        use_new_reference=False, sync_updated_design=False,
        progress_callback=None, pause_event=None, stop_event=None,
        cancel_event=None,
    ) -> dict[str, Any]:
        """统一对话入口：首条消息生成初版，后续消息在上一版基础上增量微调。

        attachments 为 [{name, content}, ...]，内容会并入给模型的指令，
        但对话历史只记录精简展示文本。
        """
        ws = init_workspace(workspace)
        conv = self.get(workspace, scope)
        attachments = attachments or []

        combined_parts = [message.strip()]
        for att in attachments:
            name = str(att.get("name") or "附件")
            content = str(att.get("content") or "").strip()
            if content:
                combined_parts.append(f"\n\n【参考文件：{name}】\n{content}")
        combined_for_llm = "\n".join(combined_parts).strip()
        if scope == "concept" and use_new_reference and not combined_for_llm:
            combined_for_llm = "请读取新增拆解章节，只同步阶段粗纲的最后一个阶段或追加新阶段。"
        if scope == "stage" and sync_updated_design and not combined_for_llm:
            combined_for_llm = "请同步阶段粗纲的末尾变化，只调整最后一个舞台或追加新舞台。"

        if attachments:
            names = "、".join(str(a.get("name") or "附件") for a in attachments)
            display_text = f"{message.strip()}\n（附件：{names}）" if message.strip() else f"（附件：{names}）"
        else:
            display_text = message.strip()
        if not display_text and scope == "stage" and sync_updated_design:
            display_text = "同步更新后续舞台"
        elif not display_text and scope == "concept" and use_new_reference:
            display_text = "同步新增拆解到阶段粗纲"
        if not combined_for_llm:
            raise ValueError("请输入灵感或上传文件后再发送。")

        conv.append_user(display_text)
        from training.adaptive_builder import (
            gen_design_concept, gen_stage_design, refine_design_concept, refine_stage_design,
            extend_stage_design, sync_stage_outline_from_new_reference,
        )
        from core.llm_provider import LLMCallCancelled

        progress_state = {"completed": 0, "total": 1}

        def report(phase: str, completed: int, total: int, detail: str) -> None:
            progress_state.update(completed=int(completed), total=max(1, int(total)))
            if progress_callback:
                progress_callback(phase, completed, total, detail)

        def stopped_stage_result() -> dict[str, Any]:
            base = _design_dir(ws)
            return {
                "long_mainline": _read_text(os.path.join(base, "long_mainline.md")),
                "stage_roadmap": _read_text(os.path.join(base, "stage_roadmap.md")),
                "adjustment_note": "已结束本轮舞台设计，已写入的长线主线和舞台均已保留。",
                "stopped": True,
            }

        def run_stage_operation(operation):
            """取消当前请求后停在断点；继续时重新执行尚未落盘的这一步。"""
            while True:
                if stop_event is not None and stop_event.is_set():
                    return stopped_stage_result()
                if pause_event is not None and not pause_event.is_set():
                    report(
                        "paused", progress_state["completed"], progress_state["total"],
                        "舞台设计已暂停；点击继续后从当前断点接着生成",
                    )
                    pause_event.wait()
                    if stop_event is not None and stop_event.is_set():
                        return stopped_stage_result()
                    if cancel_event is not None:
                        cancel_event.clear()
                try:
                    result = operation()
                except LLMCallCancelled:
                    if stop_event is not None and stop_event.is_set():
                        return stopped_stage_result()
                    report(
                        "paused", progress_state["completed"], progress_state["total"],
                        "当前模型请求已暂停；点击继续后重新生成当前舞台",
                    )
                    if pause_event is not None:
                        pause_event.wait()
                    if stop_event is not None and stop_event.is_set():
                        return stopped_stage_result()
                    if cancel_event is not None:
                        cancel_event.clear()
                    continue
                if stop_event is not None and stop_event.is_set():
                    stopped = stopped_stage_result()
                    # 请求已经返回且产物已写盘时，保留刚完成的写入结果。
                    if isinstance(result, dict):
                        stopped.update({k: v for k, v in result.items() if v})
                        stopped["stopped"] = True
                        stopped["adjustment_note"] = "已结束本轮舞台设计，已完成内容均已保留。"
                    return stopped
                return result

        is_initial = not _design_files_exist(ws, scope)
        is_concept_stage_sync = scope == "concept" and not is_initial and bool(use_new_reference)
        is_sync_extend = scope == "stage" and not is_initial and bool(sync_updated_design)
        is_extend = scope == "stage" and not is_initial and _is_extend_intent(combined_for_llm)
        if is_initial:
            if scope == "concept":
                result = gen_design_concept(
                    ws, creative_direction=combined_for_llm,
                    progress_callback=progress_callback,
                )
            else:
                result = run_stage_operation(
                    lambda: gen_stage_design(
                        ws, creative_direction=combined_for_llm,
                        progress_callback=report, cancel_event=cancel_event,
                    )
                )
            mode = "initial"
        elif is_concept_stage_sync:
            if progress_callback:
                progress_callback("generating", 0, 1, "正在同步新增拆解到阶段粗纲")
            result = sync_stage_outline_from_new_reference(
                ws, instruction=combined_for_llm,
            )
            if progress_callback:
                progress_callback("completed", 1, 1, "阶段粗纲已同步")
            mode = "concept_stage_sync"
        elif is_sync_extend or is_extend:
            if progress_callback:
                progress_callback("generating", 0, 1, "正在更新舞台路线图")
            result = run_stage_operation(
                lambda: extend_stage_design(
                    ws, instruction=combined_for_llm,
                    sync_updated_design=is_sync_extend,
                    cancel_event=cancel_event,
                )
            )
            if progress_callback:
                progress_callback("completed", 1, 1, "舞台路线图已更新")
            mode = "sync_extend" if is_sync_extend else "extend"
        else:
            if progress_callback and scope == "concept":
                progress_callback("generating", 0, 1, "正在根据指令调整设计")
            if scope == "concept":
                result = refine_design_concept(
                    ws, instruction=combined_for_llm, use_new_reference=False,
                )
            else:
                result = run_stage_operation(
                    lambda: refine_stage_design(
                        ws, instruction=combined_for_llm,
                        cancel_event=cancel_event,
                        progress_callback=report,
                        pause_event=pause_event,
                        stop_event=stop_event,
                    )
                )
            if progress_callback and scope == "concept":
                progress_callback("completed", 1, 1, "设计内容已更新")
            mode = "refine"
        if not result:
            raise RuntimeError("未配置可用模型，请先在右上角配置大模型 API。")

        note = str(result.get("adjustment_note") or "").strip()
        if not note:
            note = ("已生成初版，可继续输入调整要求。" if mode == "initial"
                    else "已根据新增拆解内容同步末尾阶段粗纲。" if mode == "concept_stage_sync"
                    else "已同步新版全书设计并追加后续舞台。" if mode == "sync_extend"
                    else "已追加后续舞台。" if mode == "extend" else "已按指令更新。")
        artifacts = _extract_artifacts(scope, result)
        conv.append_assistant(note, artifacts)
        conv.save()

        return {"mode": mode, "result": result, "conversation": conv.history()}

    def start_message(
        self, workspace: str, scope: str, message: str, attachments=None,
        use_new_reference=False, sync_updated_design=False,
    ) -> dict[str, Any]:
        """在后台执行设计对话，供前端轮询三段式全书设计进度。"""
        if scope not in _SCOPE_FILES:
            raise ValueError("设计步骤只能是 concept 或 stage。")
        key = (workspace, scope)
        ws = init_workspace(workspace)
        is_initial = not _design_files_exist(ws, scope)
        total = 3 if scope == "concept" and is_initial else 1
        with self._jobs_lock:
            current = self._jobs.get(key)
            if current and current.get("status") in {"queued", "running", "pausing", "paused", "stopping"}:
                raise ValueError("当前设计步骤已有生成任务正在进行。")
            pause_event = threading.Event()
            pause_event.set()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            job = {
                "id": uuid.uuid4().hex,
                "status": "running",
                "phase": "queued",
                "completed": 0,
                "total": total,
                "progress_kind": "design_concept" if scope == "concept" else "stage_design",
                "message": "任务已创建，正在启动",
                "pause_event": pause_event,
                "stop_event": stop_event,
                "cancel_event": cancel_event,
                "prompt_history": [],
                "prompt_count": 0,
                "error": "",
            }
            self._jobs[key] = job

        def update(phase: str, completed: int, callback_total: int, detail: str) -> None:
            with self._jobs_lock:
                active = self._jobs.get(key)
                if not active or active.get("id") != job["id"]:
                    return
                active.update(
                    phase=phase,
                    completed=int(completed),
                    total=max(1, int(callback_total)),
                    message=detail,
                )

        def worker() -> None:
            def trace_prompt(event: dict) -> None:
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if not active or active.get("id") != job["id"]:
                        return
                    history = active.setdefault("prompt_history", [])
                    history.append(event)
                    del history[:-50]
                    active.update(
                        prompt_count=len(history),
                        current_prompt_id=event.get("id"),
                        prompt_model=event.get("model", ""),
                        prompt_created_at=event.get("created_at", ""),
                    )
            trace_context = capture_prompts(trace_prompt)
            trace_context.__enter__()
            try:
                response = self.run_message(
                    workspace, scope, message, attachments,
                    use_new_reference=use_new_reference,
                    sync_updated_design=sync_updated_design,
                    progress_callback=update,
                    pause_event=pause_event,
                    stop_event=stop_event,
                    cancel_event=cancel_event,
                )
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active.get("id") == job["id"]:
                        stopped = bool((response.get("result") or {}).get("stopped"))
                        active.update(
                            status="stopped" if stopped else "completed",
                            phase="stopped" if stopped else "completed",
                            completed=(
                                active.get("completed", 0) if stopped
                                else active.get("total", total)
                            ),
                            message=(
                                "已结束本轮舞台设计" if stopped else
                                "全书设计已生成" if scope == "concept" else "舞台设计已生成"
                            ),
                            result={"mode": response.get("mode")},
                        )
            except Exception as exc:
                with self._jobs_lock:
                    active = self._jobs.get(key)
                    if active and active.get("id") == job["id"]:
                        active.update(
                            status="failed", phase="failed",
                            message="生成失败", error=str(exc),
                        )
            finally:
                trace_context.__exit__(None, None, None)

        threading.Thread(
            target=worker, name=f"design-chat-{scope}", daemon=True,
        ).start()
        return self.job_status(workspace, scope)

    def job_status(self, workspace: str, scope: str) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, scope))
            if not job:
                status = {
                    "status": "idle", "phase": "idle", "completed": 0,
                    "total": 0, "message": "", "error": "",
                }
            else:
                status = {
                key: value for key, value in job.items()
                if key not in {"pause_event", "stop_event", "cancel_event", "prompt_history"}
                }
        if scope == "stage" and status.get("status") in {"idle", "stopped", "failed"}:
            status.update(_stage_resume_status(init_workspace(workspace)))
        return status

    def prompts(self, workspace: str, scope: str) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get((workspace, scope))
            if not job:
                return {"items": []}
            return {
                "job_id": job.get("id"),
                "items": [dict(item) for item in job.get("prompt_history", [])],
            }

    def continue_incomplete(self, workspace: str, scope: str) -> dict[str, Any]:
        if scope != "stage":
            raise ValueError("当前仅舞台设计支持断点继续。")
        resume = _stage_resume_status(init_workspace(workspace))
        if not resume.get("can_resume"):
            raise ValueError("当前没有可继续的未完成舞台。")
        return self.start_message(
            workspace, scope, "继续生成未完成的舞台设计",
        )

    def pause(self, workspace: str, scope: str) -> dict[str, Any]:
        if scope != "stage":
            raise ValueError("当前仅舞台设计支持暂停。")
        key = (workspace, scope)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing"}:
                raise ValueError("当前没有可暂停的舞台设计任务。")
            job["pause_event"].clear()
            job["cancel_event"].set()
            job.update(status="pausing", phase="pausing", message="正在暂停当前模型请求")
        return self.job_status(workspace, scope)

    def resume(self, workspace: str, scope: str) -> dict[str, Any]:
        if scope != "stage":
            raise ValueError("当前仅舞台设计支持继续。")
        key = (workspace, scope)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"paused", "pausing"}:
                raise ValueError("当前没有已暂停的舞台设计任务。")
            job["cancel_event"].clear()
            job["pause_event"].set()
            job.update(status="running", phase="generating", message="已继续生成舞台设计")
        return self.job_status(workspace, scope)

    def stop(self, workspace: str, scope: str) -> dict[str, Any]:
        if scope != "stage":
            raise ValueError("当前仅舞台设计支持结束。")
        key = (workspace, scope)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if not job or job["status"] not in {"running", "pausing", "paused"}:
                raise ValueError("当前没有可结束的舞台设计任务。")
            job["stop_event"].set()
            job["cancel_event"].set()
            job["pause_event"].set()
            job.update(status="stopping", phase="stopping", message="正在结束本轮舞台设计")
        return self.job_status(workspace, scope)

    def reset(self, workspace: str, scope: str) -> dict[str, Any]:
        """清空对话并删除该步骤的设计文件，使下一条消息重新作为初版生成。"""
        key = (workspace, scope)
        with self._jobs_lock:
            job = self._jobs.get(key)
            if job and job.get("status") in {"queued", "running", "pausing", "paused", "stopping"}:
                raise ValueError("当前设计任务仍在执行，请先结束任务再重置。")
            if job:
                job["prompt_history"] = []
                job["prompt_count"] = 0
                for field in ("current_prompt_id", "prompt_model", "prompt_created_at"):
                    job.pop(field, None)
        ws = init_workspace(workspace)
        for name in _SCOPE_FILES.get(scope, ()):
            try:
                os.remove(os.path.join(_design_dir(ws), name))
            except FileNotFoundError:
                pass
        if scope == "stage":
            # 书名与简介由粗略大纲 + 长线主线派生；舞台设计重置后旧版本已失去依据。
            try:
                os.remove(os.path.join(ws.file_system, "novel_name_synopsis.md"))
            except FileNotFoundError:
                pass
        if scope in {"concept", "stage"}:
            # 系统面板由当前全书设计和舞台设计派生。上游重置后，旧定义和所有
            # 章节状态都不再可信；下次生成章纲时应重新自动判断并初始化。
            _clear_system_panel_artifacts(ws)
        state_files = (
            ("chapter_usage_state.json", "design_state.json")
            if scope == "concept" else ("arc_usage_state.json",)
        )
        for name in state_files:
            try:
                os.remove(os.path.join(_design_dir(ws), name))
            except FileNotFoundError:
                pass
        conv = self.get(workspace, scope)
        conv.clear()
        return {"reset": True, "conversation": conv.history()}

    def clear(self, workspace: str, scope: str) -> dict[str, Any]:
        conv = self.get(workspace, scope)
        conv.clear()
        return {"cleared": True, "conversation": conv.history()}
