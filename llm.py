"""Thin client for a local Ollama server: tool-calling chat + JSON-schema output."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

import config


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, model: str = config.MODEL, base_url: str = config.OLLAMA_URL):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.load(resp)
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self.base_url} ({exc}). Start it with `ollama serve` "
                f"and pull the model with `ollama pull {self.model}`."
            ) from exc

    def _options(self) -> Dict[str, Any]:
        return {"temperature": config.TEMPERATURE, "seed": config.SEED, "num_ctx": 8192}

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """One reasoning step. Returns the assistant message (may contain tool_calls)."""
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "keep_alive": "30m", "options": self._options()}
        if tools:
            payload["tools"] = tools
        return self._post(payload)["message"]

    def structured(self, messages: List[Dict[str, Any]], schema: Dict[str, Any]) -> Dict[str, Any]:
        """Constrained decoding: the reply is guaranteed to match `schema`."""
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "keep_alive": "30m", "format": schema, "options": self._options()}
        content = self._post(payload)["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {content[:200]}") from exc
