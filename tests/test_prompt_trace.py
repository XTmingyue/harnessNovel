import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.llm_provider import LLMProvider
from core.prompt_trace import capture_prompts


class PromptTraceTests(unittest.TestCase):
    def test_provider_records_actual_prompt_to_file_and_callback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "task.prompts.jsonl"
            captured = []
            with (
                patch.dict(
                    os.environ,
                    {
                        "HARNESS_NOVEL_PROMPT_TRACE_FILE": str(trace_path),
                        "OPENAI_API_KEY": "",
                    },
                    clear=False,
                ),
                capture_prompts(captured.append),
            ):
                provider = LLMProvider(model="demo-model", api_key=None)
                result = provider.generate("最终拼装后的测试 Prompt")

            self.assertEqual("", result)
            self.assertEqual(1, len(captured))
            self.assertEqual("demo-model", captured[0]["model"])
            self.assertEqual("最终拼装后的测试 Prompt", captured[0]["prompt"])
            persisted = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual("最终拼装后的测试 Prompt", persisted[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
