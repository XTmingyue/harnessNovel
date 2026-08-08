import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from webui.design_chat import DesignChatManager


class DesignChatJobTests(unittest.TestCase):
    def test_concept_chat_exposes_three_step_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"HARNESS_NOVEL_HOME": temp_dir}, clear=False,
        ):
            manager = DesignChatManager(Path(temp_dir))

            def fake_run_message(*args, progress_callback=None, **kwargs):
                progress_callback("worldview", 0, 3, "正在生成世界观")
                progress_callback("worldview_complete", 1, 3, "正在生成粗略大纲")
                progress_callback("rough_outline_complete", 2, 3, "正在生成阶段粗纲")
                progress_callback("stage_outline_complete", 3, 3, "已全部生成")
                return {"mode": "initial", "result": {}, "conversation": {"turns": []}}

            manager.run_message = fake_run_message
            started = manager.start_message("测试", "concept", "生成")
            self.assertEqual(3, started["total"])

            deadline = time.time() + 2
            status = started
            while status["status"] == "running" and time.time() < deadline:
                time.sleep(0.01)
                status = manager.job_status("测试", "concept")

            self.assertEqual("completed", status["status"])
            self.assertEqual(3, status["completed"])
            self.assertEqual(3, status["total"])

    def test_stage_job_supports_pause_resume_and_stop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DesignChatManager(Path(temp_dir))
            pause_event = threading.Event()
            pause_event.set()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            manager._jobs[("测试", "stage")] = {
                "id": "stage-job",
                "status": "running",
                "phase": "stage_generating",
                "completed": 1,
                "total": 3,
                "progress_kind": "stage_design",
                "message": "正在生成舞台2/3",
                "pause_event": pause_event,
                "stop_event": stop_event,
                "cancel_event": cancel_event,
                "error": "",
            }

            paused = manager.pause("测试", "stage")
            self.assertEqual("pausing", paused["status"])
            self.assertFalse(pause_event.is_set())
            self.assertTrue(cancel_event.is_set())

            resumed = manager.resume("测试", "stage")
            self.assertEqual("running", resumed["status"])
            self.assertTrue(pause_event.is_set())
            self.assertFalse(cancel_event.is_set())

            stopped = manager.stop("测试", "stage")
            self.assertEqual("stopping", stopped["status"])
            self.assertTrue(stop_event.is_set())
            self.assertTrue(cancel_event.is_set())

    def test_stage_reset_also_removes_name_and_synopsis(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"HARNESS_NOVEL_HOME": temp_dir}, clear=False,
        ):
            workspace = Path(temp_dir) / "测试"
            design = workspace / "file_system" / "story_design"
            design.mkdir(parents=True)
            (design / "long_mainline.md").write_text("长线", encoding="utf-8")
            (design / "stage_roadmap.md").write_text("舞台", encoding="utf-8")
            synopsis = workspace / "file_system" / "novel_name_synopsis.md"
            synopsis.write_text("书名与简介", encoding="utf-8")
            panel_definition = workspace / "file_system" / "mechanics" / "system_panel.json"
            panel_definition.parent.mkdir(parents=True)
            panel_definition.write_text('{"enabled": true}', encoding="utf-8")
            panel_snapshot = workspace / "file_system" / "system_panels" / "vol_01" / "chapter_001.json"
            panel_snapshot.parent.mkdir(parents=True)
            panel_snapshot.write_text('{"chapter": 1}', encoding="utf-8")

            manager = DesignChatManager(Path(temp_dir))
            manager._jobs[("测试", "stage")] = {
                "id": "finished", "status": "completed",
                "prompt_history": [{"prompt": "历史 Prompt"}], "prompt_count": 1,
                "current_prompt_id": "prompt-1", "prompt_model": "demo",
            }
            manager.reset("测试", "stage")

            self.assertFalse((design / "long_mainline.md").exists())
            self.assertFalse((design / "stage_roadmap.md").exists())
            self.assertFalse(synopsis.exists())
            self.assertFalse(panel_definition.exists())
            self.assertFalse((workspace / "file_system" / "system_panels").exists())
            self.assertEqual([], manager.prompts("测试", "stage")["items"])

    def test_concept_reset_removes_system_panel_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"HARNESS_NOVEL_HOME": temp_dir}, clear=False,
        ):
            workspace = Path(temp_dir) / "测试"
            panel_definition = workspace / "file_system" / "mechanics" / "system_panel.json"
            panel_definition.parent.mkdir(parents=True)
            panel_definition.write_text('{"enabled": true}', encoding="utf-8")
            panel_snapshot = workspace / "file_system" / "system_panels" / "vol_01" / "chapter_001.json"
            panel_snapshot.parent.mkdir(parents=True)
            panel_snapshot.write_text('{"chapter": 1}', encoding="utf-8")

            manager = DesignChatManager(Path(temp_dir))
            manager.reset("测试", "concept")

            self.assertFalse(panel_definition.exists())
            self.assertFalse((workspace / "file_system" / "system_panels").exists())


if __name__ == "__main__":
    unittest.main()
