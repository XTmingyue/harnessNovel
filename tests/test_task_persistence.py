from pathlib import Path

from webui.task_runner import TaskManager, TaskRecord, UploadStore, WorkspaceStore


def make_manager(tmp_path: Path) -> TaskManager:
    return TaskManager(
        WorkspaceStore(tmp_path / "workspaces"),
        tmp_path / "tasks",
        UploadStore(tmp_path / "uploads"),
    )


def test_completed_task_is_restored_after_restart(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    record = TaskRecord(
        id="abcdef123456",
        type="world_build",
        label="构建目标世界资料库",
        workspace="测试项目",
        status="succeeded",
        message="执行完成",
        log_path=str(tmp_path / "tasks" / "abcdef123456.log"),
    )
    manager._tasks[record.id] = record
    manager._persist_record(record)
    manager._append_log(record, "历史日志\n")

    restored = make_manager(tmp_path)

    assert restored.list("测试项目")[0]["id"] == record.id
    assert restored.logs(record.id)["content"] == "历史日志\n"


def test_running_task_is_marked_interrupted_after_restart(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    record = TaskRecord(
        id="123456abcdef",
        type="write",
        label="生成正文",
        workspace="测试项目",
        status="running",
        message="正在执行",
        log_path=str(tmp_path / "tasks" / "123456abcdef.log"),
    )
    manager._tasks[record.id] = record
    manager._persist_record(record)

    restored = make_manager(tmp_path)
    task = restored.get(record.id)

    assert task is not None
    assert task.status == "failed"
    assert task.message == "服务重启，任务已中断"
    assert "已标记为中断" in restored.logs(record.id)["content"]
