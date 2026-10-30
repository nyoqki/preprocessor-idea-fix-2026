import asyncio
import base64
import ssl
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx
import orjson

from yasno.ai import prompts
from yasno.ai.http import (
    ProviderHttp,
    ProviderHttpError,
    Usage,
    first_choice_text,
    log_call,
)
from yasno.ai.transcription import transcription_with_repair
from yasno.ai.types import (
    BoundingBox,
    ChatMessage,
    EmbeddingKind,
    JsonSchema,
    OcrLine,
    OcrResult,
    Transcription,
)

PROVIDER = "yandex"
LLM_URL = "https://llm.api.cloud.yandex.net/v1"
OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1"

type ModelPrefix = Literal["gpt", "emb"]


class YandexClient:
    def __init__(
        self,
        api_key: str,
        folder_id: str,
        *,
        llm_url: str = LLM_URL,
        ocr_url: str = OCR_URL,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool | None = None,
    ) -> None:
        self.folder_id = folder_id
        headers = {
            "Authorization": f"Api-Key {api_key}",
            "x-folder-id": folder_id,
            "OpenAI-Project": folder_id,
            "x-data-logging-enabled": "false",
        }
        self.llm = ProviderHttp(
            PROVIDER,
            base_url=llm_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            verify=verify,
        )
        self.ocr = ProviderHttp(
            PROVIDER,
            base_url=ocr_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            verify=verify,
        )

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.ocr.aclose()

    def model_uri(self, prefix: ModelPrefix, model: str) -> str:
        if "://" in model:
            return model
        return f"{prefix}://{self.folder_id}/{model}/latest"

    async def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        operation: str = "chat",
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model_uri("gpt", model),
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(json_schema.get("title") or "response"),
                    "schema": json_schema,
                    "strict": True,
                },
            }
        started = time.monotonic()
        data = await self.llm.send_json("POST", "chat/completions", json=body)
        text = first_choice_text(PROVIDER, data)
        log_call(PROVIDER, model, operation, started, Usage.from_payload(data))
        return text


def _message_payload(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    return [{"role": message.role.value, "content": message.content} for message in messages]


class YandexChat:
    def __init__(self, client: YandexClient, model: str) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"

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
            _message_payload(messages),
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class YandexVision:
    def __init__(self, client: YandexClient, model: str, *, max_tokens: int = 2000) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"
        self._max_tokens = max_tokens

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
            )

        return await transcription_with_repair(self.name, raw, repair)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(data: Mapping[str, Any], camel: str, snake: str) -> Any:
    return data.get(camel, data.get(snake))


def _bbox(polygon: Any, width: float | None, height: float | None) -> BoundingBox | None:
    if not isinstance(polygon, Mapping) or not width or not height:
        return None
    vertices = polygon.get("vertices")
    if not isinstance(vertices, list):
        return None
    xs = [
        x
        for x in (_number(v.get("x", 0)) for v in vertices if isinstance(v, Mapping))
        if x is not None
    ]
    ys = [
        y
        for y in (_number(v.get("y", 0)) for v in vertices if isinstance(v, Mapping))
        if y is not None
    ]
    if not xs or not ys:
        return None
    left = min(max(min(xs) / width, 0.0), 1.0)
    top = min(max(min(ys) / height, 0.0), 1.0)
    right = min(max(max(xs) / width, 0.0), 1.0)
    bottom = min(max(max(ys) / height, 0.0), 1.0)
    return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)


def _line_text(line: Mapping[str, Any]) -> str:
    text = line.get("text")
    if isinstance(text, str):
        return text
    alternatives = line.get("alternatives")
    if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], Mapping):
        return str(alternatives[0].get("text", ""))
    return ""


def _annotations(content: bytes) -> list[Mapping[str, Any]]:
    chunks: list[Any] = []
    try:
        chunks.append(orjson.loads(content))
    except orjson.JSONDecodeError:
        for raw_line in content.splitlines():
            if raw_line.strip():
                try:
                    chunks.append(orjson.loads(raw_line))
                except orjson.JSONDecodeError as exc:
                    raise ProviderHttpError(PROVIDER, "malformed OCR response") from exc
    if len(chunks) == 1 and isinstance(chunks[0], list):
        chunks = chunks[0]
    annotations: list[Mapping[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        payload = chunk.get("result", chunk)
        if not isinstance(payload, Mapping):
            continue
        annotation = _field(payload, "textAnnotation", "text_annotation")
        if isinstance(annotation, Mapping):
            annotations.append(annotation)
    return annotations


def parse_ocr(content: bytes) -> OcrResult:
    annotations = _annotations(content)
    if not annotations:
        raise ProviderHttpError(PROVIDER, "OCR response has no text annotation")
    annotation = annotations[0]
    width = _number(annotation.get("width"))
    height = _number(annotation.get("height"))
    lines: list[OcrLine] = []
    for block in annotation.get("blocks") or []:
        if not isinstance(block, Mapping):
            continue
        for line in block.get("lines") or []:
            if not isinstance(line, Mapping):
                continue
            text = _line_text(line).strip()
            if text:
                bbox = _bbox(_field(line, "boundingBox", "bounding_box"), width, height)
                lines.append(OcrLine(text=text, bbox=bbox))
    if not lines:
        full_text = _field(annotation, "fullText", "full_text") or annotation.get("markdown") or ""
        lines = [OcrLine(text=row.strip()) for row in str(full_text).splitlines() if row.strip()]
    return OcrResult(lines=lines)


class YandexOcr:
    def __init__(
        self,
        client: YandexClient,
        model: str = "handwritten",
        *,
        languages: Sequence[str] = ("ru", "en"),
    ) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:ocr-{model}"
        self._languages = list(languages)

    async def recognize(self, image: bytes, mime_type: str) -> OcrResult:
        body = {
            "content": base64.b64encode(image).decode("ascii"),
            "mimeType": mime_type,
            "languageCodes": self._languages,
            "model": self.model,
        }
        started = time.monotonic()
        response = await self.client.ocr.send("POST", "recognizeText", json=body)
        result = parse_ocr(response.content)
        log_call(PROVIDER, self.model, "ocr", started, lines=len(result.lines))
        return result


class YandexEmbedder:
    def __init__(
        self,
        client: YandexClient,
        *,
        doc_model: str = "text-search-doc",
        query_model: str = "text-search-query",
        dimensions: int = 256,
        concurrency: int = 4,
    ) -> None:
        self.client = client
        self.name = f"{PROVIDER}:{doc_model}"
        self.dimensions = dimensions
        self._models: dict[EmbeddingKind, str] = {"document": doc_model, "query": query_model}
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _embed_one(self, model: str, text: str) -> list[float]:
        async with self._semaphore:
            started = time.monotonic()
            data = await self.client.llm.send_json(
                "POST",
                "embeddings",
                json={"model": self.client.model_uri("emb", model), "input": [text]},
            )
        try:
            vector = [float(value) for value in data["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderHttpError(PROVIDER, "unexpected embeddings payload") from exc
        log_call(PROVIDER, model, "embed", started, Usage.from_payload(data))
        return vector

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind) -> list[list[float]]:
        model = self._models[kind]
        return list(await asyncio.gather(*(self._embed_one(model, text) for text in texts)))
