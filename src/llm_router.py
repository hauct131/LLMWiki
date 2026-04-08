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
import time
import random
from typing import Optional, List
from itertools import cycle

from .config import PipelineConfig

logger = logging.getLogger(__name__)

# ADDED: Global state for key rotation and rate limiting
_key_cycler = None
_last_request_time = 0
_min_interval = 0.5  # seconds between requests (2 req/sec max) – safe
_max_retries_per_key = 2  # number of attempts per key before giving up
_global_rate_limit_rpm = 15  # max requests per minute (adjust as needed)
_rate_limit_lock = None  # simple lock using time tracking

# ADDED: Helper functions for rate limiting
def _rate_limit():
    """Ensure at least _min_interval seconds between requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _min_interval:
        sleep_time = _min_interval - elapsed + random.uniform(0, 0.1)
        time.sleep(sleep_time)
    _last_request_time = time.time()

def _init_key_cycler(keys: List[str]):
    global _key_cycler
    if _key_cycler is None and keys:
        _key_cycler = cycle(keys)

def _get_next_key() -> Optional[str]:
    global _key_cycler
    if _key_cycler is None:
        return None
    return next(_key_cycler)

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

    # ── Priority 1: Gemini (with multiple keys and rate limiting) ─────────
    # ADDED: Use gemini_api_keys if available, otherwise fallback to single key
    keys = getattr(config, "gemini_api_keys", [])
    if not keys and getattr(config, "gemini_api_key", ""):
        keys = [config.gemini_api_key]

    if keys:
        # Initialize key cycler
        _init_key_cycler(keys)
        result = _call_gemini_with_retry(prompt, system, config, temperature, max_tokens)
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
# ADDED: Gemini with key rotation, rate limiting, and 429 handling
# ---------------------------------------------------------------------------

def _call_gemini_with_retry(
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature: float,
    max_tokens: int,
    max_attempts_total: int = 3,
) -> str:
    """
    Try Gemini using round-robin keys. If a key hits 429, skip it and try next.
    If all keys are exhausted, wait and retry entire set up to max_attempts_total.
    Returns response text or "" on failure.
    """
    keys = getattr(config, "gemini_api_keys", [])
    if not keys:
        return ""

    _init_key_cycler(keys)
    total_keys = len(keys)

    for attempt in range(max_attempts_total):
        # Try each key at most once per attempt (or track failed keys)
        tried_in_this_attempt = set()
        for _ in range(total_keys * _max_retries_per_key):
            key = _get_next_key()
            if not key or key in tried_in_this_attempt:
                continue
            tried_in_this_attempt.add(key)

            # Apply rate limiting before each request
            _rate_limit()

            result = _call_gemini_single(key, prompt, system, config, temperature, max_tokens)
            if result is not None:
                return result
            # result is None means failure (including 429) – move to next key
            logger.debug(f"Gemini key {key[:8]}... failed, switching to next key")

        # If we exhausted all keys in this attempt, wait with exponential backoff
        if attempt < max_attempts_total - 1:
            wait_time = (2 ** attempt) * 5 + random.uniform(0, 2)  # 5, 10, 20 seconds
            logger.warning(f"All Gemini keys exhausted. Waiting {wait_time:.1f}s before retry (attempt {attempt+1}/{max_attempts_total})")
            time.sleep(wait_time)

    return ""

def _call_gemini_single(
    api_key: str,
    prompt: str,
    system: str,
    config: PipelineConfig,
    temperature: float,
    max_tokens: int,
) -> Optional[str]:
    """
    Call Gemini with a single API key. Returns response text if successful,
    None if failed (including 429 rate limit). Does not raise.
    """
    model_name = getattr(config, "gemini_model_name", "gemini-2.0-flash")
    timeout = config.api_timeout_secs

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "candidateCount": 1,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    headers = {"Content-Type": "application/json"}
    raw = _http_post(url, headers, payload, timeout)
    if not raw:
        return None

    try:
        data = json.loads(raw)
        # Check for API error (including 429)
        if "error" in data:
            error_code = data["error"].get("code")
            if error_code == 429:
                logger.warning(f"Gemini key {api_key[:8]}... rate limited (429)")
            else:
                logger.error(f"Gemini key {api_key[:8]}... error {error_code}: {data['error'].get('message', '')}")
            return None
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None
        return parts[0].get("text", "")
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning(f"Gemini response parse error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Backend: Gemini (original, kept for reference but not used directly)
# We keep the original _call_gemini function for compatibility but it's not called.
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