#!/usr/bin/env python3
"""Sync SHEIN activity rows into a MaybeAI spreadsheet.

The script shells out to `opencli shein activity` for authenticated SHEIN
browser work. Raw crawler rows can be saved to DB per store/day, while the
business Sheet receives only the legacy 11-column ETL projection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_SHEET_URL = "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40"
DEFAULT_RAW_DB_URI = "https://www.maybe.ai/docs/spreadsheets/d/<raw-activity-doc-id>?gid=0"
DEFAULT_MAYBEAI_BASE_URL = "https://play-be.omnimcp.ai"
DEFAULT_MAYBEAI_API_TIMEOUT = 300
DEFAULT_MAYBEAI_API_ATTEMPTS = 3
DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS = 5
DEFAULT_OPENCLI_CMD = "npm exec -- opencli"
DEFAULT_STORE = "店3"
DEFAULT_LOG_DIR = "artifacts/shein-activity/logs"
DEFAULT_RAW_DB_TYPE = "shein_activity"
DEFAULT_RAW_DB_WORKSHEET_SUFFIX = "活动数据"
DEFAULT_RAW_DB_SAVE_PATH = "/api/v1/tool/function_call"
DEFAULT_RAW_DB_READ_PATH = "/api/v1/tool/function_call"
DEFAULT_RAW_READ_DAYS = 30
SHEET_READ_CHUNK_ROWS = 10000
WORKSHEET_DIMENSIONS_PATH = "/api/v1/excel_v2/worksheet/dimensions"

RAW_SHEET_HEADERS = [
    "raw_db_type",
    "raw_key",
    "record_type",
    "snapshot_date",
    "store",
    "profile",
    "request_url",
    "list_request_url",
    "detail_request_url",
    "queried_insert_start_time",
    "queried_insert_end_time",
    "queried_page_size",
    "queried_type_id",
    "queried_time_zone",
    "queried_system",
    "activity_total_count",
    "activity_total_pages",
    "activity_page_num",
    "detail_total_count",
    "detail_total_pages",
    "detail_page_num",
    "activity_id",
    "activity_name",
    "activity_status",
    "activity_type_id",
    "type_id",
    "activity_type_name",
    "site",
    "country",
    "creator",
    "created_at",
    "updated_at",
    "start_time",
    "end_time",
    "terminate_time",
    "state",
    "store_code",
    "supplier_id",
    "source_store_name",
    "tool_name",
    "raw_activity_json",
    "goods_id",
    "skc",
    "image_url",
    "sku_supplier_no",
    "attend_num_sum",
    "stock_num",
    "ivt_num",
    "inventory_num",
    "goods_product_act_price",
    "goods_max_product_act_price",
    "goods_is_effective",
    "goods_failed_reason",
    "goods_state",
    "goods_is_del",
    "goods_currency",
    "goods_supply_price_new",
    "goods_supply_price",
    "goods_us_supply_price",
    "goods_eur_supply_price",
    "goods_uk_supply_price",
    "goods_mxn_supply_price",
    "is_sale_attribute",
    "pricing_type",
    "product_tag",
    "sku_count",
    "sku",
    "sku_currency",
    "sku_supply_price_new",
    "sku_product_act_price",
    "sku_max_product_act_price",
    "sku_supply_price",
    "sku_us_supply_price",
    "sku_eur_supply_price",
    "sku_uk_supply_price",
    "sku_mxn_supply_price",
    "sku_main_attr_names",
    "sku_sale_attr_names",
    "sku_attr_info_list_json",
    "goods_country_attr_info_list_json",
    "sku_info_list_json",
    "raw_detail_json",
    "raw_json",
]

RAW_DB_OMIT_HEADERS = {
    "sku_attr_info_list_json",
    "goods_country_attr_info_list_json",
    "sku_info_list_json",
    "raw_activity_json",
    "raw_detail_json",
    "raw_json",
}

RAW_DB_SHEET_HEADERS = [header for header in RAW_SHEET_HEADERS if header not in RAW_DB_OMIT_HEADERS]

SHEET_HEADERS = [
    "店铺",
    "活动名称",
    "活动规格",
    "活动商品图片",
    "活动商品skc",
    "活动商品供方货号",
    "活动时间",
    "活动开始时间",
    "活动结束时间",
    "活动终止时间",
    "状态",
]

ACTIVITY_TYPE_MAPPING = {
    "31": "限时折扣",
    "1": "店铺活动",
    "2": "平台大促",
    "9": "多买多折",
    "21": "新人专享",
}

STATE_MAPPING = {
    "3": "开启",
    "4": "已结束",
    "5": "已撤销",
    "6": "已终止",
}


class SyncError(RuntimeError):
    pass


class StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line)
        return len(data)

    def flush(self) -> None:
        if self._buffer.strip():
            self.logger.log(self.level, self._buffer.rstrip())
        self._buffer = ""

    def isatty(self) -> bool:
        return False


def resolve_repo_path(path_value: str, repo_root: Path) -> Path:
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else repo_root / path


def setup_activity_logging(args: argparse.Namespace, repo_root: Path) -> tuple[logging.Logger, list[logging.Handler], Any, Any]:
    log_dir = resolve_repo_path(getattr(args, "log_dir", DEFAULT_LOG_DIR), repo_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    logger = logging.getLogger("shein_activity_sync")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(original_stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    sys.stdout = StreamToLogger(logger, logging.INFO)
    sys.stderr = StreamToLogger(logger, logging.ERROR)
    print(f"Logging SHEIN activity sync to {log_path}")
    print(f"--- run started at {datetime.now().isoformat(timespec='seconds')} ---")
    return logger, [file_handler, console_handler], original_stdout, original_stderr


def normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_date_input(value: Any) -> str:
    text = string_value(value)
    if not text:
        return ""
    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    dashed = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    match = compact or dashed
    if not match:
        raise SyncError(f"Date must be YYYY-MM-DD or YYYYMMDD: {text}")
    year, month, day = match.groups()
    try:
        parsed = datetime(int(year), int(month), int(day))
    except ValueError as error:
        raise SyncError(f"Invalid date: {text}") from error
    return parsed.strftime("%Y-%m-%d")


def default_yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def resolve_date_range(start_date: Any, end_date: Any) -> list[str]:
    start = normalize_date_input(start_date)
    end = normalize_date_input(end_date)
    if not start and not end:
        start = end = default_yesterday()
    elif start and not end:
        end = start
    elif end and not start:
        start = end
    if start > end:
        start, end = end, start
    cursor = datetime.strptime(start, "%Y-%m-%d")
    stop = datetime.strptime(end, "%Y-%m-%d")
    days: list[str] = []
    while cursor <= stop:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days


def resolve_requested_days(args: argparse.Namespace) -> list[str]:
    crawl_last_days = getattr(args, "crawl_last_days", None)
    last_days = getattr(args, "last_days", None)
    if crawl_last_days not in (None, "") and last_days not in (None, ""):
        raise SyncError("--crawl-last-days cannot be combined with --last-days.")
    option = "--crawl-last-days" if crawl_last_days not in (None, "") else "--last-days"
    days_value = crawl_last_days if crawl_last_days not in (None, "") else last_days
    if days_value in (None, ""):
        return resolve_date_range(getattr(args, "start_date", None), getattr(args, "end_date", None))
    if getattr(args, "start_date", None):
        raise SyncError(f"{option} cannot be combined with --start-date. Use --end-date to choose the window end.")
    days = int(days_value)
    if days <= 0:
        raise SyncError(f"{option} must be a positive integer.")
    end = normalize_date_input(getattr(args, "end_date", None)) or default_yesterday()
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return resolve_date_range(start, end)


def parse_sheet_url(url: str) -> tuple[str, str | None, str]:
    match = re.search(r"/spreadsheets/d/([^/?#]+)", url)
    if not match:
        raise SyncError(f"Cannot parse document id from sheet URL: {url}")
    parsed = urllib.parse.urlparse(url)
    gid = urllib.parse.parse_qs(parsed.query).get("gid", [None])[0]
    base_uri = f"https://www.maybe.ai/docs/spreadsheets/d/{match.group(1)}"
    return match.group(1), gid, base_uri


def shell_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as error:
        raise SyncError(f"Invalid command: {command}") from error


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


def run_command(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def command_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def looks_auth_required(text: str) -> bool:
    lowered = text.lower()
    return any(
        needle in lowered
        for needle in ("auth required", "authrequired", "not logged in", "login", "登录", "session is not ready", "code=20302")
    )


def looks_retryable_cli_failure(text: str) -> bool:
    lowered = text.lower()
    return any(
        needle in lowered
        for needle in ("capture timeout", "target closed", "networkerror", "aborterror", "http 500", "http 502", "http 503", "http 504")
    )


def maybeai_token() -> str:
    for name in ("MAYBEAI_API_TOKEN", "MAYBEAI_AUTH_TOKEN", "MAYBEAI_API_KEY"):
        token = os.environ.get(name)
        if token:
            return token
    raise SyncError("Missing MaybeAI token. Set MAYBEAI_API_TOKEN, MAYBEAI_AUTH_TOKEN, or MAYBEAI_API_KEY.")


class MaybeAIClient:
    def __init__(self, args: argparse.Namespace) -> None:
        self.base_url = getattr(args, "maybeai_base_url", DEFAULT_MAYBEAI_BASE_URL).rstrip("/")
        self.token = maybeai_token()
        self.attempts = int(getattr(args, "maybeai_api_attempts", DEFAULT_MAYBEAI_API_ATTEMPTS))
        self.retry_delay = int(getattr(args, "maybeai_api_retry_delay_seconds", DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS))

    def post(self, path: str, payload: dict[str, Any], timeout: int = DEFAULT_MAYBEAI_API_TIMEOUT) -> dict[str, Any]:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            request = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < self.attempts:
                    time.sleep(self.retry_delay)
        raise SyncError(f"MaybeAI API {path} failed: {last_error}")


def build_maybeai_client(args: argparse.Namespace) -> MaybeAIClient:
    return MaybeAIClient(args)


def build_opencli_base(args: argparse.Namespace) -> list[str]:
    command = shell_words(getattr(args, "opencli_cmd", DEFAULT_OPENCLI_CMD))
    profile = getattr(args, "profile", None)
    if profile:
        command.extend(["--profile", profile])
    return command


def build_shein_login_command(opencli: list[str], args: argparse.Namespace) -> list[str]:
    command = [*opencli, "shein", "login"]
    username = getattr(args, "shein_username", None) or os.environ.get("SHEIN_USERNAME") or os.environ.get("SHEIN_USER")
    password = getattr(args, "shein_password", None) or os.environ.get("SHEIN_PASSWORD") or os.environ.get("SHEIN_PASS")
    if username:
        command.extend(["--username", username])
    if password:
        command.extend(["--password", password])
    if getattr(args, "login_wait", None):
        command.extend(["--wait", str(args.login_wait)])
    return command


def ensure_shein_session(args: argparse.Namespace, repo_root: Path, opencli: list[str]) -> None:
    if not getattr(args, "preflight_login", False):
        return
    whoami = run_command([*opencli, "shein", "whoami", "-f", "json"], repo_root, int(getattr(args, "login_timeout", 300)))
    if whoami.returncode == 0:
        return
    login = run_command(build_shein_login_command(opencli, args), repo_root, int(getattr(args, "login_timeout", 300)))
    if login.returncode != 0:
        raise SyncError(f"SHEIN login CLI failed with exit code {login.returncode}:\n{command_output(login)}")


def add_optional(command: list[str], arg_name: str, value: Any) -> None:
    if value not in (None, ""):
        command.extend([arg_name, str(value)])


def build_activity_command(args: argparse.Namespace, day: str) -> list[str]:
    command = [*shell_words(getattr(args, "opencli_cmd", DEFAULT_OPENCLI_CMD))]
    if getattr(args, "profile", None):
        command.extend(["--profile", args.profile])
    command.extend(["shein", "activity", "--snapshotDate", day, "-f", "json"])
    add_optional(command, "--insertStartTime", getattr(args, "insert_start_time", None))
    add_optional(command, "--insertEndTime", getattr(args, "insert_end_time", None))
    add_optional(command, "--typeId", getattr(args, "type_id", None))
    add_optional(command, "--system", getattr(args, "system", None))
    add_optional(command, "--timeZone", getattr(args, "time_zone", None))
    add_optional(command, "--activityIds", getattr(args, "activity_ids", None))
    add_optional(command, "--pageSize", getattr(args, "page_size", None))
    add_optional(command, "--limitActivities", getattr(args, "limit_activities", None))
    add_optional(command, "--limitRows", getattr(args, "limit_rows", None))
    add_optional(command, "--maxListPages", getattr(args, "max_list_pages", None))
    add_optional(command, "--maxDetailPages", getattr(args, "max_detail_pages", None))
    add_optional(command, "--detailConcurrency", getattr(args, "detail_concurrency", None))
    add_optional(command, "--requestDelayMinMs", getattr(args, "request_delay_min_ms", None))
    add_optional(command, "--requestDelayMaxMs", getattr(args, "request_delay_max_ms", None))
    add_optional(command, "--timeout", getattr(args, "opencli_timeout", None))
    add_optional(command, "--requestTimeout", getattr(args, "request_timeout", None))
    add_optional(command, "--retryAttempts", getattr(args, "api_retry_attempts", None))
    add_optional(command, "--retryDelayMs", getattr(args, "api_retry_delay_ms", None))
    return command


def extract_json_array(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise SyncError(f"OpenCLI output is not JSON: {error}") from error
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if isinstance(parsed, dict):
        for key in ("data", "rows", "result"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise SyncError("OpenCLI output did not contain a JSON row array.")


def fetch_shein_rows_for_day(args: argparse.Namespace, repo_root: Path, day: str, _opencli: list[str]) -> list[dict[str, Any]]:
    command = build_activity_command(args, day)
    login_cmd = build_shein_login_command(_opencli, args)
    attempts = int(getattr(args, "attempts", 3))
    last_output = ""
    for attempt in range(1, attempts + 1):
        print(f"Running SHEIN activity CLI for {day} (attempt {attempt}/{attempts}): {' '.join(shlex.quote(item) for item in command)}")
        result = run_command(command, repo_root, int(getattr(args, "cli_timeout", 3600)))
        if result.returncode == 0:
            return extract_json_array(result.stdout)
        last_output = command_output(result)
        if not looks_auth_required(last_output) and not looks_retryable_cli_failure(last_output):
            raise SyncError(f"SHEIN activity CLI failed with exit code {result.returncode}:\n{last_output}")
        if attempt < attempts and int(getattr(args, "retry_delay_seconds", 5)) > 0:
            if looks_auth_required(last_output) or getattr(args, "login_on_retry", True):
                print("Refreshing SHEIN session with login CLI before retry...")
                login = run_command(login_cmd, repo_root, int(getattr(args, "login_timeout", 300)))
                if login.returncode != 0:
                    print(f"SHEIN login refresh failed but retrying activity later:\n{command_output(login)}")
                elif int(getattr(args, "login_wait_seconds", 0)) > 0:
                    time.sleep(int(getattr(args, "login_wait_seconds", 0)))
            time.sleep(int(getattr(args, "retry_delay_seconds", 5)))
    raise SyncError(f"SHEIN activity CLI failed after {attempts} attempts:\n{last_output}")


def raw_db_worksheet_name(args: argparse.Namespace, store: str | None = None) -> str:
    explicit = string_value(getattr(args, "raw_db_worksheet_name", ""))
    if explicit:
        return explicit
    suffix = string_value(getattr(args, "raw_db_worksheet_suffix", DEFAULT_RAW_DB_WORKSHEET_SUFFIX)) or DEFAULT_RAW_DB_WORKSHEET_SUFFIX
    return f"{store or getattr(args, 'store', DEFAULT_STORE)}{suffix}"


def raw_db_uri(args: argparse.Namespace) -> str:
    return string_value(getattr(args, "raw_db_uri", "")) or DEFAULT_RAW_DB_URI


def validate_raw_db_uri(args: argparse.Namespace) -> None:
    uri = raw_db_uri(args)
    if "<" in uri or ">" in uri or "raw-activity-doc-id" in uri:
        raise SyncError(
            "raw DB URI is still a placeholder. Configure --raw-db-uri or scripts/shein-activity-prod.json before raw DB reads/writes."
        )


def build_save_table_worksheet_to_mongodb_payload(
    args: argparse.Namespace,
    *,
    data_date: str,
    uri: str,
    store: str,
    include_raw_key: bool = True,
) -> dict[str, Any]:
    profile = string_value(getattr(args, "profile", ""))
    raw_type = string_value(getattr(args, "raw_db_type", DEFAULT_RAW_DB_TYPE)) or DEFAULT_RAW_DB_TYPE
    raw_key = f"{raw_type}:{store}:{profile}:{normalize_date_input(data_date)}"
    tool_args = {
        "data_date": normalize_date_input(data_date),
        "uri": uri,
        "worksheet_name": raw_db_worksheet_name(args, store),
    }
    if include_raw_key:
        tool_args.update({
            "key": raw_key,
            "raw_key": raw_key,
            "raw_db_type": raw_type,
            "store": store,
            "profile": profile,
        })
    return {
        "app": "function_call",
        "tool_id": "excel__save_table_worksheet_to_mongodb",
        "tool_name": "save_table_worksheet_to_mongodb",
        "tool_args": tool_args,
    }


def enrich_raw_activity_rows(args: argparse.Namespace, day: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    store = getattr(args, "store", DEFAULT_STORE)
    profile = string_value(getattr(args, "profile", ""))
    raw_type = string_value(getattr(args, "raw_db_type", DEFAULT_RAW_DB_TYPE)) or DEFAULT_RAW_DB_TYPE
    raw_key = f"{raw_type}:{store}:{profile}:{day}"
    for row in rows:
        copy = dict(row)
        copy["raw_db_type"] = string_value(copy.get("raw_db_type")) or raw_type
        copy["raw_key"] = string_value(copy.get("raw_key")) or raw_key
        copy["snapshot_date"] = string_value(copy.get("snapshot_date")) or day
        copy["store"] = string_value(copy.get("store")) or store
        copy["profile"] = string_value(copy.get("profile")) or profile
        enriched.append(copy)
    if not enriched:
        enriched.append({
            "raw_db_type": raw_type,
            "raw_key": raw_key,
            "record_type": "empty_snapshot",
            "snapshot_date": day,
            "store": store,
            "profile": profile,
        })
    return enriched


def raw_rows_to_sheet_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {header: normalize_cell(row.get(header, "")) for header in RAW_DB_SHEET_HEADERS}
        for row in rows
    ]


def save_result_failed(result: dict[str, Any]) -> bool:
    return bool(result.get("success") is False or result.get("error"))


def looks_raw_key_args_unsupported(result: dict[str, Any]) -> bool:
    text = json.dumps(result, ensure_ascii=False).lower()
    return any(needle in text for needle in ("unknown", "unexpected", "unsupported", "invalid", "schema", "extra", "key"))


def save_raw_activity_rows(args: argparse.Namespace, client: MaybeAIClient | Any, day: str, rows: list[dict[str, Any]]) -> None:
    if getattr(args, "dry_run", False) or not getattr(args, "raw_db", False):
        return
    uri = raw_db_uri(args)
    worksheet = raw_db_worksheet_name(args, getattr(args, "store", DEFAULT_STORE))
    target = {"uri": uri, "worksheet_name": worksheet}
    records = raw_rows_to_sheet_records(enrich_raw_activity_rows(args, day, rows))
    print(f"Writing raw SHEIN activity worksheet for {day}: uri={uri}, worksheet={worksheet}, rows={len(rows)}")
    existing_row_count = len(records) + 1
    try:
        dimensions = client.post(WORKSHEET_DIMENSIONS_PATH, target, timeout=DEFAULT_MAYBEAI_API_TIMEOUT)
        worksheets = dimensions.get("worksheets") if isinstance(dimensions, dict) else None
        if isinstance(worksheets, list) and worksheets:
            existing_row_count = max(existing_row_count, int(worksheets[0].get("row_count") or 0))
    except Exception:
        existing_row_count = len(records) + 1
    if len(RAW_DB_SHEET_HEADERS) < len(RAW_SHEET_HEADERS):
        legacy_clear_range = (
            f"{excel_column_name(len(RAW_DB_SHEET_HEADERS) + 1)}1:"
            f"{excel_column_name(len(RAW_SHEET_HEADERS))}{max(existing_row_count, 1)}"
        )
        clear_result = client.post(
            "/api/v1/excel/update_range",
            {
                **target,
                "range_address": legacy_clear_range,
                "values": [["" for _ in range(len(RAW_SHEET_HEADERS) - len(RAW_DB_SHEET_HEADERS))]
                           for _ in range(max(existing_row_count, 1))],
            },
            timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
        )
        if clear_result.get("success") is False:
            raise SyncError(f"Raw activity worksheet legacy column clear failed for {day}:\n{json.dumps(clear_result, ensure_ascii=False)}")
    header_result = client.post(
        "/api/v1/excel/update_range",
        {**target, "range_address": f"A1:{excel_column_name(len(RAW_DB_SHEET_HEADERS))}1", "values": [RAW_DB_SHEET_HEADERS]},
        timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
    )
    if header_result.get("success") is False:
        raise SyncError(f"Raw activity worksheet header update failed for {day}:\n{json.dumps(header_result, ensure_ascii=False)}")
    write_result = client.post(
        "/api/v1/excel/update_data_keep_headers",
        {**target, "data": records, "preserve_formulas": True, "skip_recalculation": False, "start_row": 2},
        timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
    )
    if write_result.get("success") is False:
        raise SyncError(f"Raw activity worksheet write failed for {day}:\n{json.dumps(write_result, ensure_ascii=False)}")
    payload = build_save_table_worksheet_to_mongodb_payload(args, data_date=day, uri=uri, store=getattr(args, "store", DEFAULT_STORE))
    snapshot_key = f"shein_activity:{getattr(args, 'store', DEFAULT_STORE)}:{string_value(getattr(args, 'profile', ''))}:{day}"
    print(
        "Saving raw SHEIN activity worksheet to MongoDB: "
        f"day={day}, rows={len(rows)}, key={snapshot_key}, worksheet={worksheet}"
    )
    result = client.post(getattr(args, "raw_db_save_path", DEFAULT_RAW_DB_SAVE_PATH), payload, timeout=DEFAULT_MAYBEAI_API_TIMEOUT)
    if save_result_failed(result) and looks_raw_key_args_unsupported(result):
        print("Raw activity DB save rejected extended key args; retrying with legacy save_table_worksheet_to_mongodb payload.")
        legacy_payload = build_save_table_worksheet_to_mongodb_payload(
            args,
            data_date=day,
            uri=uri,
            store=getattr(args, "store", DEFAULT_STORE),
            include_raw_key=False,
        )
        result = client.post(getattr(args, "raw_db_save_path", DEFAULT_RAW_DB_SAVE_PATH), legacy_payload, timeout=DEFAULT_MAYBEAI_API_TIMEOUT)
    if save_result_failed(result):
        raise SyncError(f"Raw activity DB worksheet save failed for {day}:\n{json.dumps(result, ensure_ascii=False)}")


def fetch_and_save_shein_rows(args: argparse.Namespace, repo_root: Path, client: Any, missing_days: list[str]) -> list[dict[str, Any]]:
    if not missing_days:
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] No missing activity snapshot days; skipping OpenCLI.")
        return []
    opencli = build_opencli_base(args)
    ensure_shein_session(args, repo_root, opencli)
    all_rows: list[dict[str, Any]] = []
    for index, day in enumerate(missing_days, start=1):
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Fetching activity day {index}/{len(missing_days)}: {day}")
        rows = fetch_shein_rows_for_day(args, repo_root, day, opencli)
        all_rows.extend(enrich_raw_activity_rows(args, day, rows))
        save_raw_activity_rows(args, client, day, rows)
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Activity day completed: {day}, rows={len(rows)}")
    return all_rows


def map_activity_type(value: Any) -> Any:
    text = string_value(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return ACTIVITY_TYPE_MAPPING.get(text, normalize_cell(value))


def map_activity_state(value: Any) -> Any:
    text = string_value(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return STATE_MAPPING.get(text, normalize_cell(value))


def first_nonblank(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def format_activity_time(start: Any, end: Any) -> str:
    start_text = string_value(start)
    end_text = string_value(end)
    if start_text and end_text and start_text != end_text:
        return f"{start_text} ~ {end_text}"
    return start_text or end_text


def adapter_row_to_record(row: dict[str, Any], store: str) -> dict[str, Any]:
    start = first_nonblank(row, "start_time", "activity_start_time", "begin_time", "活动开始时间")
    end = first_nonblank(row, "end_time", "activity_end_time", "finish_time", "活动结束时间")
    type_value = first_nonblank(row, "activity_type_id", "type_id", "活动规格")
    state_value = first_nonblank(row, "state", "status", "活动状态", "状态")
    record = {
        "店铺": store,
        "活动名称": normalize_cell(first_nonblank(row, "activity_name", "act_name", "prom_name", "name", "活动名称")),
        "活动规格": map_activity_type(type_value),
        "活动商品图片": normalize_cell(first_nonblank(row, "image_url", "img_url", "活动商品图片")),
        "活动商品skc": normalize_cell(first_nonblank(row, "skc", "goods_skc", "product_skc", "活动商品skc")),
        "活动商品供方货号": normalize_cell(first_nonblank(row, "sku_supplier_no", "活动商品供方货号")),
        "活动时间": format_activity_time(start, end),
        "活动开始时间": normalize_cell(start),
        "活动结束时间": normalize_cell(end),
        "活动终止时间": normalize_cell(first_nonblank(row, "terminate_time", "terminated_time", "stop_time", "close_time", "cancel_time", "abort_time", "活动终止时间")),
        "状态": map_activity_state(state_value),
    }
    return {header: record.get(header, "") for header in SHEET_HEADERS}


def rows_to_records(rows: list[dict[str, Any]], store: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if row.get("record_type") == "empty_snapshot":
            continue
        if not first_nonblank(row, "activity_id", "activity_name", "活动名称", "活动商品skc", "skc"):
            continue
        if any(header in row for header in SHEET_HEADERS):
            records.append({header: normalize_cell(row.get(header, "")) for header in SHEET_HEADERS})
        else:
            records.append(adapter_row_to_record(row, store))
    return records


def unique_key(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        string_value(record.get("店铺")),
        string_value(record.get("活动名称")),
        string_value(record.get("活动开始时间")),
        string_value(record.get("活动商品skc")),
        string_value(record.get("活动商品供方货号")),
    )


def merge_records_by_unique_key(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for record in existing:
        merged[unique_key(record)] = record
    for record in fresh:
        merged[unique_key(record)] = record
    return list(merged.values())


def merge_records_for_store_refresh(existing: list[dict[str, Any]], fresh: list[dict[str, Any]], store: str) -> list[dict[str, Any]]:
    retained = [record for record in existing if string_value(record.get("店铺")) != store]
    return merge_records_by_unique_key(retained, fresh)


def sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda row: (string_value(row.get("店铺")), string_value(row.get("活动开始时间")), string_value(row.get("活动名称")), string_value(row.get("活动商品skc"))))


def extract_raw_snapshot_days(response: dict[str, Any]) -> set[str]:
    snapshots = response.get("snapshots")
    if snapshots is None:
        snapshots = response.get("result", {}).get("snapshots") if isinstance(response.get("result"), dict) else None
    days = set()
    for snapshot in snapshots or []:
        if isinstance(snapshot, dict) and snapshot.get("data_date"):
            days.add(normalize_date_input(snapshot.get("data_date")))
    return days


def records_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    data_date = normalize_date_input(snapshot.get("data_date"))
    raw_records = snapshot.get("records") or snapshot.get("data")
    if isinstance(raw_records, list) and all(isinstance(item, dict) for item in raw_records):
        return [dict(item, snapshot_date=item.get("snapshot_date") or data_date) for item in raw_records]
    headers = snapshot.get("headers")
    rows = snapshot.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for values in rows:
        if not isinstance(values, list):
            continue
        row = {str(header): values[index] if index < len(values) else "" for index, header in enumerate(headers) if header}
        if data_date and not row.get("snapshot_date"):
            row["snapshot_date"] = data_date
        result.append(row)
    return result


def read_raw_api_rows(_args: argparse.Namespace, _client: Any, _days: list[str], *, response: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = response.get("snapshots")
    if snapshots is None and isinstance(response.get("result"), dict):
        snapshots = response["result"].get("snapshots")
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots or []:
        if isinstance(snapshot, dict):
            rows.extend(records_from_snapshot(snapshot))
    return rows


def row_source_day(row: dict[str, Any]) -> str:
    for key in ("snapshot_date", "data_date", "dataDate", "date", "日期"):
        value = row.get(key)
        if string_value(value):
            try:
                return normalize_date_input(value)
            except SyncError:
                return ""
    return ""


def effective_raw_read_days(args: argparse.Namespace) -> int:
    return int(getattr(args, "raw_read_days", DEFAULT_RAW_READ_DAYS) or DEFAULT_RAW_READ_DAYS)


def raw_read_days_for_requested_window(_args: argparse.Namespace, requested_days: list[str]) -> int:
    if not requested_days:
        return 1
    earliest = min(normalize_date_input(day) for day in requested_days)
    latest_requested = max(normalize_date_input(day) for day in requested_days)
    anchor = max(default_yesterday(), latest_requested)
    span = (datetime.strptime(anchor, "%Y-%m-%d") - datetime.strptime(earliest, "%Y-%m-%d")).days + 1
    return max(len(requested_days), span, 1)


def build_read_recent_worksheet_snapshots_payload(args: argparse.Namespace, *, uri: str, worksheet_name: str, read_days: int | None = None) -> dict[str, Any]:
    return {
        "app": "function_call",
        "tool_id": "excel__read_recent_worksheet_snapshots",
        "tool_name": "read_recent_worksheet_snapshots",
        "tool_args": {
            "uri": uri,
            "worksheet_name": worksheet_name,
            "last_n_days": int(read_days if read_days is not None else effective_raw_read_days(args)),
        },
    }


def read_raw_api_snapshot_response(args: argparse.Namespace, client: Any, days: list[str], *, read_days: int, purpose: str) -> dict[str, Any]:
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Reading raw DB snapshots for {purpose}: days={read_days}")
    payload = build_read_recent_worksheet_snapshots_payload(
        args,
        uri=raw_db_uri(args),
        worksheet_name=raw_db_worksheet_name(args),
        read_days=read_days,
    )
    response = client.post(getattr(args, "raw_db_read_path", DEFAULT_RAW_DB_READ_PATH), payload, timeout=DEFAULT_MAYBEAI_API_TIMEOUT)
    requested = set(days)
    source_snapshots = response.get("snapshots") or response.get("result", {}).get("snapshots", [])
    filtered_snapshots = []
    for snapshot in source_snapshots:
        if not isinstance(snapshot, dict) or not requested:
            filtered_snapshots.append(snapshot)
            continue
        data_date = snapshot.get("data_date")
        if data_date and normalize_date_input(data_date) in requested:
            filtered_snapshots.append(snapshot)
    return {
        **response,
        "snapshots": filtered_snapshots,
    }


def compute_missing_days(requested_days: list[str], raw_snapshot_days: set[str], skip_existing_days: bool) -> tuple[list[str], list[str]]:
    if not skip_existing_days:
        return requested_days, []
    missing = [day for day in requested_days if day not in raw_snapshot_days]
    skipped = [day for day in requested_days if day in raw_snapshot_days]
    return missing, skipped


def latest_requested_days(requested_days: list[str]) -> list[str]:
    if not requested_days:
        return []
    normalized = [normalize_date_input(day) for day in requested_days]
    return [max(normalized)]


def build_sheet_target(args: argparse.Namespace, client: Any) -> tuple[dict[str, str], str | None]:
    doc_id, gid, base_uri = parse_sheet_url(getattr(args, "sheet_url", DEFAULT_SHEET_URL))
    worksheet_name = getattr(args, "worksheet_name", None)
    if gid and not worksheet_name:
        response = client.post("/api/v1/excel/list_worksheets", {"uri": base_uri}, timeout=30)
        for worksheet in response.get("worksheets", []):
            if str(worksheet.get("gid", worksheet.get("sheet_id", ""))) == str(gid):
                worksheet_name = worksheet.get("worksheet_name") or worksheet.get("name") or worksheet.get("title")
                break
    target_uri = f"{base_uri}?gid={gid}" if gid else base_uri
    target: dict[str, str] = {"uri": target_uri}
    if worksheet_name:
        target["worksheet_name"] = worksheet_name
    return target, worksheet_name


def excel_column_name(index: int) -> str:
    name = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


LAST_COLUMN = excel_column_name(len(SHEET_HEADERS))


def first_int_at_paths(data: Any, paths: list[tuple[str, ...]]) -> int | None:
    for path in paths:
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current in (None, ""):
            continue
        try:
            value = int(current)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def extract_worksheet_row_count(response: dict[str, Any]) -> int:
    row_count = first_int_at_paths(response, [
        ("row_count",),
        ("rowCount",),
        ("rows",),
        ("used_rows",),
        ("usedRows",),
        ("max_row",),
        ("maxRow",),
        ("data", "row_count"),
        ("data", "rowCount"),
        ("data", "rows"),
        ("data", "used_rows"),
        ("data", "usedRows"),
        ("data", "max_row"),
        ("data", "maxRow"),
        ("result", "row_count"),
        ("result", "rowCount"),
        ("result", "rows"),
        ("result", "used_rows"),
        ("result", "usedRows"),
        ("result", "max_row"),
        ("result", "maxRow"),
        ("dimensions", "row_count"),
        ("dimensions", "rowCount"),
        ("dimensions", "rows"),
        ("data", "dimensions", "row_count"),
        ("data", "dimensions", "rowCount"),
        ("data", "dimensions", "rows"),
        ("result", "dimensions", "row_count"),
        ("result", "dimensions", "rowCount"),
        ("result", "dimensions", "rows"),
    ])
    if row_count is None and isinstance(response.get("worksheets"), list):
        for worksheet in response["worksheets"]:
            if not isinstance(worksheet, dict):
                continue
            row_count = first_int_at_paths(worksheet, [
                ("row_count",),
                ("rowCount",),
                ("rows",),
                ("used_rows",),
                ("usedRows",),
                ("max_row",),
                ("maxRow",),
                ("dimensions", "row_count"),
                ("dimensions", "rowCount"),
                ("dimensions", "rows"),
                ("dimensions", "used_rows"),
                ("dimensions", "usedRows"),
                ("dimensions", "max_row"),
                ("dimensions", "maxRow"),
            ])
            if row_count is not None:
                break
    if row_count is None:
        raise SyncError(f"MaybeAI worksheet dimensions response missing row count:\n{json.dumps(response, ensure_ascii=False)}")
    return row_count


def build_worksheet_dimensions_payload(target: dict[str, str]) -> dict[str, str]:
    payload: dict[str, str] = {"uri": target["uri"]}
    if target.get("worksheet_name"):
        payload["worksheet_name"] = target["worksheet_name"]
    _doc_id, gid, _base_uri = parse_sheet_url(target["uri"])
    if gid:
        payload["gid"] = str(gid)
        payload["sheet_id"] = str(gid)
    return payload


def worksheet_dimensions_gid_only_payload(payload: dict[str, str]) -> dict[str, str] | None:
    gid = payload.get("gid") or payload.get("sheet_id")
    uri = string_value(payload.get("uri"))
    if not gid or not uri:
        return None
    return {"uri": uri, "gid": str(gid), "sheet_id": str(gid)}


def read_worksheet_row_count(client: Any, target: dict[str, str]) -> int:
    payload = build_worksheet_dimensions_payload(target)
    print("Reading worksheet dimensions for row count...")
    dimensions = client.post(WORKSHEET_DIMENSIONS_PATH, payload, timeout=30)
    if dimensions.get("success") is False:
        raise SyncError(f"MaybeAI worksheet dimensions did not succeed:\n{json.dumps(dimensions, ensure_ascii=False)}")
    try:
        row_count = extract_worksheet_row_count(dimensions)
    except SyncError:
        retry_payload = worksheet_dimensions_gid_only_payload(payload)
        if retry_payload is None:
            raise
        print("Worksheet dimensions row count missing; retrying with gid-only payload...")
        retry_dimensions = client.post(WORKSHEET_DIMENSIONS_PATH, retry_payload, timeout=30)
        if retry_dimensions.get("success") is False:
            raise SyncError(f"MaybeAI worksheet dimensions did not succeed:\n{json.dumps(retry_dimensions, ensure_ascii=False)}")
        row_count = extract_worksheet_row_count(retry_dimensions)
    print(f"Worksheet dimensions row count: {row_count}")
    return row_count


def records_from_sheet_values(values: Any, headers: list[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        return []
    effective_headers = [str(header or "").strip() for header in (headers or values[0])]
    data_rows = values if headers is not None else values[1:]
    records: list[dict[str, Any]] = []
    for raw_row in data_rows:
        if not isinstance(raw_row, list):
            continue
        if not any(string_value(cell) for cell in raw_row):
            continue
        records.append({
            header: raw_row[index] if index < len(raw_row) else ""
            for index, header in enumerate(effective_headers)
            if header
        })
    return records


def records_from_sheet_data(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [
        {header: normalize_cell(record.get(header, "")) for header in SHEET_HEADERS if header in record}
        for record in data
        if isinstance(record, dict)
    ]


def read_sheet_records(client: Any, target: dict[str, str]) -> list[dict[str, Any]]:
    row_count = max(1, read_worksheet_row_count(client, target))
    records: list[dict[str, Any]] = []
    start = 1
    first_chunk = True
    while start <= row_count:
        if first_chunk:
            end = min(row_count, SHEET_READ_CHUNK_ROWS + 1)
        else:
            end = min(row_count, start + SHEET_READ_CHUNK_ROWS - 1)
        range_address = f"A{start}:{LAST_COLUMN}{end}"
        print(f"Reading existing rows from {range_address}...")
        payload = {**target, "range_address": range_address}
        response = client.post("/api/v1/excel/read_sheet", payload, timeout=DEFAULT_MAYBEAI_API_TIMEOUT)
        if response.get("success") is False:
            raise SyncError(f"MaybeAI read_sheet did not succeed:\n{json.dumps(response, ensure_ascii=False)}")
        chunk_records = records_from_sheet_values(response.get("values", []), headers=None if first_chunk else SHEET_HEADERS)
        if not chunk_records:
            chunk_records = records_from_sheet_data(response.get("data", []))
        records.extend(chunk_records)
        if first_chunk:
            start = SHEET_READ_CHUNK_ROWS + 2
            first_chunk = False
        else:
            start = end + 1
    return records


def ensure_headers(args: argparse.Namespace, client: Any, target: dict[str, str]) -> None:
    if not getattr(args, "ensure_headers", False):
        return
    client.post(
        "/api/v1/excel/update_range",
        {**target, "range_address": f"A1:{LAST_COLUMN}1", "values": [SHEET_HEADERS]},
        timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
    )


def write_sheet_records(client: Any, target: dict[str, str], records: list[dict[str, Any]], _args: argparse.Namespace) -> None:
    print(f"Writing {len(records)} merged activity rows with update_data_keep_headers...")
    result = client.post(
        "/api/v1/excel/update_data_keep_headers",
        {
            **target,
            "data": [{header: row.get(header, "") for header in SHEET_HEADERS} for row in records],
            "preserve_formulas": True,
            "skip_recalculation": False,
            "start_row": 2,
        },
        timeout=DEFAULT_MAYBEAI_API_TIMEOUT,
    )
    if result.get("success") is False:
        raise SyncError(f"MaybeAI activity update_data_keep_headers did not succeed:\n{json.dumps(result, ensure_ascii=False)}")
    print("Write result:", json.dumps({
        "spreadsheet_url": result.get("spreadsheet_url") or getattr(_args, "sheet_url", ""),
        "range": result.get("range"),
        "rows": len(records),
        "write_api": "update_data_keep_headers",
    }, ensure_ascii=False))


def run_sync(args: argparse.Namespace, repo_root: Path) -> None:
    requested_days = resolve_requested_days(args)
    skip_sheet_write = bool(getattr(args, "skip_sheet_write", False))
    if skip_sheet_write and not getattr(args, "raw_db", False) and not getattr(args, "dry_run", False):
        raise SyncError("--skip-sheet-write requires --raw-db so crawl-only runs do not drop fetched rows.")
    uses_raw_db = (
        bool(getattr(args, "skip_existing_days", True))
        or bool(getattr(args, "raw_db", False))
        or getattr(args, "etl_source", "fresh") == "raw-api"
    )
    if uses_raw_db and hasattr(args, "raw_db_uri"):
        validate_raw_db_uri(args)
    print(f"SHEIN activity sync store/profile: store={getattr(args, 'store', DEFAULT_STORE)}, profile={getattr(args, 'profile', None) or '<default>'}")
    print(f"SHEIN activity crawl date range: {requested_days[0]} to {requested_days[-1]}")
    print(f"SHEIN activity target sheet URL: {getattr(args, 'sheet_url', DEFAULT_SHEET_URL)}")
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 1/6: preparing MaybeAI target and reading existing ETL rows.")
    needs_client = (
        bool(getattr(args, "skip_existing_days", True))
        or getattr(args, "etl_source", "fresh") == "raw-api"
        or (bool(getattr(args, "raw_db", False)) and not bool(getattr(args, "dry_run", False)))
        or not skip_sheet_write
    )
    client = build_maybeai_client(args) if needs_client else None
    target = None
    existing_records: list[dict[str, Any]] = []
    if client is not None and not skip_sheet_write:
        target, _worksheet_name = build_sheet_target(args, client)
        print(
            "MaybeAI activity sheet read/write target: "
            f"uri={target['uri']}"
            f"{f', worksheet={_worksheet_name}' if _worksheet_name else ''}"
        )
        if not getattr(args, "clear_worksheet_data", False):
            existing_records = read_sheet_records(client, target)
            print(f"Loaded {len(existing_records)} existing activity sheet rows.")

    plan_response: dict[str, Any] = {}
    plan_raw_rows: list[dict[str, Any]] = []
    if client is not None and getattr(args, "skip_existing_days", True):
        plan_read_days = raw_read_days_for_requested_window(args, requested_days)
        plan_response = read_raw_api_snapshot_response(args, client, requested_days, read_days=plan_read_days, purpose="crawl plan")
        plan_raw_rows = read_raw_api_rows(args, client, requested_days, response=plan_response)
    raw_days = extract_raw_snapshot_days(plan_response)
    missing_days, skipped_days = compute_missing_days(requested_days, raw_days, bool(getattr(args, "skip_existing_days", True)))
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Date plan from raw DB: requested={len(requested_days)}, missing={len(missing_days)}, skipped={len(skipped_days)}")
    if skipped_days:
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Skipped existing raw DB days: {', '.join(skipped_days)}")
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 2/6 completed: date plan ready.")

    fetch_args = args
    if getattr(args, "etl_source", "fresh") == "raw-api" and missing_days and not getattr(args, "raw_db", False):
        fetch_args = argparse.Namespace(**vars(args))
        fetch_args.raw_db = True
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Raw API source is missing {len(missing_days)} day(s); crawling and saving missing raw DB snapshots.")
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 3/6: fetching SHEIN activity rows and saving raw DB per day.")
    fetched_rows = fetch_and_save_shein_rows(fetch_args, repo_root, client, missing_days)
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 3/6 completed: fetched adapter_rows={len(fetched_rows)}.")
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 4/6 completed: raw daily rows are saved immediately after each day fetch when enabled.")

    if skip_sheet_write:
        print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Skip sheet write enabled; fetched_days={len(missing_days)}, skipped_days={len(skipped_days)}")
        return

    adapter_rows: list[dict[str, Any]]
    export_days = latest_requested_days(requested_days)
    export_day_set = set(export_days)
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Sheet export day: {', '.join(export_days) if export_days else '<none>'}")
    if getattr(args, "etl_source", "fresh") == "raw-api":
        assert client is not None
        display_read_days = raw_read_days_for_requested_window(args, export_days)
        display_response = read_raw_api_snapshot_response(args, client, export_days, read_days=display_read_days, purpose="sheet ETL latest day")
        existing_raw_rows = [
            row
            for row in read_raw_api_rows(args, client, export_days, response=display_response)
            if not export_day_set or row_source_day(row) in export_day_set
        ]
        display_raw_days = extract_raw_snapshot_days(display_response)
        fetched_display_rows = [
            row
            for row in fetched_rows
            if row_source_day(row) in export_day_set and row_source_day(row) not in display_raw_days
        ]
        if fetched_display_rows:
            print(
                f"[{getattr(args, 'store', DEFAULT_STORE)}] Sheet ETL raw DB read is missing "
                f"{len(fetched_display_rows)} fresh row(s); including freshly crawled rows for display fallback."
            )
        adapter_rows = [*existing_raw_rows, *fetched_display_rows]
    else:
        adapter_rows = [
            row
            for row in [*plan_raw_rows, *fetched_rows]
            if not export_day_set or row_source_day(row) in export_day_set
        ]

    print(
        f"[{getattr(args, 'store', DEFAULT_STORE)}] ETL source rows combined: "
        f"raw_db_rows={len(adapter_rows) - len(fetched_rows)}, fresh_rows={len(fetched_rows)}, total={len(adapter_rows)}."
    )
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 5/6: running ETL mapping.")
    records = rows_to_records(adapter_rows, getattr(args, "store", DEFAULT_STORE))
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 5/6 completed: etl_rows={len(records)}.")
    if records:
        print("Sample ETL row:", json.dumps(records[0], ensure_ascii=False))
    if getattr(args, "dry_run", False):
        print(f"Dry run enabled; etl_rows={len(records)}")
        return
    if not records and getattr(args, "etl_source", "fresh") != "raw-api":
        print("No SHEIN activity ETL rows; skipping Sheet write.")
        return
    assert client is not None and target is not None
    print(f"[{getattr(args, 'store', DEFAULT_STORE)}] Step 6/6: writing ETL sheet.")
    ensure_headers(args, client, target)
    if getattr(args, "clear_worksheet_data", False):
        merged = records
    elif getattr(args, "etl_source", "fresh") == "raw-api":
        merged = merge_records_for_store_refresh(existing_records, records, getattr(args, "store", DEFAULT_STORE))
    else:
        merged = merge_records_by_unique_key(existing_records, records)
    sheet_records = sort_records(merged)
    write_sheet_records(client, target, sheet_records, args)
    print(
        f"[{getattr(args, 'store', DEFAULT_STORE)}] Store completed: fetched_days={len(missing_days)}, "
        f"skipped_days={len(skipped_days)}, adapter_rows={len(adapter_rows)}, etl_rows={len(records)}, sheet_rows={len(sheet_records)}."
    )


def load_store_configs(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults", {})
    stores = payload.get("stores", [])
    if not isinstance(defaults, dict) or not isinstance(stores, list):
        raise SyncError("Store config must contain object defaults and list stores.")
    result: list[dict[str, Any]] = []
    for store in stores:
        if not isinstance(store, dict):
            continue
        merged = {**defaults, **store}
        if not merged.get("store") or not merged.get("profile"):
            raise SyncError("Each store config requires store and profile.")
        result.append(merged)
    return result


def args_for_store_config(args: argparse.Namespace, config: dict[str, Any]) -> argparse.Namespace:
    scoped = argparse.Namespace(**vars(args))
    override_keys = set(getattr(args, "_cli_override_keys", set()) or set())
    for key, value in config.items():
        attr = key.replace("-", "_")
        if attr == "worksheet_name" and "sheet_url" in override_keys and "worksheet_name" not in override_keys:
            continue
        if attr in override_keys:
            continue
        setattr(scoped, attr, value)
    return scoped


def run_for_args(args: argparse.Namespace, repo_root: Path) -> None:
    if getattr(args, "store_config", None):
        configs = load_store_configs(Path(args.store_config))
        filters = set(getattr(args, "store_key", []) or [])
        configs = [
            config
            for config in configs
            if not filters or ({str(config.get("key", "")), str(config.get("store", ""))} & filters)
        ]
        if not configs:
            raise SyncError("No store configs matched --store-key.")
        print(f"Running SHEIN activity for {len(configs)} configured stores.")
        for index, config in enumerate(configs, start=1):
            print(f"=== configured store {index}/{len(configs)}: store={config.get('store')}, profile={config.get('profile')} ===")
            scoped = args_for_store_config(args, config)
            run_sync(scoped, repo_root)
            print(f"=== configured store completed {index}/{len(configs)}: store={scoped.store} ===")
    else:
        run_sync(args, repo_root)


def run_self_test() -> int:
    test_path = Path(__file__).with_name("sync-shein-activity-to-sheet.test.py")
    spec = importlib.util.spec_from_file_location("sync_shein_activity_to_sheet_tests", test_path)
    if spec is None or spec.loader is None:
        raise SyncError(f"Cannot load self-test file: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import unittest

    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync SHEIN activity rows into a MaybeAI sheet.")
    parser.add_argument("--start-date", dest="start_date")
    parser.add_argument("--end-date", dest="end_date")
    parser.add_argument("--crawl-last-days", type=int)
    parser.add_argument("--last-days", type=int)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--profile")
    parser.add_argument("--store-config")
    parser.add_argument("--store-key", action="append", default=[])
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    parser.add_argument("--worksheet-name")
    parser.add_argument("--raw-db", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--raw-db-type", default=DEFAULT_RAW_DB_TYPE)
    parser.add_argument("--raw-db-uri", default=DEFAULT_RAW_DB_URI)
    parser.add_argument("--raw-db-worksheet-name")
    parser.add_argument("--raw-db-worksheet-suffix", default=DEFAULT_RAW_DB_WORKSHEET_SUFFIX)
    parser.add_argument("--raw-db-save-path", default=DEFAULT_RAW_DB_SAVE_PATH)
    parser.add_argument("--raw-db-read-path", default=DEFAULT_RAW_DB_READ_PATH)
    parser.add_argument("--raw-read-days", type=int, default=DEFAULT_RAW_READ_DAYS)
    parser.add_argument("--etl-source", choices=["fresh", "raw-api"], default="fresh")
    parser.add_argument("--sheet-display-days", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--skip-existing-days", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-sheet-write", action="store_true")
    parser.add_argument("--clear-worksheet-data", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--ensure-headers", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--opencli-cmd", default=DEFAULT_OPENCLI_CMD)
    parser.add_argument("--insert-start-time")
    parser.add_argument("--insert-end-time")
    parser.add_argument("--type-id", type=int)
    parser.add_argument("--system")
    parser.add_argument("--time-zone")
    parser.add_argument("--activity-ids")
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--limit-activities", type=int)
    parser.add_argument("--limit-rows", type=int)
    parser.add_argument("--max-list-pages", type=int)
    parser.add_argument("--max-detail-pages", type=int)
    parser.add_argument("--detail-concurrency", type=int)
    parser.add_argument("--request-delay-min-ms", type=int)
    parser.add_argument("--request-delay-max-ms", type=int)
    parser.add_argument("--request-timeout", type=int, default=60)
    parser.add_argument("--api-retry-attempts", type=int, default=3)
    parser.add_argument("--api-retry-delay-ms", type=int, default=1000)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=int, default=5)
    parser.add_argument("--cli-timeout", type=int, default=3600)
    parser.add_argument("--opencli-timeout", type=int, default=3600)
    parser.add_argument("--login-timeout", type=int, default=300)
    parser.add_argument("--preflight-login", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--maybeai-base-url", default=DEFAULT_MAYBEAI_BASE_URL)
    parser.add_argument("--maybeai-api-attempts", type=int, default=DEFAULT_MAYBEAI_API_ATTEMPTS)
    parser.add_argument("--maybeai-api-retry-delay-seconds", type=int, default=DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS)
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--login-on-retry", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--login-wait-seconds", type=int, default=2)
    parser.add_argument("--shein-username")
    parser.add_argument("--shein-password")
    parser.add_argument("--self-test", action="store_true")
    return parser


def mark_cli_overrides(args: argparse.Namespace, argv: list[str]) -> None:
    overrides: set[str] = set()
    mapping = {
        "--raw-read-days": "raw_read_days",
        "--sheet-url": "sheet_url",
        "--worksheet-name": "worksheet_name",
    }
    for token in argv:
        key = token.split("=", 1)[0]
        if key in mapping:
            overrides.add(mapping[key])
    args._cli_override_keys = overrides


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(raw_argv)
    mark_cli_overrides(args, raw_argv)
    if args.self_test:
        return run_self_test()
    repo_root = Path(__file__).resolve().parents[1]
    for env_file in getattr(args, "env_file", []) or []:
        load_env_file(Path(env_file).expanduser())
    logger, log_handlers, original_stdout, original_stderr = setup_activity_logging(args, repo_root)
    try:
        run_for_args(args, repo_root)
        return 0
    except subprocess.TimeoutExpired as error:
        print(f"Timed out while running: {' '.join(error.cmd)}", file=sys.stderr)
        return 1
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        print(f"--- run finished at {datetime.now().isoformat(timespec='seconds')} ---")
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        for handler in log_handlers:
            logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
