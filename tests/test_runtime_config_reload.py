import os
import unittest
from unittest.mock import patch

from core.config import ConfigLoader


class RuntimeConfigReloadTests(unittest.TestCase):
    def test_saved_web_config_replaces_cached_and_process_values(self):
        keys = {
            "ADAPTIVE_BUILDER_LITE_MODEL": "new-model",
            "ADAPTIVE_BUILDER_LITE_BASE_URL": "https://new.example/v1",
            "ADAPTIVE_BUILDER_LITE_API_KEY": "new-key",
        }
        with patch.dict(os.environ, {
            "ADAPTIVE_BUILDER_LITE_MODEL": "old-model",
            "ADAPTIVE_BUILDER_LITE_BASE_URL": "https://old.example/v1",
            "ADAPTIVE_BUILDER_LITE_API_KEY": "old-key",
        }, clear=False):
            ConfigLoader._env = {"ADAPTIVE_BUILDER_LITE_MODEL": "cached-model"}
            ConfigLoader.activate(keys)
            config = ConfigLoader.get_adaptive_builder_lite_config()

            self.assertEqual(config["model"], "new-model")
            self.assertEqual(config["base_url"], "https://new.example/v1")
            self.assertEqual(config["api_key"], "new-key")
            self.assertNotEqual(
                ConfigLoader._env,
                {"ADAPTIVE_BUILDER_LITE_MODEL": "cached-model"},
            )


if __name__ == "__main__":
    unittest.main()
