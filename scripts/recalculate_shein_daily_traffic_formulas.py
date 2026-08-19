#!/usr/bin/env python3
"""Recalculate downstream SHEIN daily-traffic worksheets.

The 8:00 daily-traffic job writes each store's rows with
sync-shein-daily-traffic-to-sheet.py --skip-recalculate, then runs this script
once so the formula-heavy downstream worksheets are recalculated in order.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time
from typing import Any
import urllib.error
import urllib.request


DEFAULT_MAYBEAI_BASE_URL = "https://a-play-be.maybeai.cn"
DEFAULT_MAYBEAI_API_TIMEOUT = 300
DEFAULT_MAYBEAI_API_ATTEMPTS = 3
DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS = 5

TRAFFIC_RECALCULATE_WORKSHEETS = [
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=91",
        "clear_cache": False,
        "formula_engine": "base",
        "workbook_scope": False,
        "sync_save": False,
        "worksheet_name": "产品_SKU日事实表",
    },
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=93",
        "clear_cache": False,
        "formula_engine": "base",
        "workbook_scope": False,
        "sync_save": False,
        "worksheet_name": "产品_日趋势汇总表",
    },
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=94",
        "clear_cache": False,
        "formula_engine": "base",
        "workbook_scope": False,
        "sync_save": False,
        "worksheet_name": "产品_类目周期明细表",
    },
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=95",
        "clear_cache": False,
        "formula_engine": "base",
        "workbook_scope": False,
        "sync_save": False,
        "worksheet_name": "产品_生命周期周期汇总表",
    },
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=92",
        "clear_cache": False,
        "formula_engine": "base",
        "workbook_scope": False,
        "sync_save": False,
        "worksheet_name": "产品_预设周期汇总表",
    },
    {
        "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=123",
        "clear_cache": False,
        "sync_save": True,
        "worksheet_name": "SKC区域运费当月",
    },
]


class RecalculateError(Exception):
    """Raised when a traffic worksheet recalculation fails."""


class MaybeAIClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        attempts: int = DEFAULT_MAYBEAI_API_ATTEMPTS,
        retry_delay_seconds: int = DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.attempts = max(1, attempts)
        self.retry_delay_seconds = max(0, retry_delay_seconds)

    def post(self, path: str, payload: dict[str, Any], timeout: int = DEFAULT_MAYBEAI_API_TIMEOUT) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error = ""
        for attempt in range(1, self.attempts + 1):
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=data,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", "replace")
                last_error = f"HTTP {error.code}:\n{body}"
                if error.code not in {429, 500, 502, 503, 504} or attempt >= self.attempts:
                    raise RecalculateError(f"MaybeAI API {path} failed with {last_error}") from error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, http.client.HTTPException) as error:
                last_error = str(error)
                if attempt >= self.attempts:
                    raise RecalculateError(
                        f"MaybeAI API {path} failed after {self.attempts} attempts: {last_error}"
                    ) from error

            if self.retry_delay_seconds > 0:
                print(
                    f"MaybeAI API {path} failed on attempt {attempt}/{self.attempts}; "
                    f"retrying in {self.retry_delay_seconds}s..."
                )
                time.sleep(self.retry_delay_seconds)

        raise RecalculateError(f"MaybeAI API {path} failed after {self.attempts} attempts: {last_error}")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def maybeai_token() -> str:
    for name in ("MAYBEAI_API_TOKEN", "MAYBEAI_AUTH_TOKEN", "MAYBEAI_API_KEY"):
        token = os.environ.get(name)
        if token:
            return token
    raise RecalculateError("Missing MaybeAI token. Set MAYBEAI_API_TOKEN, MAYBEAI_AUTH_TOKEN, or MAYBEAI_API_KEY.")


def recalculate_worksheets(
    *,
    store: str,
    token: str,
    attempts: int,
    retry_delay_seconds: int,
    base_url: str = DEFAULT_MAYBEAI_BASE_URL,
) -> list[dict[str, Any]]:
    """Recalculate the downstream traffic worksheets in their required order."""
    recalculate_client = MaybeAIClient(
        base_url,
        token,
        attempts=attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    results: list[dict[str, Any]] = []
    total = len(TRAFFIC_RECALCULATE_WORKSHEETS)
    for index, payload in enumerate(TRAFFIC_RECALCULATE_WORKSHEETS, start=1):
        worksheet_name = payload["worksheet_name"]
        print(f"[{store}] Step 7/7: recalculating worksheet {index}/{total}: {worksheet_name}.")
        result = recalculate_client.post(
            "/api/v1/excel/recalculate_formulas",
            dict(payload),
            timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
        )
        success = result.get("success", True)
        if success is False:
            message = result.get("message") or result.get("error") or "success=false"
            raise RecalculateError(f"Worksheet recalculation failed for {worksheet_name}: {message}")
        results.append({"worksheet_name": worksheet_name, "success": success, "result": result})
        print(f"[{store}] Worksheet recalculation {index}/{total} completed: {worksheet_name}.")
    print(f"[{store}] Step 7/7 completed: recalculated {total} worksheets in order.")
    return results


def recalculate_traffic_worksheets(args: argparse.Namespace, client: Any) -> list[dict[str, Any]]:
    """Compatibility entry point used by sync-shein-daily-traffic-to-sheet.py."""
    token = getattr(client, "token", None)
    if not token:
        # Some network-free callers provide a lightweight client double. A real
        # MaybeAIClient always has a token, so only those callers can skip this IO.
        print(f"[{args.store}] Worksheet recalculation skipped: MaybeAI client has no token.")
        return []
    return recalculate_worksheets(
        store=args.store,
        token=token,
        attempts=args.maybeai_api_attempts,
        retry_delay_seconds=args.maybeai_api_retry_delay_seconds,
        base_url=getattr(args, "maybeai_base_url", None) or DEFAULT_MAYBEAI_BASE_URL,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recalculate downstream SHEIN daily-traffic worksheets.")
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Optional .env file to load before reading the MaybeAI token.",
    )
    parser.add_argument(
        "--store",
        default="recalc",
        help="Label used in log messages. Default: recalc",
    )
    parser.add_argument("--maybeai-base-url", default=DEFAULT_MAYBEAI_BASE_URL, help="MaybeAI API base URL.")
    parser.add_argument(
        "--maybeai-api-attempts",
        type=int,
        default=DEFAULT_MAYBEAI_API_ATTEMPTS,
        help=f"MaybeAI API retry attempts. Default: {DEFAULT_MAYBEAI_API_ATTEMPTS}",
    )
    parser.add_argument(
        "--maybeai-api-retry-delay-seconds",
        type=int,
        default=DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS,
        help=f"Delay between MaybeAI API retries. Default: {DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS}",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    for env_file in args.env_file:
        load_env_file(Path(env_file).expanduser())
    print(f"--- recalculate run started at {datetime.now().isoformat(timespec='seconds')} ---")
    try:
        token = maybeai_token()
        recalculate_worksheets(
            store=args.store,
            token=token,
            attempts=args.maybeai_api_attempts,
            retry_delay_seconds=args.maybeai_api_retry_delay_seconds,
            base_url=args.maybeai_base_url,
        )
        return 0
    except RecalculateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        print(f"--- recalculate run finished at {datetime.now().isoformat(timespec='seconds')} ---")
        sys.stdout.flush()
        sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
