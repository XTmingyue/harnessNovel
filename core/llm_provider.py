import os
from openai import OpenAI
from core.text_utils import normalize_text

# 不值得重试的 HTTP 状态码（认证/余额等确定性错误）
_NO_RETRY_CODES = {401, 402, 403}


class LLMProvider:
    """OpenAI 兼容接口的轻量封装。

    只负责真实 API 调用与重试；失败或未配置 api_key 时返回空串并打印警告，
    不再静默返回任何假数据（Mock 已移出主路径）。
    """

    def __init__(self, model="mock-model", base_url=None, api_key=None, max_tokens=None):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.max_tokens = max_tokens
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None

    def generate(self, prompt, temperature=0.7, is_json=False, max_retries=2, max_tokens=None):
        """调用大语言模型生成内容。

        成功返回归一化后的文本；未配置 api_key 或 API 调用失败（重试耗尽 /
        401/402/403 等确定性错误）时返回空字符串并打印警告。
        """
        if not self.client:
            print("[LLMProvider] 未配置 api_key，无法调用模型，返回空内容。")
            return ""

        print(f"[LLMProvider] 正在调用模型 {self.model} ...")
        response_format = {"type": "json_object"} if is_json else None
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if is_json:
            kwargs["response_format"] = response_format

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                return normalize_text(response.choices[0].message.content)
            except Exception as e:
                status_code = getattr(e, 'status_code', None)
                if status_code in _NO_RETRY_CODES:
                    print(f"[LLMProvider] API 错误 ({status_code})，不可重试。")
                    break
                if attempt < max_retries:
                    print(f"[LLMProvider] API 调用失败（第{attempt+1}次），重试中... 错误: {e}")
                else:
                    print(f"[LLMProvider] API 调用失败，已重试{max_retries}次。错误: {e}")

        print("[LLMProvider] 调用失败，返回空内容（请检查 API Key / 余额 / 网络）。")
        return ""
