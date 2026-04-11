from __future__ import annotations

from typing import Any
from urllib import error, request
import os


def build_auth_headers_from_env() -> dict[str, str]:
    value = os.environ.get("COMFY_AUTH_HEADER_VALUE", "").strip()
    if value:
        name = os.environ.get("COMFY_AUTH_HEADER_NAME", "Authorization").strip() or "Authorization"
        return {name: value}
    token = os.environ.get("COMFY_AUTH_HEADER", "").strip()
    if token:
        name = os.environ.get("COMFY_AUTH_HEADER_NAME", "Authorization").strip() or "Authorization"
        scheme = os.environ.get("COMFY_AUTH_SCHEME", "Bearer").strip()
        return {name: f"{scheme} {token}".strip() if scheme else token}
    return {}


def auth_header_variants(base_headers: dict[str, str] | None = None) -> list[dict[str, str]]:
    headers = dict(build_auth_headers_from_env())
    if base_headers:
        headers.update(base_headers)
    variants: list[dict[str, str]] = [headers]
    auth_value = headers.get("Authorization")
    if isinstance(auth_value, str):
        auth_value = auth_value.strip()
        if " " in auth_value:
            _scheme, token = auth_value.split(" ", 1)
            token = token.strip()
            if token:
                alt = dict(headers)
                alt["Authorization"] = token
                variants.append(alt)
    # Some reverse proxies reject malformed/strict Authorization headers on specific endpoints
    # (for example /history) even when the endpoint is otherwise public. Try a no-auth variant last.
    if headers:
        variants.append({})
    return variants


def urlopen_with_auth_fallback(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    retry_on_401: bool = True,
) -> Any:
    variants = auth_header_variants(headers)
    last_http_error: error.HTTPError | None = None
    for idx, hdrs in enumerate(variants):
        req = request.Request(url, method=method, data=data, headers=hdrs)
        try:
            return request.urlopen(req, timeout=timeout)
        except error.HTTPError as exc:
            last_http_error = exc
            is_last = idx == len(variants) - 1
            if not retry_on_401 or exc.code != 401 or is_last:
                raise
    if last_http_error is not None:
        raise last_http_error
    req = request.Request(url, method=method, data=data, headers=build_auth_headers_from_env())
    return request.urlopen(req, timeout=timeout)
