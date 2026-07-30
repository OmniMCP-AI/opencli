#!/usr/bin/env python3
"""Sync SHEIN daily traffic rows into a MaybeAI spreadsheet."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import http.client
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shlex
import socket
import ssl
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_SHEET_URL = "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0"
DEFAULT_MAYBEAI_BASE_URL = "https://play-be.omnimcp.ai"
DEFAULT_MAYBEAI_API_TIMEOUT = 300
DEFAULT_MAYBEAI_API_ATTEMPTS = 3
DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS = 5
DEFAULT_OPENCLI_CMD = "npm exec -- opencli"
DEFAULT_STORE = "店3"
DEFAULT_LOG_DIR = "artifacts/shein-daily-traffic/logs"
DEFAULT_RAW_DB_TYPE = "shein_daily_traffic"
DEFAULT_RAW_DB_SAVE_PATH = "/api/v1/tool/function_call"
DEFAULT_RAW_DB_SAVE_TOOL_ID = "excel__save_table_worksheet_to_mongodb"
DEFAULT_RAW_DB_SAVE_TOOL_NAME = "save_table_worksheet_to_mongodb"
DEFAULT_RAW_DB_READ_PATH = "/api/v1/tool/function_call"
DEFAULT_RAW_DB_READ_TOOL_ID = "excel__read_recent_worksheet_snapshots"
DEFAULT_RAW_DB_READ_TOOL_NAME = "read_recent_worksheet_snapshots"
DEFAULT_RAW_DB_URI = "https://www.maybe.ai/docs/spreadsheets/d/6a69d73b0e55e966f026dee3?gid=0"
DEFAULT_RAW_DB_WORKSHEET_SUFFIX = "每日流量"
DEFAULT_RAW_READ_DAYS = 30

RAW_SHEET_HEADERS = [
    "date",
    "queried_start_date",
    "queried_end_date",
    "total_count",
    "page_num",
    "request_url",
    "goods_name",
    "img_url",
    "spu",
    "skc",
    "sku_supplier_no",
    "new_goods_tag",
    "layer_name",
    "onsale_flag",
    "sale_flag",
    "multicolor_flag",
    "goods_uv_idx",
    "eps_uv_idx",
    "bounce_uv_idx",
    "bounce_rate",
    "search_click_cnt",
    "like_cnt",
    "cart_uv_idx",
    "cart_pv_idx",
    "gds_cart_ctr_idx",
    "pay_uv_idx",
    "pay_order_cnt",
    "gmv",
    "gds_pay_ctr_idx",
    "sale_uv_idx",
    "sale_cnt",
    "sale_gmv",
    "gds_sale_ctr_idx",
    "confirm_ctr_idx",
    "total_quality_level",
    "total_comment_cnt",
    "bad_comment_cnt",
    "bad_comment_rate",
    "return_order_cnt",
    "return_qty",
    "new_cate_1_name",
    "new_cate_2_name",
    "new_cate_3_name",
    "new_cate_4_name",
    "brand",
    "list_name",
    "list_type",
    "list_rank",
    "prom_tag",
    "prom_names",
    "prom_ids",
    "prom_inf_ing_json",
    "right_campaign_json",
    "raw_json",
]

SHEET_HEADERS = [
    "站点",
    "店铺",
    "日期",
    "商品编号",
    "商品",
    "商品当前状态",
    "规格编号",
    "规格名称",
    "规格当前状态",
    "商品货号",
    "主商品货号",
    "商品访客（访问）",
    "商品页面访客",
    "跳出商品页面的访客数",
    "商品跳出率",
    "搜索点击数",
    "赞",
    "商品访客（添加至购物车）",
    "件数 (加入购物车）",
    "转化率 (加入购物车率)",
    "买家数（已下单）",
    "件数（已下单）",
    "销售额（已下单）",
    "转化率（已下单）",
    "买家数（已确认订单）",
    "件数（已确认订单）",
    "一级分类",
    "二级分类",
    "三级分类",
    "四级分类",
]

UNIQUE_KEY_FIELDS = ["店铺", "日期", "商品货号", "主商品货号", "供应商SKU"]
SKIP_KEY_FIELDS = ["店铺", "日期"]
JSON_BLOB_FIELDS = {"每日流量明细JSON", "活动信息JSON", "权益活动JSON", "原始JSON", "raw_json"}


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


def setup_daily_logging(args: argparse.Namespace, repo_root: Path) -> tuple[logging.Logger, list[logging.Handler], Any, Any]:
    log_dir = resolve_repo_path(args.log_dir, repo_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    logger = logging.getLogger("shein_daily_traffic_sync")
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
    print(f"Logging SHEIN daily traffic sync to {log_path}")
    print(f"--- run started at {datetime.now().isoformat(timespec='seconds')} ---")
    return logger, [file_handler, console_handler], original_stdout, original_stderr


def excel_column_name(index: int) -> str:
    if index <= 0:
        raise ValueError("Excel column index must be positive.")
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


LAST_COLUMN = excel_column_name(len(SHEET_HEADERS))
RAW_LAST_COLUMN = excel_column_name(len(RAW_SHEET_HEADERS))


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


STORE_CONFIG_ALIASES = {
    "storeName": "store",
    "store_name": "store",
    "opencliProfile": "profile",
    "opencli_profile": "profile",
    "sheetUrl": "sheet_url",
    "sheet-url": "sheet_url",
    "worksheetName": "worksheet_name",
    "worksheet-name": "worksheet_name",
    "sheetDisplayDays": "sheet_display_days",
    "sheet-display-days": "sheet_display_days",
    "rawDbUri": "raw_db_uri",
    "raw-db-uri": "raw_db_uri",
    "rawDbWorksheetName": "raw_db_worksheet_name",
    "raw-db-worksheet-name": "raw_db_worksheet_name",
}

STORE_CONFIG_ALLOWED_KEYS = {
    "store",
    "profile",
    "sheet_url",
    "worksheet_name",
    "sheet_display_days",
    "raw_db_uri",
    "raw_db_worksheet_name",
}


def normalize_store_config_mapping(raw: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = STORE_CONFIG_ALIASES.get(str(key), str(key))
        if normalized_key in {"key", "id", "enabled"} or normalized_key in STORE_CONFIG_ALLOWED_KEYS:
            normalized[normalized_key] = value
    return normalized


def load_store_configs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SyncError(f"Store config file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SyncError(f"Invalid store config JSON: {path}: {error}") from error

    defaults: dict[str, Any] = {}
    stores: Any = payload
    if isinstance(payload, dict):
        raw_defaults = payload.get("defaults")
        defaults = normalize_store_config_mapping(raw_defaults) if isinstance(raw_defaults, dict) else {}
        stores = payload.get("stores")
    if not isinstance(stores, list):
        raise SyncError("Store config must be a JSON array or an object with a stores array.")

    configs: list[dict[str, Any]] = []
    for index, item in enumerate(stores, start=1):
        if not isinstance(item, dict):
            raise SyncError(f"Store config entry #{index} must be an object.")
        config = {**defaults, **normalize_store_config_mapping(item)}
        if config.get("enabled") is False:
            continue
        if not str(config.get("store", "") or "").strip():
            raise SyncError(f"Store config entry #{index} is missing store.")
        if not str(config.get("profile", "") or "").strip():
            raise SyncError(f"Store config entry #{index} is missing profile.")
        configs.append(config)
    return configs


def filter_store_configs(configs: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    selected = {str(key).strip() for key in keys if str(key).strip()}
    if not selected:
        return configs
    return [
        config
        for config in configs
        if str(config.get("key", "")).strip() in selected
        or str(config.get("id", "")).strip() in selected
        or str(config.get("store", "")).strip() in selected
    ]


def args_for_store_config(args: argparse.Namespace, config: dict[str, Any]) -> argparse.Namespace:
    values = dict(vars(args))
    if not values:
        values = {
            key: getattr(args, key)
            for key in dir(args)
            if not key.startswith("_") and not callable(getattr(args, key))
        }
    scoped = argparse.Namespace(**values)
    for key in STORE_CONFIG_ALLOWED_KEYS:
        value = config.get(key)
        if value is not None and value != "":
            setattr(scoped, key, value)
    return scoped


def maybeai_token() -> str:
    for name in ("MAYBEAI_API_TOKEN", "MAYBEAI_AUTH_TOKEN", "MAYBEAI_API_KEY"):
        token = os.environ.get(name)
        if token:
            return token
    raise SyncError("Missing MaybeAI token. Set MAYBEAI_API_TOKEN, MAYBEAI_AUTH_TOKEN, or MAYBEAI_API_KEY.")


def parse_sheet_url(url: str) -> tuple[str, str | None]:
    match = re.search(r"/spreadsheets/d/([^/?#]+)", url)
    if not match:
        raise SyncError(f"Cannot parse document id from sheet URL: {url}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return match.group(1), query.get("gid", [None])[0]


def shell_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as error:
        raise SyncError(f"Invalid command: {command}") from error


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
    needles = [
        "authrequired",
        "auth required",
        "not logged in",
        "login",
        "登录",
        "session is not ready",
        "returned an html/auth page",
        "code=20302",
    ]
    return any(needle in lowered for needle in needles)


def looks_retryable_cli_failure(text: str) -> bool:
    lowered = text.lower()
    needles = [
        "failed to fetch",
        "browser exec command timed out",
        "capture timeout",
        "search button not found",
        "inspected target navigated or closed",
        "target closed",
        "aborterror",
        "networkerror",
        "fetch failed after",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    ]
    return any(needle in lowered for needle in needles)


def build_opencli_base(args: argparse.Namespace) -> list[str]:
    opencli = shell_words(args.opencli_cmd)
    if args.profile:
        opencli.extend(["--profile", args.profile])
    return opencli


def shein_credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.shein_username or os.environ.get("SHEIN_USERNAME") or os.environ.get("SHEIN_USER") or ""
    password = args.shein_password or os.environ.get("SHEIN_PASSWORD") or os.environ.get("SHEIN_PASS") or ""
    return username, password


def build_shein_login_command(opencli: list[str], args: argparse.Namespace) -> list[str]:
    login_cmd = [*opencli, "shein", "login"]
    username, password = shein_credentials(args)
    if username:
        login_cmd.extend(["--username", username])
    if password:
        login_cmd.extend(["--password", password])
    return login_cmd


def ensure_shein_session(args: argparse.Namespace, repo_root: Path, opencli: list[str]) -> None:
    if not args.preflight_login:
        return

    whoami_cmd = [*opencli, "shein", "whoami", "-f", "json"]
    last_output = ""
    for attempt in range(1, args.attempts + 1):
        print(f"Checking SHEIN session with whoami (attempt {attempt}/{args.attempts})...")
        whoami = run_command(whoami_cmd, repo_root, args.login_timeout)
        if whoami.returncode == 0:
            print("SHEIN session is ready.")
            return

        output = command_output(whoami)
        auth_required = looks_auth_required(output)
        retryable = looks_retryable_cli_failure(output)
        if not auth_required and not retryable and not args.login_on_retry:
            raise SyncError(f"SHEIN whoami failed with exit code {whoami.returncode}:\n{output}")

        print("SHEIN session is not ready; running login CLI before fetching daily traffic...")
        login = run_command(build_shein_login_command(opencli, args), repo_root, args.login_timeout)
        last_output = command_output(login)
        if login.returncode == 0:
            if args.login_wait_seconds > 0:
                time.sleep(args.login_wait_seconds)
            verify = run_command(whoami_cmd, repo_root, args.login_timeout)
            if verify.returncode == 0:
                print("SHEIN session is ready after login.")
                return
            last_output = command_output(verify)
        elif not looks_retryable_cli_failure(last_output) and not looks_auth_required(last_output):
            raise SyncError(f"SHEIN login CLI failed with exit code {login.returncode}:\n{last_output}")

        if attempt < args.attempts and args.retry_delay_seconds > 0:
            print(f"SHEIN session preflight failed; retrying in {args.retry_delay_seconds}s...")
            time.sleep(args.retry_delay_seconds)

    raise SyncError(f"SHEIN login/session preflight failed after {args.attempts} attempts:\n{last_output}")


def extract_json_array(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    candidates = [stripped]
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            if not all(isinstance(item, dict) for item in parsed):
                raise SyncError("SHEIN CLI returned a JSON array, but not all items are objects.")
            return parsed
    raise SyncError(f"SHEIN CLI did not return a JSON array. Output preview:\n{stripped[:1000]}")


def normalize_date_input(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.match(r"^(\d{4})(\d{2})(\d{2})$", text)
    dashed = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    match = compact or dashed
    if not match:
        raise SyncError(f"Date must be YYYY-MM-DD or YYYYMMDD. Received: {text!r}")
    year, month, day = (int(part) for part in match.groups())
    try:
        parsed = datetime(year, month, day)
    except ValueError as error:
        raise SyncError(f"Invalid date: {text!r}") from error
    return parsed.strftime("%Y-%m-%d")


def default_yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def resolve_date_range(start_date: Any = None, end_date: Any = None) -> list[str]:
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
    dates = []
    while cursor <= stop:
        dates.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return dates


def yyyymmdd(value: Any) -> str:
    return normalize_date_input(value).replace("-", "")


def fetch_shein_rows_for_day(args: argparse.Namespace, repo_root: Path, day: str, opencli: list[str]) -> list[dict[str, Any]]:
    daily_cmd = [*opencli, "shein", "daily-traffic", "--startDate", day, "--endDate", day, "-f", "json"]
    if args.area_cd:
        daily_cmd.extend(["--areaCd", args.area_cd])
    if args.country_site:
        daily_cmd.extend(["--countrySite", args.country_site])
    if args.page_size is not None:
        daily_cmd.extend(["--pageSize", str(args.page_size)])
    if args.limit is not None:
        daily_cmd.extend(["--limit", str(args.limit)])
    if args.max_pages is not None:
        daily_cmd.extend(["--maxPages", str(args.max_pages)])
    if args.opencli_timeout is not None:
        daily_cmd.extend(["--timeout", str(args.opencli_timeout)])
    if args.request_timeout is not None:
        daily_cmd.extend(["--requestTimeout", str(args.request_timeout)])
    if args.api_retry_attempts is not None:
        daily_cmd.extend(["--retryAttempts", str(args.api_retry_attempts)])
    if args.api_retry_delay_ms is not None:
        daily_cmd.extend(["--retryDelayMs", str(args.api_retry_delay_ms)])

    login_cmd = build_shein_login_command(opencli, args)
    last_output = ""
    for attempt in range(1, args.attempts + 1):
        print(
            f"Running SHEIN daily traffic CLI for {day} (attempt {attempt}/{args.attempts}): "
            f"{' '.join(shlex.quote(item) for item in daily_cmd)}"
        )
        result = run_command(daily_cmd, repo_root, args.cli_timeout)
        if result.returncode == 0:
            return extract_json_array(result.stdout)

        last_output = command_output(result)
        auth_required = looks_auth_required(last_output)
        retryable = looks_retryable_cli_failure(last_output)
        if not auth_required and not retryable:
            raise SyncError(f"SHEIN daily traffic CLI failed with exit code {result.returncode}:\n{last_output}")

        if auth_required or args.login_on_retry:
            print("Refreshing SHEIN session with login CLI before retry...")
            login = run_command(login_cmd, repo_root, args.login_timeout)
            if login.returncode != 0:
                login_output = command_output(login)
                if auth_required or attempt >= args.attempts:
                    raise SyncError(f"SHEIN login CLI failed with exit code {login.returncode}:\n{login_output}")
                print(f"SHEIN login refresh failed but retrying daily traffic later:\n{login_output}")
            elif args.login_wait_seconds > 0:
                time.sleep(args.login_wait_seconds)

        if attempt < args.attempts and args.retry_delay_seconds > 0:
            time.sleep(args.retry_delay_seconds)

    raise SyncError(f"SHEIN daily traffic CLI failed after {args.attempts} attempts:\n{last_output}")


def fetch_shein_rows(args: argparse.Namespace, repo_root: Path, missing_days: list[str]) -> list[dict[str, Any]]:
    if not missing_days:
        return []
    opencli = build_opencli_base(args)
    ensure_shein_session(args, repo_root, opencli)
    rows: list[dict[str, Any]] = []
    for day in missing_days:
        rows.extend(fetch_shein_rows_for_day(args, repo_root, day, opencli))
    return rows


def normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return ""
    return value


def is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip() == ""


def parse_json_object_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_json_array_cell(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def first_nonblank(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if not is_blank_value(value):
            return value
    return ""


def join_raw_campaign_field(items: Any, field: str) -> str:
    if not isinstance(items, list):
        return ""
    values = []
    for item in items:
        if isinstance(item, dict) and not is_blank_value(item.get(field)):
            values.append(str(item.get(field)))
    return " | ".join(values)


def derived_bad_comment_count(row: dict[str, Any], raw: dict[str, Any]) -> Any:
    explicit = first_nonblank(row, "bad_comment_cnt", "差评数")
    if not is_blank_value(explicit):
        return explicit
    raw_explicit = first_nonblank(raw, "payBadCommentCnt", "badCommentCnt")
    if not is_blank_value(raw_explicit):
        return raw_explicit
    total_value = first_nonblank(row, "total_comment_cnt", "商品评价数")
    if is_blank_value(total_value):
        total_value = raw.get("totalCommentCnt", "")
    rate_value = first_nonblank(row, "bad_comment_rate", "差评率")
    if is_blank_value(rate_value):
        rate_value = raw.get("badCommentRate", "")
    total = number_or_none(total_value)
    rate = number_or_none(rate_value)
    if total is None or rate is None:
        return ""
    if rate > 1:
        rate = rate / 100
    return int(round(total * rate))


def adapter_row_from_raw_sources(row: dict[str, Any]) -> dict[str, Any]:
    raw = parse_json_object_cell(row.get("raw_json") or row.get("原始JSON") or row.get("每日流量明细JSON"))
    prom_campaign = raw.get("promCampaign") if isinstance(raw.get("promCampaign"), dict) else {}
    prom_items = parse_json_array_cell(row.get("prom_inf_ing_json") or row.get("活动信息JSON")) or (
        prom_campaign.get("promInfIng") if isinstance(prom_campaign.get("promInfIng"), list) else []
    )
    right_campaign = parse_json_array_cell(row.get("right_campaign_json") or row.get("权益活动JSON")) or (
        raw.get("rightCampaign") if isinstance(raw.get("rightCampaign"), list) else prom_campaign.get("rightCampaign", [])
    )
    adapter = {header: row.get(header, "") for header in RAW_SHEET_HEADERS if header in row}
    supplement = {
        "date": first_nonblank(row, "date", "日期"),
        "queried_start_date": first_nonblank(row, "queried_start_date", "查询开始日期"),
        "queried_end_date": first_nonblank(row, "queried_end_date", "查询结束日期"),
        "total_count": first_nonblank(row, "total_count", "抓取总数"),
        "page_num": first_nonblank(row, "page_num", "页码"),
        "request_url": first_nonblank(row, "request_url", "请求URL"),
        "goods_name": first_nonblank(row, "goods_name", "商品") or raw.get("goodsName", ""),
        "img_url": first_nonblank(row, "img_url", "商品图片") or raw.get("imgUrl") or raw.get("imageUrl", ""),
        "spu": first_nonblank(row, "spu", "主商品货号") or raw.get("spu", ""),
        "skc": first_nonblank(row, "skc", "商品货号") or raw.get("skc", ""),
        "sku_supplier_no": first_nonblank(row, "sku_supplier_no", "供应商SKU") or raw.get("skuSupplierNo", ""),
        "new_goods_tag": first_nonblank(row, "new_goods_tag", "是否新品") or raw.get("newGoodsTag", ""),
        "layer_name": first_nonblank(row, "layer_name", "层级名称") or raw.get("layerNm", ""),
        "onsale_flag": first_nonblank(row, "onsale_flag", "上架状态") or raw.get("onsaleFlag", ""),
        "sale_flag": first_nonblank(row, "sale_flag", "商品当前状态") or raw.get("saleFlag", ""),
        "multicolor_flag": first_nonblank(row, "multicolor_flag", "是否多色") or raw.get("multicolorFlag", ""),
        "goods_uv_idx": first_nonblank(row, "goods_uv_idx", "商品访客（访问）") or raw.get("goodsUvIdx", ""),
        "eps_uv_idx": first_nonblank(row, "eps_uv_idx", "商品页面访客") or raw.get("epsUvIdx", ""),
        "bounce_uv_idx": first_nonblank(row, "bounce_uv_idx", "跳出商品页面的访客数") or raw.get("bounceUvIdx", ""),
        "bounce_rate": first_nonblank(row, "bounce_rate", "商品跳出率") or raw.get("bounceRate", ""),
        "search_click_cnt": first_nonblank(row, "search_click_cnt", "搜索点击数") or raw.get("searchClickCnt", ""),
        "like_cnt": first_nonblank(row, "like_cnt", "赞") or raw.get("likeCnt", ""),
        "cart_uv_idx": first_nonblank(row, "cart_uv_idx", "商品访客（添加至购物车）") or raw.get("cartUvIdx", ""),
        "cart_pv_idx": first_nonblank(row, "cart_pv_idx", "件数 (加入购物车）") or raw.get("cartPvIdx", ""),
        "gds_cart_ctr_idx": first_nonblank(row, "gds_cart_ctr_idx", "转化率 (加入购物车率)") or raw.get("gdsCartCtrIdx", ""),
        "pay_uv_idx": first_nonblank(row, "pay_uv_idx", "买家数（已下单）") or raw.get("payUvIdx", ""),
        "pay_order_cnt": first_nonblank(row, "pay_order_cnt", "件数（已下单）") or raw.get("payOrderCnt", ""),
        "gmv": first_nonblank(row, "gmv", "销售额（已下单）") or raw.get("gmv", ""),
        "gds_pay_ctr_idx": first_nonblank(row, "gds_pay_ctr_idx", "转化率（已下单）") or raw.get("gdsPayCtrIdx", ""),
        "sale_uv_idx": first_nonblank(row, "sale_uv_idx", "买家数（已确认订单）") or raw.get("saleUvIdx", ""),
        "sale_cnt": first_nonblank(row, "sale_cnt", "件数（已确认订单）") or raw.get("saleCnt", ""),
        "sale_gmv": first_nonblank(row, "sale_gmv", "销售额（已确认订单）") or raw.get("saleGmv", ""),
        "gds_sale_ctr_idx": first_nonblank(row, "gds_sale_ctr_idx", "转化率（已确认订单）") or raw.get("gdsSaleCtrIdx", ""),
        "confirm_ctr_idx": first_nonblank(row, "confirm_ctr_idx", "转化率 (将确定)") or raw.get("confirmCtrIdx", ""),
        "total_quality_level": first_nonblank(row, "total_quality_level", "商品质量等级") or raw.get("totalQualityLevel", ""),
        "total_comment_cnt": first_nonblank(row, "total_comment_cnt", "商品评价数") or raw.get("totalCommentCnt", ""),
        "bad_comment_cnt": derived_bad_comment_count(row, raw),
        "bad_comment_rate": first_nonblank(row, "bad_comment_rate", "差评率") or raw.get("badCommentRate", ""),
        "return_order_cnt": first_nonblank(row, "return_order_cnt", "退货订单数") or raw.get("returnOrderCnt", ""),
        "return_qty": first_nonblank(row, "return_qty", "退货件数") or raw.get("returnQty", ""),
        "new_cate_1_name": first_nonblank(row, "new_cate_1_name", "一级分类") or raw.get("newCate1Nm", ""),
        "new_cate_2_name": first_nonblank(row, "new_cate_2_name", "二级分类") or raw.get("newCate2Nm", ""),
        "new_cate_3_name": first_nonblank(row, "new_cate_3_name", "三级分类") or raw.get("newCate3Nm", ""),
        "new_cate_4_name": first_nonblank(row, "new_cate_4_name", "四级分类") or raw.get("newCate4Nm", ""),
        "brand": first_nonblank(row, "brand", "品牌") or raw.get("brand", ""),
        "list_name": first_nonblank(row, "list_name", "榜单名称") or raw.get("listName", ""),
        "list_type": first_nonblank(row, "list_type", "榜单类型") or raw.get("listType", ""),
        "list_rank": first_nonblank(row, "list_rank", "榜单排名") or raw.get("listRank", ""),
        "prom_tag": first_nonblank(row, "prom_tag", "活动标签") or prom_campaign.get("promTag", ""),
        "prom_names": first_nonblank(row, "prom_names", "活动名称") or join_raw_campaign_field(prom_items, "promNm"),
        "prom_ids": first_nonblank(row, "prom_ids", "活动ID") or join_raw_campaign_field(prom_items, "promId"),
        "prom_inf_ing_json": prom_items,
        "right_campaign_json": right_campaign,
        "raw_json": raw,
    }
    for key, value in supplement.items():
        if not is_blank_value(value) or is_blank_value(adapter.get(key)):
            adapter[key] = value
    return adapter


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def map_status_flag(value: Any) -> Any:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "在售"}:
        return "在售"
    if text in {"0", "false", "no", "非在售"}:
        return "非在售"
    return normalize_cell(value)


def map_yes_no(value: Any) -> Any:
    text = str(value).strip().lower()
    if text in {"", "none", "null"}:
        return ""
    if text in {"0", "false", "no", "否"}:
        return "否"
    if text in {"1", "true", "yes", "是"}:
        return "是"
    return normalize_cell(value)


def ratio(numerator: Any, denominator: Any) -> Any:
    num = number_or_none(numerator)
    den = number_or_none(denominator)
    if num is None or den in (None, 0):
        return ""
    value = num / den
    return int(value) if value.is_integer() else value


def default_zero_when_blank(value: Any) -> Any:
    return 0 if str(value or "").strip() == "" else normalize_cell(value)


def adapter_row_to_record(row: dict[str, Any], store: str) -> dict[str, Any]:
    record = {
        "站点": "SHEIN",
        "店铺": store,
        "日期": normalize_date_input(row.get("date")),
        "查询开始日期": str(row.get("queried_start_date") or yyyymmdd(row.get("date"))),
        "查询结束日期": str(row.get("queried_end_date") or yyyymmdd(row.get("date"))),
        "商品编号": normalize_cell(row.get("goods_id", "")),
        "商品": normalize_cell(row.get("goods_name", "")),
        "商品图片": normalize_cell(row.get("img_url", "")),
        "商品当前状态": map_status_flag(row.get("sale_flag", "")),
        "规格编号": normalize_cell(row.get("sku_code", "")),
        "规格名称": normalize_cell(row.get("sku_name", "")),
        "规格当前状态": normalize_cell(row.get("sku_status", "")),
        "商品货号": normalize_cell(row.get("skc", "")),
        "主商品货号": normalize_cell(row.get("spu", "")),
        "供应商SKU": normalize_cell(row.get("sku_supplier_no", "")),
        "上架状态": map_status_flag(row.get("onsale_flag", "")),
        "是否新品": map_yes_no(row.get("new_goods_tag", "")),
        "是否多色": map_yes_no(row.get("multicolor_flag", "")),
        "商品访客（访问）": normalize_cell(row.get("goods_uv_idx", "")),
        "商品页面访客": normalize_cell(row.get("eps_uv_idx", "")),
        "点击率": ratio(row.get("goods_uv_idx", ""), row.get("eps_uv_idx", "")),
        "跳出商品页面的访客数": normalize_cell(row.get("bounce_uv_idx", "")),
        "商品跳出率": normalize_cell(row.get("bounce_rate", "")),
        "搜索点击数": normalize_cell(row.get("search_click_cnt", "")),
        "赞": normalize_cell(row.get("like_cnt", "")),
        "商品访客（添加至购物车）": normalize_cell(row.get("cart_uv_idx", "")),
        "件数 (加入购物车）": normalize_cell(row.get("cart_pv_idx", "")),
        "转化率 (加入购物车率)": normalize_cell(row.get("gds_cart_ctr_idx", "")),
        "买家数（已下单）": normalize_cell(row.get("pay_uv_idx", "")),
        "件数（已下单）": default_zero_when_blank(row.get("pay_order_cnt", "")),
        "销售额（已下单）": normalize_cell(row.get("gmv", "")),
        "转化率（已下单）": normalize_cell(row.get("gds_pay_ctr_idx", "")),
        "买家数（已确认订单）": normalize_cell(row.get("sale_uv_idx", "")),
        "件数（已确认订单）": default_zero_when_blank(row.get("sale_cnt", "")),
        "销售额（已确认订单）": normalize_cell(row.get("sale_gmv", "")),
        "转化率（已确认订单）": normalize_cell(row.get("gds_sale_ctr_idx", "")),
        "转化率 (将确定)": normalize_cell(row.get("confirm_ctr_idx", "")),
        "商品质量等级": normalize_cell(row.get("total_quality_level", "")),
        "商品评价数": normalize_cell(row.get("total_comment_cnt", "")),
        "差评数": normalize_cell(row.get("bad_comment_cnt", "")),
        "差评率": normalize_cell(row.get("bad_comment_rate", "")),
        "退货订单数": normalize_cell(row.get("return_order_cnt", "")),
        "退货件数": normalize_cell(row.get("return_qty", "")),
        "一级分类": normalize_cell(row.get("new_cate_1_name", "")),
        "二级分类": normalize_cell(row.get("new_cate_2_name", "")),
        "三级分类": normalize_cell(row.get("new_cate_3_name", "")),
        "四级分类": normalize_cell(row.get("new_cate_4_name", "")),
        "品牌": normalize_cell(row.get("brand", "")),
        "层级名称": normalize_cell(row.get("layer_name", "")),
        "榜单名称": normalize_cell(row.get("list_name", "")),
        "榜单类型": normalize_cell(row.get("list_type", "")),
        "榜单排名": normalize_cell(row.get("list_rank", "")),
        "活动标签": normalize_cell(row.get("prom_tag", "")),
        "活动名称": normalize_cell(row.get("prom_names", "")),
        "活动ID": normalize_cell(row.get("prom_ids", "")),
        "请求URL": normalize_cell(row.get("request_url", "")),
        "抓取总数": normalize_cell(row.get("total_count", "")),
        "页码": normalize_cell(row.get("page_num", "")),
        "store_name": store,
        "queried_start_date": str(row.get("queried_start_date") or yyyymmdd(row.get("date"))),
        "queried_end_date": str(row.get("queried_end_date") or yyyymmdd(row.get("date"))),
    }
    return {header: record.get(header, "") for header in SHEET_HEADERS}


def rows_to_records(rows: list[dict[str, Any]], store: str) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        if any(header in row for header in SHEET_HEADERS):
            records.append(sheet_row_to_record(row, store))
        else:
            records.append(adapter_row_to_record(row, store))
    return records


def is_blank_record(record: dict[str, Any]) -> bool:
    return all(str(value or "").strip() == "" for value in record.values())


def normalize_sheet_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for header in SHEET_HEADERS:
        normalized[header] = normalize_cell(record.get(header, ""))
    return normalized


def sheet_row_to_record(row: dict[str, Any], store: str) -> dict[str, Any]:
    record = normalize_sheet_record(row)
    supplemental = adapter_row_to_record(adapter_row_from_raw_sources(row), store)
    for header, value in supplemental.items():
        if is_blank_value(record.get(header)) and not is_blank_value(value):
            record[header] = value
    date_value = normalize_date_input(record.get("日期") or row.get("date"))
    record["站点"] = record.get("站点") or "SHEIN"
    record["店铺"] = record.get("店铺") or store
    record["日期"] = date_value
    record["查询开始日期"] = record.get("查询开始日期") or yyyymmdd(date_value)
    record["查询结束日期"] = record.get("查询结束日期") or yyyymmdd(date_value)
    record["store_name"] = record.get("store_name") or record["店铺"]
    record["queried_start_date"] = record.get("queried_start_date") or record["查询开始日期"]
    record["queried_end_date"] = record.get("queried_end_date") or record["查询结束日期"]
    return record


def records_from_sheet_values(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        return []
    raw_headers = values[0]
    if not isinstance(raw_headers, list):
        return []
    headers = [str(header or "").strip() for header in raw_headers]
    index_by_header = {header: index for index, header in enumerate(headers) if header}

    records: list[dict[str, Any]] = []
    for raw_row in values[1:]:
        if not isinstance(raw_row, list):
            continue
        record = {}
        for header in SHEET_HEADERS:
            index = index_by_header.get(header)
            record[header] = normalize_cell(raw_row[index]) if index is not None and index < len(raw_row) else ""
        records.append(record)
    return records


def record_unique_key(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field, "")).strip() for field in UNIQUE_KEY_FIELDS)


def day_skip_key(record: dict[str, Any]) -> tuple[str, str]:
    return str(record.get("店铺", "")).strip(), normalize_date_input(record.get("日期")) if str(record.get("日期", "")).strip() else ""


def compute_missing_days(days: list[str], existing_records: list[dict[str, Any]], store: str, skip_existing_days: bool = True) -> tuple[list[str], list[str]]:
    if not skip_existing_days:
        return list(days), []
    existing_keys = {day_skip_key(record) for record in existing_records if str(record.get("店铺", "")).strip() and str(record.get("日期", "")).strip()}
    missing = []
    skipped = []
    for day in days:
        if (store, day) in existing_keys:
            skipped.append(day)
        else:
            missing.append(day)
    return missing, skipped


def merge_records_by_unique_key(existing_records: list[dict[str, Any]], fresh_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    key_order: list[tuple[str, ...]] = []
    for record in [*existing_records, *fresh_records]:
        normalized = normalize_sheet_record(record)
        if is_blank_record(normalized):
            continue
        key = record_unique_key(normalized)
        if key not in merged_by_key:
            key_order.append(key)
        merged_by_key[key] = normalized
    return [merged_by_key[key] for key in key_order]


def sort_records_for_write(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: (
        -int(str(record.get("日期", "0000-00-00")).replace("-", "") or "0"),
        str(record.get("商品货号", "")).strip(),
        str(record.get("主商品货号", "")).strip(),
        str(record.get("供应商SKU", "")).strip(),
        str(record.get("店铺", "")).strip(),
    ))


def sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sort_records_for_write(records)


def positive_int_or_none(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise SyncError(f"{name} must be a positive integer.") from error
    if parsed <= 0:
        raise SyncError(f"{name} must be a positive integer.")
    return parsed


def filter_records_for_sheet_display(records: list[dict[str, Any]], requested_days: list[str], sheet_display_days: Any) -> list[dict[str, Any]]:
    display_days = positive_int_or_none(sheet_display_days, "--sheet-display-days")
    if display_days is None:
        return list(records)
    end = normalize_date_input(requested_days[-1])
    start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=display_days - 1)
    start = start_dt.strftime("%Y-%m-%d")

    visible: list[dict[str, Any]] = []
    for record in records:
        try:
            day = normalize_date_input(record.get("日期"))
        except SyncError:
            continue
        if start <= day <= end:
            visible.append(record)
    return visible


def traffic_rows_summary(rows: list[dict[str, Any]], records: list[dict[str, Any]], requested_days: list[str], missing_days: list[str], skipped_days: list[str]) -> dict[str, Any]:
    by_date = Counter(str(row.get("date") or row.get("日期") or "").strip() for row in rows if str(row.get("date") or row.get("日期") or "").strip())
    return {
        "requested_days": requested_days,
        "fetched_days": missing_days,
        "skipped_days": skipped_days,
        "adapter_rows": len(rows),
        "etl_rows": len(records),
        "by_date": dict(sorted(by_date.items())),
        "sample_keys": [record_unique_key(record) for record in records[:3]],
    }


def days_with_etl_records(records: list[dict[str, Any]], store: str, candidate_days: list[str]) -> list[str]:
    candidate_set = set(candidate_days)
    seen: set[str] = set()
    days: list[str] = []
    for record in records:
        record_store, day = day_skip_key(record)
        if record_store != store or day not in candidate_set or day in seen:
            continue
        seen.add(day)
        days.append(day)
    return days


def raw_profile_key(profile: Any) -> str:
    value = str(profile or "").strip()
    return value or "default"


def build_raw_daily_document(rows: list[dict[str, Any]], args: argparse.Namespace, day: str, fetched_at: str | None = None) -> dict[str, Any]:
    normalized_day = normalize_date_input(day)
    profile = raw_profile_key(getattr(args, "profile", ""))
    source = str(getattr(args, "raw_db_type", DEFAULT_RAW_DB_TYPE) or DEFAULT_RAW_DB_TYPE).strip()
    store = str(getattr(args, "store", "") or "").strip()
    return {
        "schema_version": 1,
        "source": source,
        "raw_key": f"{source}:{store}:{profile}:{normalized_day}",
        "store": store,
        "profile": profile,
        "date": normalized_day,
        "queried_start_date": yyyymmdd(normalized_day),
        "queried_end_date": yyyymmdd(normalized_day),
        "row_count": len(rows),
        "rows": rows,
        "fetched_at": fetched_at or datetime.now().isoformat(timespec="seconds"),
    }


def json_cell(value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return normalize_cell(value)


def raw_rows_to_sheet_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        record = {}
        for header in RAW_SHEET_HEADERS:
            value = row.get(header, "")
            record[header] = json_cell(value) if header in {"prom_inf_ing_json", "right_campaign_json", "raw_json"} else normalize_cell(value)
        records.append(record)
    return records


def raw_db_worksheet_name(args: argparse.Namespace, store: str) -> str:
    explicit = str(getattr(args, "raw_db_worksheet_name", "") or "").strip()
    if explicit:
        return explicit
    suffix = str(getattr(args, "raw_db_worksheet_suffix", DEFAULT_RAW_DB_WORKSHEET_SUFFIX) or "").strip()
    return f"{store}{suffix}"


def raw_db_uri(args: argparse.Namespace) -> str:
    return str(getattr(args, "raw_db_uri", "") or DEFAULT_RAW_DB_URI).strip()


def build_save_table_worksheet_to_mongodb_payload(args: argparse.Namespace, data_date: str, uri: str, store: str) -> dict[str, Any]:
    return {
        "app": "function_call",
        "tool_id": DEFAULT_RAW_DB_SAVE_TOOL_ID,
        "tool_name": DEFAULT_RAW_DB_SAVE_TOOL_NAME,
        "tool_args": {
            "data_date": normalize_date_input(data_date),
            "uri": uri,
            "worksheet_name": raw_db_worksheet_name(args, store),
        },
    }


def build_read_recent_worksheet_snapshots_payload(args: argparse.Namespace, uri: str, worksheet_name: str) -> dict[str, Any]:
    return {
        "app": "function_call",
        "tool_id": DEFAULT_RAW_DB_READ_TOOL_ID,
        "tool_name": DEFAULT_RAW_DB_READ_TOOL_NAME,
        "tool_args": {
            "uri": uri,
            "worksheet_name": worksheet_name,
            "last_n_days": int(getattr(args, "raw_read_days", DEFAULT_RAW_READ_DAYS) or DEFAULT_RAW_READ_DAYS),
        },
    }


def group_rows_by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            day = normalize_date_input(row.get("date"))
        except SyncError:
            day = ""
        if day:
            grouped.setdefault(day, []).append(row)
    return grouped


def write_raw_worksheet_for_day(args: argparse.Namespace, client: "MaybeAIClient", day: str, rows: list[dict[str, Any]]) -> tuple[str, str]:
    uri = raw_db_uri(args)
    if not uri:
        raise SyncError("--raw-db requires a raw DB staging URI.")
    worksheet_name = raw_db_worksheet_name(args, args.store)
    target = {"uri": uri, "worksheet_name": worksheet_name}
    header_range = f"A1:{RAW_LAST_COLUMN}1"
    print(f"Writing raw SHEIN daily traffic worksheet for {day}: uri={uri}, worksheet={worksheet_name}, rows={len(rows)}")
    header_result = client.post("/api/v1/excel/update_range", {**target, "range_address": header_range, "values": [RAW_SHEET_HEADERS]})
    if header_result.get("success") is False:
        raise SyncError(f"Raw worksheet header update failed for {day}:\n{json.dumps(header_result, ensure_ascii=False)}")

    records = raw_rows_to_sheet_records(rows)
    if not records:
        records = [{header: "" for header in RAW_SHEET_HEADERS}]
    write_result = client.post("/api/v1/excel/update_data_keep_headers", {
        **target,
        "data": records,
        "preserve_formulas": True,
        "skip_recalculation": False,
        "start_row": 2,
    })
    if write_result.get("success") is False:
        raise SyncError(f"Raw worksheet write failed for {day}:\n{json.dumps(write_result, ensure_ascii=False)}")
    return uri, worksheet_name


def save_raw_daily_rows(args: argparse.Namespace, client: "MaybeAIClient", day: str, rows: list[dict[str, Any]]) -> None:
    document = build_raw_daily_document(rows, args, day)
    uri, worksheet_name = write_raw_worksheet_for_day(args, client, day, rows)
    payload = build_save_table_worksheet_to_mongodb_payload(args, data_date=day, uri=uri, store=args.store)
    doc_id, _ = parse_sheet_url(uri)
    snapshot_key = f"{doc_id}:{worksheet_name}:{normalize_date_input(day)}"
    print(
        "Saving raw SHEIN daily traffic worksheet to MongoDB: "
        f"day={day}, rows={len(rows)}, raw_key={document['raw_key']}, "
        f"snapshot_key={snapshot_key}, worksheet={worksheet_name}"
    )
    result = client.post(args.raw_db_save_path, payload)
    if result.get("success") is False or result.get("error"):
        raise SyncError(f"Raw DB worksheet save failed for {day}:\n{json.dumps(result, ensure_ascii=False)}")


def save_raw_days(args: argparse.Namespace, client: "MaybeAIClient", days: list[str], rows: list[dict[str, Any]]) -> None:
    if not args.raw_db or args.dry_run:
        return
    by_date = group_rows_by_date(rows)
    for day in days:
        save_raw_daily_rows(args, client, day, by_date.get(day, []))


def extract_raw_api_rows(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        candidates = response
    elif isinstance(response, dict):
        candidates = []
        payload = response.get("result") if isinstance(response.get("result"), dict) else response
        if isinstance(payload, dict) and isinstance(payload.get("snapshots"), list):
            rows: list[dict[str, Any]] = []
            for snapshot in payload["snapshots"]:
                if not isinstance(snapshot, dict):
                    continue
                rows.extend(records_from_headers_and_rows(snapshot.get("headers"), snapshot.get("rows")))
            return rows
        for key in ("rows", "data", "records", "items"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            candidates = [payload["data"]]
    else:
        candidates = []

    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        nested_rows = data.get("rows") if isinstance(data, dict) else None
        if isinstance(nested_rows, list):
            rows.extend(row for row in nested_rows if isinstance(row, dict))
        elif "date" in item or "skc" in item or "raw_json" in item:
            rows.append(item)
    return rows


def records_from_headers_and_rows(headers: Any, rows: Any) -> list[dict[str, Any]]:
    if not isinstance(headers, list) or not isinstance(rows, list):
        return []
    normalized_headers = [str(header or "").strip() for header in headers]
    records: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            records.append(row)
            continue
        if not isinstance(row, list):
            continue
        record = {}
        for index, header in enumerate(normalized_headers):
            if header:
                record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def raw_api_date_window(requested_days: list[str], read_days: int) -> tuple[str, str]:
    end = normalize_date_input(requested_days[-1])
    start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=max(1, read_days) - 1)
    return start_dt.strftime("%Y-%m-%d"), end


def read_raw_api_rows(args: argparse.Namespace, client: "MaybeAIClient", requested_days: list[str]) -> list[dict[str, Any]]:
    if not args.raw_db_read_path:
        raise SyncError("--etl-source raw-api requires --raw-db-read-path.")
    uri = raw_db_uri(args)
    worksheet_name = raw_db_worksheet_name(args, args.store)
    payload = build_read_recent_worksheet_snapshots_payload(args, uri=uri, worksheet_name=worksheet_name)
    print(f"Reading raw SHEIN daily traffic worksheet snapshots: uri={uri}, worksheet={worksheet_name}, last_n_days={args.raw_read_days}")
    response = client.post(args.raw_db_read_path, payload)
    rows = extract_raw_api_rows(response)
    print(f"Loaded {len(rows)} raw SHEIN daily traffic rows from API.")
    return rows


class MaybeAIClient:
    def __init__(self, base_url: str, token: str, attempts: int = DEFAULT_MAYBEAI_API_ATTEMPTS, retry_delay_seconds: int = DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS) -> None:
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
                    raise SyncError(f"MaybeAI API {path} failed with {last_error}") from error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, http.client.HTTPException) as error:
                last_error = str(error)
                if attempt >= self.attempts:
                    raise SyncError(f"MaybeAI API {path} failed after {self.attempts} attempts: {last_error}") from error

            if self.retry_delay_seconds > 0:
                print(f"MaybeAI API {path} failed on attempt {attempt}/{self.attempts}; retrying in {self.retry_delay_seconds}s...")
                time.sleep(self.retry_delay_seconds)

        raise SyncError(f"MaybeAI API {path} failed after {self.attempts} attempts: {last_error}")


def build_maybeai_client(args: argparse.Namespace) -> MaybeAIClient:
    return MaybeAIClient(
        args.maybeai_base_url,
        maybeai_token(),
        attempts=args.maybeai_api_attempts,
        retry_delay_seconds=args.maybeai_api_retry_delay_seconds,
    )


def resolve_worksheet_name(client: MaybeAIClient, doc_id: str, gid: str | None) -> str | None:
    if gid is None:
        return None
    payload = {"uri": f"https://www.maybe.ai/docs/spreadsheets/d/{doc_id}"}
    data = client.post("/api/v1/excel/list_worksheets", payload, timeout=30)
    for worksheet in data.get("worksheets", []):
        candidates = {
            str(worksheet.get("gid", "")),
            str(worksheet.get("sheet_id", "")),
            str(worksheet.get("index", "")),
        }
        if str(gid) in candidates:
            return (
                worksheet.get("worksheet_name")
                or worksheet.get("title")
                or worksheet.get("name")
                or worksheet.get("sheet_name")
            )
    return None


def build_sheet_target(args: argparse.Namespace, client: MaybeAIClient) -> tuple[dict[str, Any], str | None]:
    doc_id, gid = parse_sheet_url(args.sheet_url)
    worksheet_name = args.worksheet_name or resolve_worksheet_name(client, doc_id, gid)
    uri = f"https://www.maybe.ai/docs/spreadsheets/d/{doc_id}"
    if gid is not None:
        uri = f"{uri}?gid={gid}"
    target: dict[str, Any] = {"uri": uri}
    if worksheet_name:
        target["worksheet_name"] = worksheet_name
    return target, worksheet_name


def read_sheet_records(client: MaybeAIClient, target: dict[str, Any], read_range: str | None = None) -> list[dict[str, Any]]:
    read_payload = {**target}
    if read_range:
        read_payload["range_address"] = read_range
    print(f"Reading existing rows from {read_range or 'entire worksheet'}...")
    read_result = client.post("/api/v1/excel/read_sheet", read_payload)
    if read_result.get("success") is False:
        raise SyncError(f"MaybeAI read_sheet did not succeed:\n{json.dumps(read_result, ensure_ascii=False)}")
    existing_records = records_from_sheet_values(read_result.get("values", []))
    if existing_records:
        return existing_records
    return [
        normalize_sheet_record(record)
        for record in read_result.get("data", [])
        if isinstance(record, dict)
    ]


def ensure_headers(args: argparse.Namespace, client: MaybeAIClient, target: dict[str, Any]) -> None:
    if not args.ensure_headers:
        return
    header_range = f"A1:{LAST_COLUMN}1"
    header_payload = {**target, "range_address": header_range, "values": [SHEET_HEADERS]}
    print(f"Ensuring header row {header_range}...")
    header_result = client.post("/api/v1/excel/update_range", header_payload)
    if header_result.get("success") is False:
        raise SyncError(f"MaybeAI header update did not succeed:\n{json.dumps(header_result, ensure_ascii=False)}")


def write_sheet_records(client: MaybeAIClient, target: dict[str, Any], records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    data_range = f"A2:{LAST_COLUMN}{len(records) + 1}" if records else f"A2:{LAST_COLUMN}2"
    print(f"Writing {len(records)} merged rows with update_data_keep_headers...")
    write_payload = {
        **target,
        "data": records,
        "preserve_formulas": True,
        "skip_recalculation": False,
        "start_row": 2,
    }
    write_result = client.post("/api/v1/excel/update_data_keep_headers", write_payload)
    if write_result.get("success") is False:
        raise SyncError(f"MaybeAI update_data_keep_headers did not succeed:\n{json.dumps(write_result, ensure_ascii=False)}")
    print("Write result:", json.dumps({
        "spreadsheet_url": write_result.get("spreadsheet_url") or args.sheet_url,
        "range": write_result.get("range") or data_range,
        "rows": len(records),
        "write_api": "update_data_keep_headers",
    }, ensure_ascii=False))


def verify_written_days(client: MaybeAIClient, target: dict[str, Any], args: argparse.Namespace, fetched_days: list[str]) -> None:
    if not fetched_days:
        return
    visible = read_sheet_records(client, target, args.read_range)
    visible_keys = {day_skip_key(record) for record in visible}
    missing = [day for day in fetched_days if (args.store, day) not in visible_keys]
    if missing:
        raise SyncError(f"Write verification failed; fetched store/day rows not visible: {missing}")
    print(f"Verified fetched days are visible: {', '.join(fetched_days)}")


def read_existing_for_sync(args: argparse.Namespace, client: MaybeAIClient, target: dict[str, Any]) -> list[dict[str, Any]]:
    records = read_sheet_records(client, target, args.read_range)
    print(f"Loaded {len(records)} existing sheet rows.")
    return records


def run_sync(args: argparse.Namespace, repo_root: Path) -> None:
    requested_days = resolve_date_range(args.start_date, args.end_date)
    print(f"SHEIN daily traffic sync store/profile: store={args.store}, profile={args.profile or '<default>'}")
    print(f"SHEIN daily traffic date range: {requested_days[0]} to {requested_days[-1]}")
    print(f"SHEIN daily traffic target sheet URL: {args.sheet_url}")

    existing_records: list[dict[str, Any]] = []
    client: MaybeAIClient | None = None
    target: dict[str, Any] | None = None
    worksheet_name: str | None = None

    if not args.dry_run or args.skip_existing_days or (args.raw_db and not args.dry_run) or args.etl_source == "raw-api":
        client = build_maybeai_client(args)
        if not args.dry_run or args.skip_existing_days:
            target, worksheet_name = build_sheet_target(args, client)
            print(
                "MaybeAI daily traffic sheet read/write target: "
                f"uri={target['uri']}"
                f"{f', worksheet={worksheet_name}' if worksheet_name else ''}"
            )
            existing_records = [] if args.clear_worksheet_data else read_existing_for_sync(args, client, target)

    missing_days, skipped_days = compute_missing_days(requested_days, existing_records, args.store, args.skip_existing_days)
    print(f"Date plan: requested={len(requested_days)}, missing={len(missing_days)}, skipped={len(skipped_days)}")
    if skipped_days:
        print(f"Skipped existing store/day rows: {', '.join(skipped_days)}")

    adapter_rows = [] if args.etl_source == "raw-api" else fetch_shein_rows(args, repo_root, missing_days)
    if client is not None and args.etl_source != "raw-api":
        save_raw_days(args, client, missing_days, adapter_rows)
    if args.etl_source == "raw-api":
        if client is None:
            client = build_maybeai_client(args)
        adapter_rows = read_raw_api_rows(args, client, requested_days)
    records = rows_to_records(adapter_rows, args.store)
    summary = traffic_rows_summary(adapter_rows, records, requested_days, missing_days, skipped_days)
    print("SHEIN daily traffic summary:", json.dumps(summary, ensure_ascii=False))
    if records:
        sample = {header: records[0].get(header, "") for header in SHEET_HEADERS if header not in JSON_BLOB_FIELDS}
        print("Sample ETL row:", json.dumps(sample, ensure_ascii=False))

    if args.dry_run:
        print("Dry run enabled; skipping MaybeAI sheet write.")
        return
    if not records:
        print("No fresh SHEIN daily traffic rows; skipping MaybeAI sheet merge/write.")
        return
    assert client is not None and target is not None
    ensure_headers(args, client, target)
    merged_records = records if args.clear_worksheet_data else merge_records_by_unique_key(existing_records, records)
    merged_records = sort_records(merged_records)
    display_records = filter_records_for_sheet_display(merged_records, requested_days, args.sheet_display_days)
    if args.sheet_display_days:
        print(f"Sheet display window: last {args.sheet_display_days} day(s), rows={len(display_records)}")
    write_sheet_records(client, target, display_records, args)
    display_fresh_records = filter_records_for_sheet_display(records, requested_days, args.sheet_display_days)
    verify_written_days(client, target, args, days_with_etl_records(display_fresh_records, args.store, missing_days))


def run_self_test() -> int:
    test_path = Path(__file__).with_name("sync-shein-daily-traffic-to-sheet.test.py")
    spec = importlib.util.spec_from_file_location("sync_shein_daily_traffic_to_sheet_tests", test_path)
    if spec is None or spec.loader is None:
        raise SyncError(f"Cannot load self-test file: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import unittest

    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync SHEIN daily traffic rows into a MaybeAI sheet.")
    parser.add_argument("--start-date", dest="start_date", help="Start date, YYYY-MM-DD or YYYYMMDD. Default: yesterday.")
    parser.add_argument("--end-date", dest="end_date", help="End date, YYYY-MM-DD or YYYYMMDD. Default: start-date or yesterday.")
    parser.add_argument("--area-cd", dest="area_cd", help="Optional SHEIN areaCd forwarded to OpenCLI.")
    parser.add_argument("--country-site", dest="country_site", help="Optional SHEIN countrySite forwarded to OpenCLI, comma-separated.")
    parser.add_argument("--page-size", dest="page_size", type=int, help="Optional SHEIN daily traffic pageSize.")
    parser.add_argument("--limit", type=int, help="Optional SHEIN daily traffic row limit per fetched day.")
    parser.add_argument("--max-pages", dest="max_pages", type=int, help="Optional bounded page count per fetched day.")
    parser.add_argument("--store", default=DEFAULT_STORE, help=f"Value for 店铺/store_name. Default: {DEFAULT_STORE}")
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL, help="MaybeAI spreadsheet URL with gid.")
    parser.add_argument("--worksheet-name", help="Optional worksheet name override.")
    parser.add_argument("--read-range", help="Optional existing data range to read before merging. Omitted by default so MaybeAI returns the whole worksheet.")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help=f"Directory for daily log files. Default: {DEFAULT_LOG_DIR}")
    parser.add_argument("--maybeai-base-url", default=DEFAULT_MAYBEAI_BASE_URL, help="MaybeAI API base URL.")
    parser.add_argument("--maybeai-api-attempts", type=int, default=DEFAULT_MAYBEAI_API_ATTEMPTS, help=f"MaybeAI API retry attempts. Default: {DEFAULT_MAYBEAI_API_ATTEMPTS}")
    parser.add_argument("--maybeai-api-retry-delay-seconds", type=int, default=DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS, help=f"Delay between MaybeAI API retries. Default: {DEFAULT_MAYBEAI_API_RETRY_DELAY_SECONDS}")
    parser.add_argument("--raw-db", action=argparse.BooleanOptionalAction, default=False, help="Save freshly crawled daily rows to MongoDB through a raw worksheet and save_table_worksheet_to_mongodb before Sheet ETL. Default: false")
    parser.add_argument("--raw-db-type", default=DEFAULT_RAW_DB_TYPE, help=f"Raw crawler data type/source. Default: {DEFAULT_RAW_DB_TYPE}")
    parser.add_argument("--raw-db-save-path", default=DEFAULT_RAW_DB_SAVE_PATH, help=f"MaybeAI function_call API path used to save the raw worksheet to MongoDB. Default: {DEFAULT_RAW_DB_SAVE_PATH}")
    parser.add_argument("--raw-db-uri", default=DEFAULT_RAW_DB_URI, help=f"MaybeAI spreadsheet URI used as the raw worksheet staging table before MongoDB save. Default: {DEFAULT_RAW_DB_URI}")
    parser.add_argument("--raw-db-worksheet-name", help="Worksheet name used as the raw MongoDB staging table. Defaults to <store><raw-db-worksheet-suffix>.")
    parser.add_argument("--raw-db-worksheet-suffix", default=DEFAULT_RAW_DB_WORKSHEET_SUFFIX, help=f"Worksheet suffix used when --raw-db-worksheet-name is omitted. Default: {DEFAULT_RAW_DB_WORKSHEET_SUFFIX}")
    parser.add_argument("--raw-db-read-path", default=DEFAULT_RAW_DB_READ_PATH, help=f"MaybeAI function_call API path used by --etl-source raw-api to load recent raw worksheet snapshots. Default: {DEFAULT_RAW_DB_READ_PATH}")
    parser.add_argument("--raw-read-days", type=int, default=DEFAULT_RAW_READ_DAYS, help=f"Days to request from the raw API ending at --end-date. Default: {DEFAULT_RAW_READ_DAYS}")
    parser.add_argument("--etl-source", choices=["fresh", "raw-api"], default="fresh", help="Use freshly crawled CLI rows or rows loaded back from the raw API for Sheet ETL. Default: fresh")
    parser.add_argument("--ensure-headers", action="store_true", help="Rewrite the header row with the script schema before writing data. Off by default.")
    parser.add_argument("--sheet-display-days", type=int, help="Only keep the most recent N days in the ETL sheet, ending at --end-date. Raw DB saves still use the requested date range.")
    parser.add_argument("--clear-worksheet-data", action="store_true", help="Discard existing data rows before writing fetched rows. Headers are preserved.")
    parser.add_argument("--skip-existing-days", action=argparse.BooleanOptionalAction, default=True, help="Skip a whole day when any existing row matches 店铺 + 日期. Default: true")
    parser.add_argument("--opencli-cmd", default=DEFAULT_OPENCLI_CMD, help=f"Command used to invoke OpenCLI. Default: {DEFAULT_OPENCLI_CMD!r}")
    parser.add_argument("--profile", help="OpenCLI Browser Bridge profile alias/id. Use one dedicated profile per store.")
    parser.add_argument("--store-config", help="JSON file with multiple store/profile/sheet configs. When set, stores are synced sequentially.")
    parser.add_argument("--store-key", action="append", default=[], help="Only run matching store config keys, ids, or store names. Can be passed multiple times.")
    parser.add_argument("--env-file", action="append", default=[], help="Optional .env file to load before reading tokens.")
    parser.add_argument("--opencli-timeout", type=int, help="Optional SHEIN command total timeout seconds passed as OpenCLI --timeout.")
    parser.add_argument("--request-timeout", type=int, help="Optional single SHEIN page API request timeout seconds passed as --requestTimeout.")
    parser.add_argument("--api-retry-attempts", type=int, help="Optional SHEIN page API retry attempts passed to OpenCLI.")
    parser.add_argument("--api-retry-delay-ms", type=int, help="Optional SHEIN page API retry base delay passed to OpenCLI.")
    parser.add_argument("--attempts", type=int, default=3, help="Whole SHEIN daily traffic CLI attempts before giving up. Default: 3")
    parser.add_argument("--retry-delay-seconds", type=int, default=10, help="Delay between whole-command retries. Default: 10")
    parser.add_argument("--login-on-retry", action=argparse.BooleanOptionalAction, default=True, help="Run shein login before retrying auth/network failures. Default: true")
    parser.add_argument("--cli-timeout", type=int, default=1800, help="Timeout for the whole daily traffic CLI subprocess in seconds. Default: 1800")
    parser.add_argument("--login-timeout", type=int, default=600, help="Timeout for login CLI in seconds. Default: 600")
    parser.add_argument("--login-wait-seconds", type=int, default=2, help="Delay before retrying after login. Default: 2")
    parser.add_argument("--preflight-login", action=argparse.BooleanOptionalAction, default=True, help="Run shein whoami before fetching and login first when the session is unavailable. Default: true")
    parser.add_argument("--shein-username", help="Optional SHEIN username for automatic login. Defaults to SHEIN_USERNAME or SHEIN_USER env var.")
    parser.add_argument("--shein-password", help="Optional SHEIN password for automatic login. Defaults to SHEIN_PASSWORD or SHEIN_PASS env var.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch SHEIN data and print ETL summary without writing to MaybeAI.")
    parser.add_argument("--self-test", action="store_true", help="Run network-free unit tests for this script and exit.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()

    repo_root = Path(__file__).resolve().parents[1]
    for env_file in args.env_file:
        load_env_file(Path(env_file).expanduser())
    logger, log_handlers, original_stdout, original_stderr = setup_daily_logging(args, repo_root)
    try:
        if args.store_config:
            configs = filter_store_configs(load_store_configs(Path(args.store_config).expanduser()), args.store_key)
            if not configs:
                raise SyncError("No store configs matched --store-key.")
            print(f"Running SHEIN daily traffic for {len(configs)} configured stores.")
            for index, config in enumerate(configs, start=1):
                scoped_args = args_for_store_config(args, config)
                print(f"=== configured store {index}/{len(configs)}: store={scoped_args.store}, profile={scoped_args.profile} ===")
                run_sync(scoped_args, repo_root)
        else:
            run_sync(args, repo_root)
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
