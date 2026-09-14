from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Protocol


class JudgeProvider(Protocol):
    def judge_json(self, *, prompt: str, packet: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAIResponsesJudgeProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        timeout_seconds: int = 180,
        use_web_search: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.use_web_search = use_web_search
        self.max_retries = max(1, max_retries)
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI judge calls")

    def judge_json(self, *, prompt: str, packet: dict[str, Any]) -> dict[str, Any]:
        raw = self._request_json(prompt=prompt, packet=packet, use_web_search=self.use_web_search)
        return _parse_response_json(_extract_response_text(raw))

    def _request_json(
        self,
        *,
        prompt: str,
        packet: dict[str, Any],
        use_web_search: bool,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(packet)},
            ],
            "reasoning": {"effort": "low"},
            "text": {"format": {"type": "json_object"}},
        }
        if use_web_search:
            payload["tools"] = [
                {
                    "type": "web_search",
                    "user_location": {"type": "approximate"},
                    "search_context_size": "medium",
                }
            ]
        body = json.dumps(payload).encode("utf-8")
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            request = urllib.request.Request(
                "https://api.openai.com/v1/responses",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if use_web_search and "Web Search cannot be used with JSON mode" in error_body:
                    return self._request_json(
                        prompt=prompt,
                        packet=packet,
                        use_web_search=False,
                    )
                last_error = error_body
                if exc.code not in {408, 409, 429, 500, 502, 503, 504, 520}:
                    raise RuntimeError(f"OpenAI judge request failed: {error_body}") from exc
                if attempt == self.max_retries:
                    raise RuntimeError(f"OpenAI judge request failed: {error_body}") from exc
                time.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError(f"OpenAI judge request failed: {last_error}")


def _extract_response_text(raw: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in raw.get("output", []):
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(str(content["text"]))
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("Judge response did not include output text")
    return text


def _parse_response_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload, _ = json.JSONDecoder().raw_decode(text)
    if not isinstance(payload, dict):
        raise RuntimeError("Judge response JSON must be an object")
    return payload
