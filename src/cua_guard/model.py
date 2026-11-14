"""Bounded DeepSeek chat transport. Secrets and response bodies are never logged."""
from __future__ import annotations
import json
import http.client
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
                 timeout=60, allow_local_http=False, wire_api="chat"):
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
        if wire_api not in {"chat", "responses"}:
            raise ValueError("Unsupported model wire API")
        self.key, self.model = key, model
        self.wire_api = wire_api
        endpoint = "/v1/responses" if wire_api == "responses" and not base_url.rstrip("/").endswith("/v1") else "/responses" if wire_api == "responses" else "/chat/completions"
        self.url = base_url.rstrip("/") + endpoint
        self.max_calls, self.max_tokens, self.timeout = max_calls, max_tokens, timeout
        self.calls, self.usage = 0, []
        self.opener = urllib.request.build_opener(NoRedirect())

    @classmethod
    def from_env(cls):
        load_env()
        return cls(os.environ.get("MODEL_API_KEY", ""),
                   os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com"),
                   os.environ.get("MODEL_ID", "deepseek-flash"),
                   int(os.environ.get("MODEL_MAX_CALLS", "20")),
                   wire_api=os.environ.get("MODEL_WIRE_API", "chat"))

    @staticmethod
    def _responses_input(messages):
        converted = []
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"type": "input_text", "text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        parts.append({"type": "input_image", "image_url": item["image_url"]["url"]})
                    else:
                        raise ModelError("Unsupported Responses content item")
                content = parts
            converted.append({"role": message["role"], "content": content})
        return converted

    def complete(self, messages, *, tools=None, json_output=False):
        if self.calls >= self.max_calls:
            raise ModelError("Per-run model call limit reached")
        if self.wire_api == "responses":
            body = dict(model=self.model, input=self._responses_input(messages),
                        max_output_tokens=self.max_tokens, store=False)
            if tools:
                body["tools"] = tools
            # Some Codex-compatible gateways reject the optional structured-output
            # field. JSON is still enforced by the prompt and local validation.
        else:
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
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "User-Agent": "CodexDiagnostic/1.0"})
        self.calls += 1  # Failed requests also consume budget; no hidden retries.
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("Oversized model response")
            result = json.loads(raw)
            if self.wire_api == "responses":
                text = result.get("output_text")
                if not isinstance(text, str):
                    chunks = []
                    for item in result.get("output", []):
                        for part in item.get("content", []):
                            if isinstance(part.get("text"), str):
                                chunks.append(part["text"])
                    text = "".join(chunks)
                if not text:
                    raise ModelError("Incomplete model response")
                self.usage.append(result.get("usage", {}))
                return {"content": text}
            choice = result["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ModelError("Incomplete model response")
            self.usage.append(result.get("usage", {}))
            return choice["message"]
        except urllib.error.HTTPError as exc:
            raise ModelError(f"Model HTTP status {exc.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError,
                TimeoutError, KeyError, IndexError, ValueError) as exc:
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
