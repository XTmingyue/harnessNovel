import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.llm_provider import LLMProvider


class _NeverCancelled:
    def is_set(self):
        return False

    def wait(self, _seconds):
        return False


class _FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create),
        )

    def create(self, **_kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.result))],
        )

    def close(self):
        return None


class LlmProviderTests(unittest.TestCase):
    def test_cancelable_request_retries_transient_timeout(self):
        with patch("core.llm_provider.OpenAI", return_value=_FakeClient()):
            provider = LLMProvider(model="test", api_key="key")
        clients = [
            _FakeClient(error=TimeoutError("Request timed out")),
            _FakeClient(result="重试成功"),
        ]
        with patch.object(provider, "_create_client", side_effect=clients):
            result = provider.generate_cancelable(
                "正文提示词",
                _NeverCancelled(),
                max_retries=1,
            )

        self.assertEqual(result, "重试成功")

    def test_timeout_setting_has_safe_fallback(self):
        with (
            patch.dict("os.environ", {"HARNESS_NOVEL_LLM_TIMEOUT": "invalid"}),
            patch("core.llm_provider.OpenAI", return_value=_FakeClient()),
        ):
            provider = LLMProvider(model="test", api_key="key")

        self.assertEqual(provider.timeout, 600.0)


if __name__ == "__main__":
    unittest.main()
