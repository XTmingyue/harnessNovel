import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from webui.arc_chat import ArcsChatManager


class ArcsChatJobTests(unittest.TestCase):
    def test_pause_and_resume_update_job_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArcsChatManager(Path(tmp))
            event = threading.Event()
            event.set()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            manager._jobs[("demo", 1)] = {
                "id": "job-1",
                "status": "running",
                "phase": "generating",
                "completed": 1,
                "total": 3,
                "message": "正在生成",
                "pause_event": event,
                "stop_event": stop_event,
                "cancel_event": cancel_event,
                "error": "",
            }

            paused = manager.pause("demo", 1)
            self.assertEqual(paused["status"], "pausing")
            self.assertFalse(event.is_set())
            self.assertTrue(cancel_event.is_set())

            resumed = manager.resume("demo", 1)
            self.assertEqual(resumed["status"], "running")
            self.assertTrue(event.is_set())
            self.assertFalse(cancel_event.is_set())

    def test_stop_interrupts_request_and_releases_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArcsChatManager(Path(tmp))
            pause_event = threading.Event()
            pause_event.clear()
            stop_event = threading.Event()
            cancel_event = threading.Event()
            manager._jobs[("demo", 1)] = {
                "id": "job-2",
                "status": "paused",
                "phase": "paused",
                "completed": 2,
                "total": 4,
                "message": "已暂停",
                "pause_event": pause_event,
                "stop_event": stop_event,
                "cancel_event": cancel_event,
                "error": "",
            }

            stopped = manager.stop("demo", 1)
            self.assertEqual(stopped["status"], "stopping")
            self.assertTrue(stop_event.is_set())
            self.assertTrue(cancel_event.is_set())
            self.assertTrue(pause_event.is_set())

    def test_job_status_does_not_expose_thread_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArcsChatManager(Path(tmp))
            self.assertEqual(manager.job_status("demo", 1)["status"], "idle")

    def test_reset_only_removes_selected_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_root = root / "workspaces"
            file_system = workspace_root / "demo" / "file_system"
            stage_1 = file_system / "story_arcs" / "vol_01"
            stage_2 = file_system / "story_arcs" / "vol_02"
            stage_1.mkdir(parents=True)
            stage_2.mkdir(parents=True)
            (stage_1 / "arc_1_ch1_5.md").write_text("舞台一", encoding="utf-8")
            (stage_1 / "arcs_index.json").write_text("{}", encoding="utf-8")
            (stage_2 / "arc_1_ch6_10.md").write_text("舞台二", encoding="utf-8")
            (stage_2 / "arcs_index.json").write_text("{}", encoding="utf-8")

            manager = ArcsChatManager(workspace_root)
            ws = SimpleNamespace(file_system=str(file_system))
            with patch("webui.arc_chat.init_workspace", return_value=ws):
                manager.reset("demo", 2)

            self.assertTrue((stage_1 / "arc_1_ch1_5.md").exists())
            self.assertTrue((stage_1 / "arcs_index.json").exists())
            self.assertFalse((stage_2 / "arc_1_ch6_10.md").exists())
            self.assertFalse((stage_2 / "arcs_index.json").exists())


if __name__ == "__main__":
    unittest.main()
