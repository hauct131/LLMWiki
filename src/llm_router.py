"""
llm_router.py — Routes LLM calls to the right backend with timeout + error isolation.

Responsibilities:
  - Try Gemini API first (if configured), then OpenAI-compatible, then Ollama.
  - Enforce per-call timeouts so a hung model never blocks the pipeline.
  - Return a plain string. Never raise — on any failure, return "".
  - Callers (prompt_runner) are responsible for validating the string.

Routing priority:
  1. Gemini API  (if config.gemini_api_key is set)
  2. OpenAI-compatible remote  (if config.use_remote_api and config.remote_api_key)
  3. Ollama  (always available as last resort)

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
    temperature = temperature_override if temperature_override is not None \
        else config.profile.temperature
    max_tokens  = config.profile.max_output_tokens

    # ── Priority 1: Gemini ────────────────────────────────────────────────
    if getattr(config, "gemini_api_key", ""):
        result = _call_gemini(prompt, system, config, temperature, max_tokens)
        if result:
            return result
        logger.warning("Gemini API failed — trying next backend")

    # ── Priority 2: OpenAI-compatible remote ──────────────────────────────
    if config.use_remote_api and config.remote_api_key:
        result = _call_openai_compatible(prompt, system, config, temperature, max_tokens)
        if result:
            return result
        logger.warning("Remote API failed — falling back to Ollama")

    # ── Priority 3: Ollama (always last resort) ───────────────────────────
    return _call_ollama(prompt, system, config, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Backend: Gemini  (https://generativelanguage.googleapis.com/v1beta)
# ---------------------------------------------------------------------------

def _call_gemini(
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature: float,
    max_tokens: int,
) -> str:
    """
    Call Gemini via REST API (no SDK required).
    Uses gemini-2.0-flash by default — fast and cheap.
    Model is overridable via config.gemini_model_name.
    """
    api_key    = getattr(config, "gemini_api_key", "")
    model_name = getattr(config, "gemini_model_name", "gemini-2.0-flash")
    timeout    = config.api_timeout_secs

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )

    # Gemini uses systemInstruction separately from user parts
    payload: dict = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature":    temperature,
            "maxOutputTokens": max_tokens,
            "candidateCount": 1,
        },
    }

    if system:
        payload["systemInstruction"] = {
            "parts": [{"text": system}]
        }

    headers = {"Content-Type": "application/json"}
    raw = _http_post(url, headers, payload, timeout)
    if not raw:
        return ""

    try:
        data = json.loads(raw)
        # Navigate: candidates[0].content.parts[0].text
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini returned no candidates: %r", raw[:200])
            return ""
        content = candidates[0].get("content", {})
        parts   = content.get("parts", [])
        if not parts:
            return ""
        return parts[0].get("text", "")
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Gemini response parse error: %s | raw: %r", exc, raw[:200])
        return ""


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

    except urllib.error.HTTPError as exc:
        logger.error("LLM HTTP %d error (%s): %s", exc.code, url, exc.reason)
        return ""
    except urllib.error.URLError as exc:
        logger.error("LLM network error (%s): %s", url, exc)
        return ""
    except TimeoutError:
        logger.error("LLM timeout after %ds (%s)", timeout, url)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM unexpected error (%s): %s", url, exc)
        return ""