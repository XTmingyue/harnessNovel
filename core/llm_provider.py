import os
import threading
from openai import OpenAI
from core.text_utils import normalize_text
from core.prompt_trace import record_prompt

# 不值得重试的 HTTP 状态码（认证/余额等确定性错误）
_NO_RETRY_CODES = {401, 402, 403}


class LLMCallCancelled(RuntimeError):
    """模型请求被用户主动取消。"""


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
        try:
            self.timeout = max(
                30.0,
                float(os.getenv("HARNESS_NOVEL_LLM_TIMEOUT", "600")),
            )
        except (TypeError, ValueError):
            self.timeout = 600.0
        self.client = self._create_client() if self.api_key else None

    def _create_client(self):
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            # 由本封装统一控制重试次数，避免 SDK 内部重试时无法及时响应暂停/结束。
            max_retries=0,
        )

    def generate(self, prompt, temperature=0.7, is_json=False, max_retries=2, max_tokens=None):
        """调用大语言模型生成内容。

        成功返回归一化后的文本；未配置 api_key 或 API 调用失败（重试耗尽 /
        401/402/403 等确定性错误）时返回空字符串并打印警告。
        """
        record_prompt(prompt, self.model)
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

    def generate_cancelable(
        self,
        prompt,
        cancel_event,
        temperature=0.7,
        is_json=False,
        max_tokens=None,
        max_retries=2,
    ):
        """执行可取消、可重试的请求；取消后不会返回未完成内容。"""
        record_prompt(prompt, self.model)
        if not self.api_key:
            return ""
        for attempt in range(max_retries + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise LLMCallCancelled("模型请求已取消")
            done = threading.Event()
            outcome = {}
            client = self._create_client()

            def request():
                try:
                    kwargs = {
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens or self.max_tokens,
                    }
                    if is_json:
                        kwargs["response_format"] = {"type": "json_object"}
                    response = client.chat.completions.create(**kwargs)
                    outcome["result"] = normalize_text(response.choices[0].message.content)
                except Exception as exc:
                    outcome["error"] = exc
                finally:
                    done.set()

            threading.Thread(target=request, name="llm-cancelable-call", daemon=True).start()
            while not done.wait(0.1):
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        client.close()
                    except Exception:
                        pass
                    raise LLMCallCancelled("模型请求已取消")

            try:
                client.close()
            except Exception:
                pass
            if "error" not in outcome:
                return outcome.get("result", "")

            error = outcome["error"]
            status_code = getattr(error, "status_code", None)
            if status_code in _NO_RETRY_CODES or attempt >= max_retries:
                raise error

            wait_seconds = min(4.0, 1.5 * (attempt + 1))
            print(
                f"[LLMProvider] 可取消请求失败（第{attempt + 1}次），"
                f"{wait_seconds:g}秒后重试... 错误: {error}"
            )
            if cancel_event is not None:
                if cancel_event.wait(wait_seconds):
                    raise LLMCallCancelled("模型请求已取消")
            else:
                threading.Event().wait(wait_seconds)

        # 循环仅为类型检查器保留；正常情况下成功返回或抛出最后一次异常。
        return ""
