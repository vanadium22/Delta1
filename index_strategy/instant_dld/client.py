"""One bounded HTTP request; preserve server fields and explicit failures."""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import time
from typing import Any

import requests

DEFAULT_URL = (
    "https://otcderivatives.swhysc.com:11443"
    "/market-cache-app/v1/market-cache/post/latest-market-data"
)


class MarketDataClient:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        use_environment: bool = False,
        connect_timeout: float = 10,
        read_timeout: float = 30,
        ca_bundle: Path | None = None,
        session: Any = None,
    ) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in (connect_timeout, read_timeout)):
            raise ValueError("请求超时必须是大于 0 的有限秒数")
        self.url = url
        self.timeout = (connect_timeout, read_timeout)
        self.verify = str(ca_bundle) if ca_bundle else True
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = use_environment

    def close(self) -> None:
        self.session.close()

    def fetch(self, symbols: list[str]) -> dict[str, Any]:
        started = time.monotonic()
        result: dict[str, Any] = {
            "requested_at": datetime.now().astimezone().isoformat(),
            "symbols": list(symbols),
            "status": "request_error",
        }
        try:
            response = self.session.post(
                self.url,
                json=symbols,
                headers={"Content-Type": "application/json", "User-Agent": "PostmanRuntime/7.26.8"},
                timeout=self.timeout,
                verify=self.verify,
                allow_redirects=False,
            )
            try:
                result["http_status"] = response.status_code
                try:
                    payload = response.json()
                except ValueError:
                    result.update(status="invalid_json", response_preview=response.text[:4000])
                    payload = None
                else:
                    result["response"] = payload
                if not 200 <= response.status_code < 300:
                    result["status"] = "http_error"
                elif payload is not None:
                    self._classify(result, payload, symbols)
                elif "response" in result:
                    result["status"] = "invalid_response"
            finally:
                response.close()
        except requests.exceptions.SSLError as exc:
            result.update(status="tls_error", error=str(exc))
        except requests.exceptions.ProxyError as exc:
            result.update(status="proxy_error", error=str(exc))
        except requests.exceptions.Timeout as exc:
            result.update(status="timeout", error=str(exc))
        except requests.exceptions.ConnectionError as exc:
            result.update(status="connection_error", error=str(exc))
        except requests.exceptions.RequestException as exc:
            result.update(status="request_error", error=str(exc))
        result["received_at"] = datetime.now().astimezone().isoformat()
        result["elapsed_seconds"] = round(time.monotonic() - started, 6)
        return result

    @staticmethod
    def _classify(result: dict, payload: Any, symbols: list[str]) -> None:
        if not isinstance(payload, dict):
            result["status"] = "invalid_response"
            return
        code = payload.get("code")
        code_ok = code is None or (type(code) is int and code == 0) or code == "0"
        if payload.get("respSuccess") is not True or payload.get("respFail") is True or not code_ok:
            result["status"] = "business_error"
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            result["status"] = "invalid_response"
            return
        present = [symbol for symbol in symbols if isinstance(data.get(symbol), dict) and data[symbol]]
        result["missing_symbols"] = [symbol for symbol in symbols if symbol not in present]
        result["received_symbols"] = present
        result["status"] = "success" if len(present) == len(symbols) else "partial" if present else "empty"
