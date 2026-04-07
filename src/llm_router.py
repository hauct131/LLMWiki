"""
llm_router.py — Routes LLM calls to the right backend with timeout + error isolation.

Responsibilities:
  - Try remote API first (if configured), fall back to Ollama.
  - Enforce per-call timeouts so a hung model never blocks the pipeline.
  - Return a plain string. Never raise — on any failure, return "".
  - Callers (prompt_runner) are responsible for validating the string.

Design contract:
  - `call(prompt, system, config) -> str`
  - Empty string means "failed" — caller handles it.
  - All exceptions are caught here and written to a simple error log param.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from .config import PipelineConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature_override: Optional[float] = None,
) -> str:
    """
    Route the call to the best available backend.
    Returns the model's text response, or "" on any failure.
    Never raises.
    """
    temperature = temperature_override or config.profile.temperature
    max_tokens  = config.profile.max_output_tokens

    if config.use_remote_api and config.remote_api_key:
        result = _call_openai_compatible(
            prompt, system, config, temperature, max_tokens
        )
        if result:
            return result
        logger.warning("Remote API failed — falling back to Ollama")

    return _call_ollama(prompt, system, config, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Backend: OpenAI-compatible remote API
# ---------------------------------------------------------------------------

def _call_openai_compatible(
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature: float,
    max_tokens: int,
) -> str:
    payload = {
        "model":       config.api_model_name,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": prompt},
        ],
    }
    url     = f"{config.api_base_url}/v1/chat/completions"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {config.remote_api_key}",
    }
    return _http_post(url, headers, payload, config.api_timeout_secs)


# ---------------------------------------------------------------------------
# Backend: Ollama  (http://localhost:11434/api/generate)
# ---------------------------------------------------------------------------

def _call_ollama(
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature: float,
    max_tokens: int,
) -> str:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    payload = {
        "model":  config.api_model_name,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature":  temperature,
            "num_predict":  max_tokens,
        },
    }
    url     = f"{config.api_base_url}/api/generate"
    headers = {"Content-Type": "application/json"}

    raw = _http_post(url, headers, payload, config.api_timeout_secs)
    if not raw:
        return ""

    # Ollama wraps the response in {"response": "..."}
    try:
        data = json.loads(raw)
        return data.get("response", "")
    except json.JSONDecodeError:
        logger.warning("Ollama returned non-JSON: %r", raw[:120])
        return ""


# ---------------------------------------------------------------------------
# Shared HTTP helper — never raises
# ---------------------------------------------------------------------------

def _http_post(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout: int,
) -> str:
    """
    POST JSON payload, return response body as str.
    Returns "" on any network or HTTP error.
    """
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # For OpenAI-compatible: extract content from choices
            try:
                data = json.loads(raw)
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    return msg.get("content", raw)
            except json.JSONDecodeError:
                pass
            return raw

    except urllib.error.URLError as exc:
        logger.error("LLM network error (%s): %s", url, exc)
        return ""
    except TimeoutError:
        logger.error("LLM timeout after %ds (%s)", timeout, url)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM unexpected error (%s): %s", url, exc)
        return ""