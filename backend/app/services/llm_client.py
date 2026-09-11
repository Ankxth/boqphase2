"""Shared LLM client abstraction.

Both llm_fallback.py (tier-field estimation) and boq_extractor.py
(ambiguous-row resolution) call through chat_json() instead of each
having their own provider-specific code. Provider is chosen by
LLM_PROVIDER in .env -- "ollama" (local) or "groq" (API) -- with no
changes needed in either caller when you switch.

Local (Ollama) has no per-call cost and keeps data on-device, but is
slow for high call-volume tasks like BOQ ambiguous-row batching on
limited VRAM. Groq is fast but needs an internet connection and a
valid API key. Pick per-situation via .env, not hardcoded.
"""

from __future__ import annotations

import json

from app.core.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


class LLMUnavailableError(Exception):
    """Raised when the configured provider can't be reached or fails.
    Callers should catch this and fall back to their own placeholder logic
    -- this module never silently falls back to a different provider on
    its own, since that would hide which provider actually produced a
    given result.
    """


def _strip_json_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


def _call_ollama(prompt: str) -> dict:
    import ollama

    client = ollama.Client(host=OLLAMA_BASE_URL)
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.1},
    )
    text = _strip_json_fences(response["message"]["content"].strip())
    return json.loads(text)


def _call_groq(prompt: str) -> dict:
    from groq import Groq

    if not GROQ_API_KEY:
        raise LLMUnavailableError("GROQ_API_KEY is not set")

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    text = _strip_json_fences(response.choices[0].message.content.strip())
    return json.loads(text)


def chat_json(prompt: str) -> dict:
    """Sends prompt to the configured provider, returns parsed JSON.
    Raises LLMUnavailableError (or lets the underlying exception surface)
    on any failure -- callers decide what to do next (placeholder
    defaults, leave rows unclassified, etc.), this function doesn't
    silently swap providers or retry on its own.
    """
    if LLM_PROVIDER == "groq":
        return _call_groq(prompt)
    elif LLM_PROVIDER == "ollama":
        return _call_ollama(prompt)
    else:
        raise LLMUnavailableError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}' -- must be 'ollama' or 'groq'")