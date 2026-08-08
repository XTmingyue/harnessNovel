import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webui.arc_chat import ArcsChatManager


class ArcsChatHistoryTests(unittest.TestCase):
    def test_history_reports_existing_arcs_without_chat_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc_dir = root / "demo" / "file_system" / "story_arcs" / "vol_01"
            arc_dir.mkdir(parents=True)
            (arc_dir / "arc_001_ch001_005.md").write_text("情节功能：测试", encoding="utf-8")
            ws = type("Workspace", (), {"file_system": str(root / "demo" / "file_system")})()

            manager = ArcsChatManager(root)
            with patch("webui.arc_chat.init_workspace", return_value=ws):
                history = manager.history("demo", 1)

            self.assertEqual(history["turns"], [])
            self.assertTrue(history["has_arcs"])


if __name__ == "__main__":
    unittest.main()
