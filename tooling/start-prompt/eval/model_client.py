"""HTTP adapters for benchmark target models and the blind judge."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from typing import Any


class ModelAPIError(RuntimeError):
    pass


def _endpoint(base_url: str, endpoint_path: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint_path.lstrip("/")


def _text_from_openai_message(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "".join(chunks)
    return str(content or "")


def _request_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ModelAPIError("Provider returned a non-object JSON response")
    return parsed


def _openai_chat(
    runtime: dict[str, Any],
    system_prompt: str | None,
    user_text: str,
    generation: dict[str, Any],
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    system_mode = runtime.get("system_mode", "system")
    if system_prompt and system_mode == "system":
        messages.append({"role": "system", "content": system_prompt})
    elif system_prompt and system_mode == "user_prefix":
        user_text = f"<system_prompt>\n{system_prompt}\n</system_prompt>\n\n{user_text}"
    elif system_prompt:
        raise ModelAPIError(f"Unsupported system_mode: {system_mode}")
    messages.append({"role": "user", "content": user_text})

    max_tokens_field = runtime.get("max_tokens_field", "max_tokens")
    body: dict[str, Any] = {
        "model": runtime["model_id"],
        "messages": messages,
        max_tokens_field: generation["max_tokens"],
    }
    temperature = generation.get("temperature")
    if runtime.get("supports_temperature", True) and temperature is not None:
        body["temperature"] = temperature
    body.update(runtime.get("extra_body", {}))
    headers = {"Content-Type": "application/json", **runtime.get("extra_headers", {})}
    api_key_header = runtime.get("api_key_header", "Authorization")
    api_key_prefix = runtime.get("api_key_prefix", "Bearer ")
    headers[api_key_header] = f"{api_key_prefix}{runtime['api_key']}"
    data = _request_json(
        _endpoint(runtime["base_url"], runtime.get("endpoint_path", "/chat/completions")),
        headers,
        body,
        int(generation.get("timeout_seconds", 180)),
    )
    try:
        choice = data["choices"][0]
        text = _text_from_openai_message(choice["message"])
    except (KeyError, IndexError, TypeError) as error:
        raise ModelAPIError("OpenAI-compatible response is missing choices[0].message") from error
    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "usage": {
            "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "provider_request_id": data.get("id"),
        "finish_reason": choice.get("finish_reason"),
    }


def _anthropic_messages(
    runtime: dict[str, Any],
    system_prompt: str | None,
    user_text: str,
    generation: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": runtime["model_id"],
        "max_tokens": generation["max_tokens"],
        "messages": [{"role": "user", "content": user_text}],
    }
    if system_prompt:
        body["system"] = system_prompt
    temperature = generation.get("temperature")
    if runtime.get("supports_temperature", True) and temperature is not None:
        body["temperature"] = temperature
    body.update(runtime.get("extra_body", {}))
    headers = {
        "Content-Type": "application/json",
        "x-api-key": runtime["api_key"],
        "anthropic-version": runtime.get("anthropic_version", "2023-06-01"),
    }
    data = _request_json(
        _endpoint(runtime["base_url"], runtime.get("endpoint_path", "/messages")),
        headers,
        body,
        int(generation.get("timeout_seconds", 180)),
    )
    content = data.get("content", [])
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": None,
        },
        "provider_request_id": data.get("id"),
        "finish_reason": data.get("stop_reason"),
    }


def generate(
    runtime: dict[str, Any],
    system_prompt: str | None,
    user_text: str,
    generation: dict[str, Any],
) -> dict[str, Any]:
    adapter = runtime.get("adapter")
    adapters = {
        "openai_chat": _openai_chat,
        "anthropic_messages": _anthropic_messages,
    }
    if adapter not in adapters:
        raise ModelAPIError(f"Unsupported adapter: {adapter}")
    retries = int(generation.get("retries", 3))
    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = adapters[adapter](runtime, system_prompt, user_text, generation)
            result["latency_seconds"] = round(time.monotonic() - started, 3)
            result["attempts"] = attempt + 1
            return result
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:2000]
            last_error = ModelAPIError(f"HTTP {error.code}: {body}")
            retryable = error.code in {408, 409, 425, 429} or error.code >= 500
            if not retryable:
                break
        except (urllib.error.URLError, TimeoutError, ModelAPIError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < retries:
            time.sleep(min(2**attempt + random.random(), 15))
    raise ModelAPIError(str(last_error or "Unknown provider error"))
