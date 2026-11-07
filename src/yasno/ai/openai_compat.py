import base64
import ssl
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx

from yasno.ai import prompts
from yasno.ai.http import ProviderHttp, Usage, first_choice_text, log_call
from yasno.ai.transcription import transcription_with_repair
from yasno.ai.types import ChatMessage, JsonSchema, Transcription

PROVIDER = "openai"

type JsonMode = Literal["schema", "object", "off"]


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        json_mode: JsonMode = "object",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool | None = None,
    ) -> None:
        self.json_mode = json_mode
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = ProviderHttp(
            PROVIDER,
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            verify=verify,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    def _response_format(self, json_schema: JsonSchema) -> dict[str, Any] | None:
        if self.json_mode == "schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": str(json_schema.get("title") or "response"),
                    "schema": json_schema,
                },
            }
        if self.json_mode == "object":
            return {"type": "json_object"}
        return None

    async def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        operation: str = "chat",
        thinking: bool | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        response_format = self._response_format(json_schema) if json_schema else None
        if response_format is not None:
            body["response_format"] = response_format
        if thinking is not None:
            body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        started = time.monotonic()
        data = await self.http.send_json("POST", "chat/completions", json=body)
        text = first_choice_text(PROVIDER, data)
        log_call(PROVIDER, model, operation, started, Usage.from_payload(data))
        return text


class OpenAICompatChat:
    def __init__(
        self, client: OpenAICompatClient, model: str, *, reasoning_tokens: int = 0
    ) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"
        self._reasoning_tokens = reasoning_tokens

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        return await self.client.chat(
            self.model,
            [{"role": m.role.value, "content": m.content} for m in messages],
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens + self._reasoning_tokens,
        )


class OpenAICompatVision:
    def __init__(
        self,
        client: OpenAICompatClient,
        model: str,
        *,
        max_tokens: int = 2000,
        thinking: bool | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"
        self._max_tokens = max_tokens
        self._thinking = thinking

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        encoded = base64.b64encode(image).decode("ascii")
        request = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompts.TRANSCRIBE},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ],
        }
        raw = await self.client.chat(
            self.model,
            [request],
            temperature=0.0,
            max_tokens=self._max_tokens,
            operation="vision",
            thinking=self._thinking,
        )

        async def repair(instruction: str) -> str:
            return await self.client.chat(
                self.model,
                [
                    {"role": "user", "content": prompts.TRANSCRIBE},
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": instruction},
                ],
                temperature=0.0,
                max_tokens=self._max_tokens,
                operation="vision_repair",
                thinking=self._thinking,
            )

        return await transcription_with_repair(self.name, raw, repair)
