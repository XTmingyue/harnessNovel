import tempfile
import unittest
from pathlib import Path

from webui.task_runner import TaskManager, TaskRecord, UploadStore, WorkspaceStore


class TaskPromptCleanupTests(unittest.TestCase):
    def test_clear_prompts_keeps_logs_and_skips_running_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "tasks"
            manager = TaskManager(
                WorkspaceStore(root / "workspaces"), task_dir,
                UploadStore(root / "uploads"),
            )
            done = TaskRecord(
                id="a" * 12, type="init", label="完成任务",
                workspace="测试", status="succeeded",
                log_path=str(task_dir / f"{'a' * 12}.log"),
            )
            running = TaskRecord(
                id="b" * 12, type="init", label="运行任务",
                workspace="测试", status="running",
                log_path=str(task_dir / f"{'b' * 12}.log"),
            )
            manager._tasks = {done.id: done, running.id: running}
            Path(done.log_path).write_text("日志", encoding="utf-8")
            (task_dir / f"{done.id}.prompts.jsonl").write_text("{}\n", encoding="utf-8")
            (task_dir / f"{running.id}.prompts.jsonl").write_text("{}\n", encoding="utf-8")

            result = manager.clear_prompts("测试")

            self.assertEqual(1, result["removed_task_count"])
            self.assertEqual(1, result["skipped_active_count"])
            self.assertFalse((task_dir / f"{done.id}.prompts.jsonl").exists())
            self.assertTrue((task_dir / f"{running.id}.prompts.jsonl").exists())
            self.assertTrue(Path(done.log_path).exists())

    def test_delete_task_removes_metadata_log_and_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "tasks"
            manager = TaskManager(
                WorkspaceStore(root / "workspaces"), task_dir,
                UploadStore(root / "uploads"),
            )
            task = TaskRecord(
                id="c" * 12, type="init", label="历史任务",
                workspace="测试", status="succeeded",
                log_path=str(task_dir / f"{'c' * 12}.log"),
            )
            manager._tasks[task.id] = task
            manager._persist_record(task)
            Path(task.log_path).write_text("日志", encoding="utf-8")
            (task_dir / f"{task.id}.prompts.jsonl").write_text("{}\n", encoding="utf-8")

            manager.delete(task.id)

            self.assertNotIn(task.id, manager._tasks)
            self.assertFalse((task_dir / f"{task.id}.json").exists())
            self.assertFalse(Path(task.log_path).exists())
            self.assertFalse((task_dir / f"{task.id}.prompts.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
