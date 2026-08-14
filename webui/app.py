"""HarnessNovel 本地 Web 工作台的 FastAPI 应用。"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from webui.task_runner import (
    EDITABLE_EXTENSIONS,
    TASK_LABELS,
    TaskManager,
    UploadStore,
    WorkspaceStore,
    require_workspace_name,
)
from webui.design_chat import DesignChatManager
from webui.arc_chat import ArcsChatManager
from webui.chapter_chat import ChapterOutlineChatManager
from webui.draft_chat import DraftChatManager
from core.workspace import init_workspace


APP_HOME = Path.home() / ".harnessNovel"
WEB_HOME = APP_HOME / "web"
WEB_SETTINGS_PATH = WEB_HOME / "settings.json"
CONFIG_PATH = APP_HOME / ".env"
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
UPLOAD_EXTENSIONS = EDITABLE_EXTENSIONS | {".jsonl"}
CONFIG_KEYS = [
    "DATA_BUILDER_MODEL",
    "DATA_BUILDER_BASE_URL",
    "DATA_BUILDER_API_KEY",
    "ADAPTIVE_BUILDER_MODEL",
    "ADAPTIVE_BUILDER_BASE_URL",
    "ADAPTIVE_BUILDER_API_KEY",
    "ADAPTIVE_BUILDER_LITE_MODEL",
    "ADAPTIVE_BUILDER_LITE_BASE_URL",
    "ADAPTIVE_BUILDER_LITE_API_KEY",
]
CONFIG_GROUPS = {
    "data_builder": ("参考拆解模型", "DATA_BUILDER"),
    "adaptive_builder": ("全书设计与舞台设计模型（推荐 Pro）", "ADAPTIVE_BUILDER"),
    "adaptive_builder_lite": ("故事情节、章纲与正文模型（推荐 Flash）", "ADAPTIVE_BUILDER_LITE"),
}


def _effective_config_path() -> Path:
    """Web 配置始终使用 HarnessNovel 的全局配置文件。"""
    return CONFIG_PATH


def _safe_filename(name: str | None) -> str:
    value = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name or "upload.txt", flags=re.UNICODE)
    return value.strip("._") or "upload.txt"


def _default_workspace_root() -> Path:
    configured = os.getenv("HARNESS_NOVEL_HOME")
    if configured:
        return Path(configured).expanduser()
    documents_root = Path.home() / "Documents" / "my-novels"
    if documents_root.exists():
        return documents_root
    return Path.cwd() / "my-novels"


def _load_web_settings() -> dict[str, Any]:
    if not WEB_SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(WEB_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_web_settings(data: dict[str, Any]) -> None:
    WEB_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_env() -> tuple[list[str], dict[str, str]]:
    config_path = _effective_config_path()
    if not config_path.is_file():
        return [], {}
    lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def _config_for_client() -> dict[str, Any]:
    _, values = _read_env()
    groups = {}
    for group_id, (label, prefix) in CONFIG_GROUPS.items():
        groups[group_id] = {
            "label": label,
            "model": values.get(f"{prefix}_MODEL", ""),
            "base_url": values.get(f"{prefix}_BASE_URL", ""),
            "api_key_configured": bool(values.get(f"{prefix}_API_KEY", "")),
        }
    return {"config_path": str(_effective_config_path()), "groups": groups}


def _update_env(updates: dict[str, str]) -> None:
    config_path = _effective_config_path()
    lines, _ = _read_env()
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# Updated by HarnessNovel Web")
        for key in CONFIG_KEYS:
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


class WebRuntime:
    def __init__(self, workspace_root: str | None):
        saved = _load_web_settings()
        root = workspace_root or saved.get("workspace_root") or _default_workspace_root()
        self.store = WorkspaceStore(root)
        os.environ["HARNESS_NOVEL_HOME"] = str(self.store.root)
        self.uploads = UploadStore(WEB_HOME / "uploads")
        self.tasks = TaskManager(self.store, WEB_HOME / "tasks", self.uploads)
        self.design_chat = DesignChatManager(root)
        self.arcs_chat = ArcsChatManager(root)
        self.chapters_chat = ChapterOutlineChatManager(root)
        self.draft_chat = DraftChatManager(root)
        self._persist_root()

    def set_workspace_root(self, root: str) -> None:
        if any(task["status"] in {"queued", "running"} for task in self.tasks.list()):
            raise ValueError("有任务正在执行，结束后才能切换工作区根目录。")
        self.store.set_root(root)
        os.environ["HARNESS_NOVEL_HOME"] = str(self.store.root)
        self.design_chat.root = Path(root)
        self.arcs_chat.root = Path(root)
        self.chapters_chat.root = Path(root)
        self.draft_chat.root = Path(root)
        self._persist_root()

    def _persist_root(self) -> None:
        _save_web_settings({"workspace_root": str(self.store.root)})

    @staticmethod
    def _chat_manager_busy(manager: Any, workspace: str) -> bool:
        lock = getattr(manager, "_jobs_lock", None) or getattr(manager, "_lock", None)
        jobs = getattr(manager, "_jobs", {})
        if lock is None:
            return False
        with lock:
            return any(
                isinstance(key, tuple)
                and key
                and key[0] == workspace
                and job.get("status") in {"running", "pausing", "paused", "stopping"}
                for key, job in jobs.items()
            )

    @staticmethod
    def _forget_chat_workspace(manager: Any, workspace: str) -> None:
        lock = getattr(manager, "_jobs_lock", None) or getattr(manager, "_lock", None)
        if lock is None:
            return
        with lock:
            for attr in ("_jobs", "_cache"):
                values = getattr(manager, attr, {})
                keys = [
                    key for key in values
                    if isinstance(key, tuple) and key and key[0] == workspace
                ]
                for key in keys:
                    values.pop(key, None)

    def delete_workspace(self, name: str) -> dict[str, Any]:
        name = require_workspace_name(name)
        managers = (self.design_chat, self.arcs_chat, self.chapters_chat, self.draft_chat)
        if any(self._chat_manager_busy(manager, name) for manager in managers):
            raise ValueError("该工作区仍有内容生成任务正在执行，请先结束任务再删除。")
        self.tasks.begin_workspace_delete(name)
        try:
            result = self.store.delete_workspace(name)
            task_result = self.tasks.delete_workspace_records(name)
            for manager in managers:
                self._forget_chat_workspace(manager, name)
            return {**result, **task_result}
        finally:
            self.tasks.end_workspace_delete(name)


def _http_error(exc: Exception, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def create_app(workspace_root: str | None = None) -> FastAPI:
    runtime = WebRuntime(workspace_root)
    app = FastAPI(title="HarnessNovel Web", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    static_dir = Path(__file__).resolve().parent / "static"

    @app.middleware("http")
    async def disable_local_asset_cache(request: Request, call_next: Any) -> Any:
        """Always serve fresh assets while the local workbench is under active development."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/settings")
    def settings() -> dict[str, str]:
        return {"workspace_root": str(runtime.store.root)}

    @app.put("/api/settings/workspace-root")
    def update_workspace_root(payload: dict[str, Any] = Body(...)) -> dict[str, str]:
        try:
            root = str(payload.get("workspace_root") or "").strip()
            if not root:
                raise ValueError("请填写工作区根目录。")
            runtime.set_workspace_root(root)
            return {"workspace_root": str(runtime.store.root)}
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return _config_for_client()

    @app.put("/api/config")
    def update_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        raw_values = payload.get("values")
        if not isinstance(raw_values, dict):
            raise _http_error(ValueError("配置格式无效。"))
        updates: dict[str, str] = {}
        for key in CONFIG_KEYS:
            value = raw_values.get(key)
            if value is None:
                continue
            value = str(value).strip()
            # API Key 留空即保持已有值，避免浏览器无法回显密钥时误清空。
            if key.endswith("_API_KEY") and not value:
                continue
            if value:
                updates[key] = value
        if updates:
            _update_env(updates)
            # 同步更新当前 Web 进程。ConfigLoader 默认优先读取 os.environ，
            # 仅写 .env 会导致同进程聊天和后续子进程仍沿用启动时的旧值。
            from core.config import ConfigLoader
            ConfigLoader.activate(updates)
        return _config_for_client()

    @app.get("/api/workspaces")
    def list_workspaces() -> dict[str, Any]:
        return {"workspace_root": str(runtime.store.root), "items": runtime.store.list_workspaces()}

    @app.get("/api/workspaces/{name}")
    def workspace_summary(name: str) -> dict[str, Any]:
        try:
            return runtime.store.summary(name)
        except FileNotFoundError as exc:
            raise _http_error(ValueError("工作区不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.delete("/api/workspaces/{name}")
    def delete_workspace(name: str) -> dict[str, Any]:
        try:
            return runtime.delete_workspace(name)
        except FileNotFoundError as exc:
            raise _http_error(ValueError("工作区不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/tree")
    def workspace_tree(name: str) -> dict[str, Any]:
        try:
            return {"items": runtime.store.tree(name)}
        except FileNotFoundError as exc:
            raise _http_error(ValueError("工作区不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/file")
    def read_workspace_file(name: str, path: str = Query(...)) -> dict[str, Any]:
        try:
            return runtime.store.read_file(name, path)
        except FileNotFoundError as exc:
            raise _http_error(ValueError("文件不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.put("/api/workspaces/{name}/file")
    def write_workspace_file(name: str, payload: dict[str, Any] = Body(...)) -> dict[str, bool]:
        try:
            path = str(payload.get("path") or "")
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError("保存内容必须是文本。")
            runtime.store.write_file(name, path, content)
            return {"saved": True}
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/reference-arc-chapters")
    def reference_arc_chapters(name: str, path: str = Query(...)) -> dict[str, Any]:
        try:
            return runtime.store.reference_arc_chapters(name, path)
        except FileNotFoundError as exc:
            raise _http_error(ValueError("文件不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/world-knowledge/enabled")
    def set_world_knowledge_enabled(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        enabled = bool(payload.get("enabled"))
        try:
            ws = init_workspace(name)
            from core.world_knowledge import set_world_knowledge_enabled as _set
            final = _set(ws, enabled)
            return {"ok": True, "enabled": final}
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/arcs/{volume}/chat")
    def arcs_chat(name: str, volume: int, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise _http_error(ValueError("请输入内容后再发送。"))
        try:
            return runtime.arcs_chat.start_message(name, volume, message)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/arcs/{volume}/job")
    def arcs_job(name: str, volume: int) -> dict[str, Any]:
        return runtime.arcs_chat.job_status(name, volume)

    @app.get("/api/workspaces/{name}/arcs/{volume}/prompts")
    def arcs_prompts(name: str, volume: int) -> dict[str, Any]:
        return runtime.arcs_chat.prompts(name, volume)

    @app.post("/api/workspaces/{name}/arcs/{volume}/pause")
    def arcs_pause(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.pause(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/arcs/{volume}/resume")
    def arcs_resume(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.resume(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/arcs/{volume}/stop")
    def arcs_stop(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.stop(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/arcs/{volume}/continue")
    def arcs_continue(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.continue_incomplete(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/arcs/{volume}/reset")
    def arcs_reset(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.reset(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/arcs/{volume}/conversation")
    def arcs_conversation(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.history(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.delete("/api/workspaces/{name}/arcs/{volume}/conversation")
    def arcs_conversation_clear(name: str, volume: int) -> dict[str, Any]:
        try:
            return runtime.arcs_chat.clear(name, volume)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/chat")
    def chapters_chat(name: str, volume: int, arc_idx: int, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise _http_error(ValueError("请输入内容后再发送。"))
        try:
            return runtime.chapters_chat.start_message(name, volume, arc_idx, message)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/chapters/system-panel")
    def chapters_system_panel_status(name: str) -> dict[str, Any]:
        try:
            from training.adaptive_builder import system_panel_status
            return system_panel_status(init_workspace(name))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/system-panel")
    def chapters_system_panel_config(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            from training.adaptive_builder import configure_system_panel
            return configure_system_panel(init_workspace(name), str(payload.get("mode") or "auto"))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/finalized-chapters")
    def finalized_chapters_update(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            from training.adaptive_builder import set_chapter_finalized
            finalized = set_chapter_finalized(
                init_workspace(name),
                str(payload.get("kind") or ""),
                int(payload.get("volume") or 0),
                int(payload.get("chapter") or 0),
                bool(payload.get("finalized")),
            )
            return {"finalized_chapters": finalized}
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/job")
    def chapters_job(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.job_status(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/prompts")
    def chapters_prompts(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        return runtime.chapters_chat.prompts(name, volume, arc_idx)

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/pause")
    def chapters_pause(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.pause(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/resume")
    def chapters_resume(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.resume(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/stop")
    def chapters_stop(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.stop(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/continue")
    def chapters_continue(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.continue_incomplete(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/reset")
    def chapters_reset(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.reset(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/conversation")
    def chapters_conversation(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.history(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.delete("/api/workspaces/{name}/chapters/{volume}/{arc_idx}/conversation")
    def chapters_conversation_clear(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.chapters_chat.clear(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/chat")
    def drafts_chat(name: str, volume: int, arc_idx: int, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            return runtime.draft_chat.start_message(
                name,
                volume,
                arc_idx,
                str(payload.get("message") or ""),
                humanize=payload.get("humanize") is not False,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/conversation")
    def drafts_conversation(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        return runtime.draft_chat.history(name, volume, arc_idx)

    @app.delete("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/conversation")
    def drafts_conversation_clear(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        return runtime.draft_chat.clear(name, volume, arc_idx)

    @app.get("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/job")
    def drafts_job(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        return runtime.draft_chat.job_status(name, volume, arc_idx)

    @app.get("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/prompts")
    def drafts_prompts(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        return runtime.draft_chat.prompts(name, volume, arc_idx)

    @app.post("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/reset")
    def drafts_reset(name: str, volume: int, arc_idx: int) -> dict[str, Any]:
        try:
            return runtime.draft_chat.reset(name, volume, arc_idx)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/drafts/{volume}/{arc_idx}/{action}")
    def drafts_control(name: str, volume: int, arc_idx: int, action: str) -> dict[str, Any]:
        try:
            if action == "pause":
                return runtime.draft_chat.pause(name, volume, arc_idx)
            if action == "resume":
                return runtime.draft_chat.resume(name, volume, arc_idx)
            if action == "stop":
                return runtime.draft_chat.stop(name, volume, arc_idx)
            if action == "continue":
                return runtime.draft_chat.continue_incomplete(name, volume, arc_idx)
            raise ValueError("不支持的正文任务操作。")
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/drafts/writing-guide")
    def drafts_writing_guide(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            upload_id = str(payload.get("upload_id") or "")
            source = runtime.uploads.resolve(upload_id)
            content = Path(source).read_text(encoding="utf-8")
            return runtime.draft_chat.save_writing_guide(name, content, Path(source).name)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/drafts/writing-guide")
    def drafts_writing_guide_status(name: str) -> dict[str, Any]:
        return runtime.draft_chat.writing_guide_status(name)

    @app.delete("/api/workspaces/{name}/drafts/writing-guide")
    def drafts_writing_guide_reset(name: str) -> dict[str, Any]:
        return runtime.draft_chat.reset_writing_guide(name)

    @app.post("/api/workspaces/{name}/design/{scope}/generate")
    def design_generate(name: str, scope: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        try:
            ws = init_workspace(name)
            from training.adaptive_builder import gen_design_concept, gen_stage_design
            kwargs = {"force": bool(payload.get("force"))}
            if payload.get("direction"):
                kwargs["creative_direction"] = str(payload["direction"])
            upload_id = str(payload.get("direction_upload_id") or "")
            if upload_id:
                kwargs["direction_file"] = str(runtime.uploads.resolve(upload_id))
            result = gen_design_concept(ws, **kwargs) if scope == "concept" else gen_stage_design(ws, **kwargs)
            return {"ok": True, "result": result}
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/design/{scope}/chat")
    def design_chat(name: str, scope: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        message = str(payload.get("message") or "").strip()
        raw_attachments = payload.get("attachments") or []
        attachments = []
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if not isinstance(item, dict):
                    continue
                attachments.append({
                    "name": str(item.get("name") or "附件"),
                    "content": str(item.get("content") or ""),
                })
        if (
            not message
            and not any(att["content"].strip() for att in attachments)
            and not bool(payload.get("use_new_reference"))
            and not bool(payload.get("sync_updated_design"))
        ):
            raise _http_error(ValueError("请输入灵感或上传文件后再发送。"))
        try:
            return runtime.design_chat.start_message(
                name, scope, message, attachments,
                use_new_reference=bool(payload.get("use_new_reference")),
                sync_updated_design=bool(payload.get("sync_updated_design")),
            )
        except Exception as exc:
            # 参数问题才是 400；模型调用、输出校验等服务端生成失败应返回 500。
            raise _http_error(exc, 500 if isinstance(exc, RuntimeError) else 400) from exc

    @app.get("/api/workspaces/{name}/design/{scope}/job")
    def design_job(name: str, scope: str) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        return runtime.design_chat.job_status(name, scope)

    @app.get("/api/workspaces/{name}/design/{scope}/prompts")
    def design_prompts(name: str, scope: str) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        return runtime.design_chat.prompts(name, scope)

    @app.post("/api/workspaces/{name}/design/{scope}/pause")
    def design_pause(name: str, scope: str) -> dict[str, Any]:
        try:
            return runtime.design_chat.pause(name, scope)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/design/{scope}/resume")
    def design_resume(name: str, scope: str) -> dict[str, Any]:
        try:
            return runtime.design_chat.resume(name, scope)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/design/{scope}/stop")
    def design_stop(name: str, scope: str) -> dict[str, Any]:
        try:
            return runtime.design_chat.stop(name, scope)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/design/{scope}/continue")
    def design_continue(name: str, scope: str) -> dict[str, Any]:
        try:
            return runtime.design_chat.continue_incomplete(name, scope)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/api/workspaces/{name}/design/{scope}/reset")
    def design_reset(name: str, scope: str) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        try:
            return runtime.design_chat.reset(name, scope)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/api/workspaces/{name}/design/{scope}/conversation")
    def design_conversation(name: str, scope: str) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        return runtime.design_chat.get(name, scope).history()

    @app.delete("/api/workspaces/{name}/design/{scope}/conversation")
    def design_conversation_clear(name: str, scope: str) -> dict[str, Any]:
        if scope not in {"concept", "stage"}:
            raise _http_error(ValueError("设计步骤只能是 concept 或 stage。"))
        return runtime.design_chat.clear(name, scope)

    @app.post("/api/uploads")
    async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in UPLOAD_EXTENSIONS:
            raise _http_error(ValueError("仅支持 txt、md、json、csv、yaml 等文本资料。"))
        filename = _safe_filename(file.filename)
        destination = runtime.uploads.root / f"{os.urandom(8).hex()}_{filename}"
        size = 0
        try:
            with destination.open("wb") as handle:
                while (chunk := await file.read(1024 * 1024)):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError("上传文件超过 80MB。")
                    handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        upload_id = runtime.uploads.register(destination)
        return {"id": upload_id, "name": filename, "size": size}

    @app.post("/api/tasks")
    def create_task(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            task_type = str(payload.get("type") or "")
            workspace = str(payload.get("workspace") or "")
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("任务参数格式无效。")
            task = runtime.tasks.create(task_type, workspace, args)
            return task.public()
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/tasks")
    def list_tasks(workspace: Optional[str] = None) -> dict[str, Any]:
        return {"items": runtime.tasks.list(workspace)}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = runtime.tasks.get(task_id)
        if not task:
            raise _http_error(ValueError("任务不存在。"), 404)
        return task.public()

    @app.get("/api/tasks/{task_id}/logs")
    def task_logs(task_id: str, offset: int = 0) -> dict[str, Any]:
        try:
            return runtime.tasks.logs(task_id, offset)
        except KeyError as exc:
            raise _http_error(ValueError("任务不存在。"), 404) from exc

    @app.get("/api/tasks/{task_id}/prompts")
    def task_prompts(task_id: str) -> dict[str, Any]:
        try:
            return runtime.tasks.prompts(task_id)
        except KeyError as exc:
            raise _http_error(ValueError("任务不存在。"), 404) from exc

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, Any]:
        try:
            return runtime.tasks.delete(task_id)
        except KeyError as exc:
            raise _http_error(ValueError("任务不存在。"), 404) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.delete("/api/task-prompts")
    def clear_task_prompts(workspace: Optional[str] = None) -> dict[str, Any]:
        try:
            return runtime.tasks.clear_prompts(workspace)
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")
    return app
