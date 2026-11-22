import ipaddress
import json
import math
import re
from contextlib import suppress
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_MAX_RESPONSE = 1024 * 1024
_INVALID = "Invalid chat completion parameters"
_FAILED = "Chat completion failed"
_AUTHORITY = re.compile(r"(?:\[[0-9a-fA-F:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]+)?")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback(hostname):
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _endpoint(base_url):
    if not isinstance(base_url, str) or any(
        ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch in "\\?#" for ch in base_url
    ):
        raise ValueError(_INVALID)
    parts = urlsplit(base_url)
    host = parts.hostname
    port = parts.port
    if (not host or not _AUTHORITY.fullmatch(parts.netloc) or port == 0 or
            (parts.scheme != "https" and not (parts.scheme == "http" and _is_loopback(host)))):
        raise ValueError(_INVALID)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + "/chat/completions", "", ""))


def _bad_constant(_):
    raise ValueError(_FAILED)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(_FAILED)
        result[name] = value
    return result


def _text_result(raw):
    if len(raw) > _MAX_RESPONSE:
        raise ValueError(_FAILED)
    result = json.loads(raw.decode("utf-8"), parse_constant=_bad_constant, object_pairs_hook=_unique_object)
    if not isinstance(result, dict) or "error" in result:
        raise ValueError(_FAILED)
    choices = result.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError(_FAILED)
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise ValueError(_FAILED)
    message = choice.get("message")
    if (not isinstance(message, dict) or message.get("role") != "assistant" or
            message.get("tool_calls") not in (None, []) or
            any(message.get(key) is not None for key in ("function_call", "refusal", "audio"))):
        raise ValueError(_FAILED)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError(_FAILED)
    content.encode("utf-8")
    return content


def complete_chat(base_url, model, api_key, prompt, timeout=30) -> str:
    try:
        if (not isinstance(model, str) or not model.strip() or
                not isinstance(prompt, str) or not prompt.strip() or
                not isinstance(api_key, str) or not api_key or any(not 33 <= ord(ch) <= 126 for ch in api_key) or
                type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError(_INVALID)
        request = Request(
            _endpoint(base_url),
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
    except (ValueError, OverflowError):
        request = None
    if request is None:
        raise ValueError(_INVALID)

    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(_FAILED)
            raw = response.read(_MAX_RESPONSE + 1)
        return _text_result(raw)
    except HTTPError as error:
        with suppress(Exception):
            error.close()
    except Exception:
        pass
    raise RuntimeError(_FAILED)
