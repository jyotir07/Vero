"""OpenAI behind the provider interface.

Every failure mode is translated into LLMError or LLMTimeout, so the runner reacts to a
provider outage the same way whoever is behind the seam. A timeout is always set: an
unbounded model call would hold a workflow open indefinitely.
"""

from openai import APITimeoutError, OpenAI

from vero.agent.provider.base import LLMError, LLMResponse, LLMTimeout


class OpenAIProvider:
    def __init__(self, *, client: OpenAI, model: str, timeout: float = 30.0) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout

    def complete(self, *, system: str, user: str) -> LLMResponse:
        import time

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                timeout=self._timeout,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc
        except Exception as exc:
            raise LLMError(f"model call failed: {exc}") from exc

        usage = response.usage
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
