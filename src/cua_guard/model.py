"""Bounded DeepSeek chat transport. Secrets and response bodies are never logged."""
from __future__ import annotations
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class ModelError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Model endpoint redirected; refusing to forward credentials")


def load_env(path: str | Path = ".env") -> None:
    """Load simple KEY=value entries; no interpolation or shell evaluation."""
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, sep, value = line.partition("=")
                if not sep or not key.strip().replace("_", "").isalnum():
                    raise ValueError("Invalid .env entry")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class DeepSeekClient:
    def __init__(self, key: str, base_url="https://api.deepseek.com",
                 model="deepseek-flash", max_calls=20, max_tokens=2048,
                 timeout=60, allow_local_http=False):
        url = urllib.parse.urlsplit(base_url)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Invalid model endpoint")
        if url.scheme != "https" and not (allow_local_http and url.scheme == "http"
                and url.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("Model endpoint must use HTTPS")
        if not key:
            raise ModelError("Set MODEL_API_KEY in the local .env file")
        if max_calls < 1 or not 1 <= max_tokens <= 8192:
            raise ValueError("Invalid request limits")
        self.key, self.url, self.model = key, base_url.rstrip("/") + "/chat/completions", model
        self.max_calls, self.max_tokens, self.timeout = max_calls, max_tokens, timeout
        self.calls, self.usage = 0, []
        self.opener = urllib.request.build_opener(NoRedirect())

    @classmethod
    def from_env(cls):
        load_env()
        return cls(os.environ.get("MODEL_API_KEY", ""),
                   os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com"),
                   os.environ.get("MODEL_ID", "deepseek-flash"),
                   int(os.environ.get("MODEL_MAX_CALLS", "20")))

    def complete(self, messages, *, tools=None, json_output=False):
        if self.calls >= self.max_calls:
            raise ModelError("Per-run model call limit reached")
        body = dict(model=self.model, messages=messages, max_tokens=self.max_tokens,
                    thinking={"type": "disabled"}, stream=False, temperature=0)
        if tools:
            body["tools"] = tools
        if json_output:
            body["response_format"] = {"type": "json_object"}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(payload) > 4_000_000:
            raise ModelError("Input exceeds request size limit")
        request = urllib.request.Request(self.url, data=payload, headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        self.calls += 1  # Failed requests also consume budget; no hidden retries.
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("Oversized model response")
            result = json.loads(raw)
            choice = result["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ModelError("Incomplete model response")
            self.usage.append(result.get("usage", {}))
            return choice["message"]
        except urllib.error.HTTPError as exc:
            raise ModelError(f"Model HTTP status {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
            raise ModelError("Model transport or response validation failed") from None

    def json(self, system: str, data: dict) -> dict:
        message = self.complete([
            {"role": "system", "content": system + " Return one JSON object."},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)}], json_output=True)
        try:
            value = json.loads(message["content"])
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (KeyError, TypeError, ValueError):
            raise ModelError("Expected a JSON object") from None
