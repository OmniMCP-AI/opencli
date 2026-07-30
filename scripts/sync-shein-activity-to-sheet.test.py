#!/usr/bin/env python3
"""Network-free tests for sync-shein-activity-to-sheet.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import argparse
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("sync-shein-activity-to-sheet.py")
SPEC = importlib.util.spec_from_file_location("sync_shein_activity_to_sheet", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync)


class SheinActivitySyncTests(unittest.TestCase):
    def test_sheet_headers_match_legacy_activity_output(self) -> None:
        self.assertEqual(sync.SHEET_HEADERS, [
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
        ])

    def test_maps_adapter_rows_to_legacy_business_records(self) -> None:
        row = {
            "record_type": "activity_detail",
            "snapshot_date": "2026-07-30",
            "activity_name": "Summer",
            "activity_type_id": 31,
            "type_id": 31,
            "image_url": "https://img.ltwebstatic.com/skc.jpg",
            "skc": "skc-1",
            "sku_supplier_no": "supplier-1",
            "start_time": "2026-07-01 00:00:00",
            "end_time": "2026-07-31 23:59:59",
            "terminate_time": "",
            "state": 3,
            "raw_json": {"must": "not leak"},
        }

        record = sync.adapter_row_to_record(row, "店1")

        self.assertEqual(record, {
            "店铺": "店1",
            "活动名称": "Summer",
            "活动规格": "限时折扣",
            "活动商品图片": "https://img.ltwebstatic.com/skc.jpg",
            "活动商品skc": "skc-1",
            "活动商品供方货号": "supplier-1",
            "活动时间": "2026-07-01 00:00:00 ~ 2026-07-31 23:59:59",
            "活动开始时间": "2026-07-01 00:00:00",
            "活动结束时间": "2026-07-31 23:59:59",
            "活动终止时间": "",
            "状态": "开启",
        })
        self.assertEqual(set(record), set(sync.SHEET_HEADERS))

    def test_keeps_list_only_and_blank_skc_activity_rows_in_etl(self) -> None:
        rows = [
            {"record_type": "activity_list_only", "activity_name": "Only list", "skc": ""},
            {"record_type": "activity_detail", "activity_name": "No skc", "skc": ""},
            {"record_type": "activity_detail", "activity_name": "Valid", "skc": "skc-1"},
            {"record_type": "empty_snapshot", "snapshot_date": "2026-07-30"},
        ]

        records = sync.rows_to_records(rows, "店1")

        self.assertEqual([record["活动名称"] for record in records], ["Only list", "No skc", "Valid"])
        self.assertEqual(records[0]["活动商品skc"], "")

    def test_builds_activity_opencli_command_for_snapshot_day(self) -> None:
        args = type("Args", (), {
            "opencli_cmd": "npm exec -- opencli",
            "profile": "profile1",
            "insert_start_time": "2026-01-30 00:00:00",
            "insert_end_time": "2026-07-30 23:59:59",
            "type_id": 31,
            "system": "mrs",
            "time_zone": "Asia/Shanghai",
            "activity_ids": "101-102",
            "page_size": 100,
            "limit_activities": 2,
            "limit_rows": 5,
            "max_list_pages": 3,
            "max_detail_pages": 2,
            "detail_concurrency": 2,
            "request_delay_min_ms": 0,
            "request_delay_max_ms": 50,
            "opencli_timeout": 3600,
            "request_timeout": 120,
            "api_retry_attempts": 3,
            "api_retry_delay_ms": 1000,
        })()

        command = sync.build_activity_command(args, "2026-07-30")

        self.assertEqual(command[:6], ["npm", "exec", "--", "opencli", "--profile", "profile1"])
        self.assertIn("activity", command)
        self.assertIn("--snapshotDate", command)
        self.assertIn("2026-07-30", command)
        self.assertIn("--activityIds", command)
        self.assertIn("101-102", command)

    def test_fetch_and_save_raw_rows_saves_each_day_immediately(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "raw_db": True,
            "dry_run": False,
            "etl_source": "fresh",
        })()
        saved: list[tuple[str, list[dict]]] = []

        def fake_fetch(_args, _repo_root, day, _opencli):
            if day == "2026-07-02":
                raise sync.SyncError("second day failed")
            return [{"snapshot_date": day, "skc": f"skc-{day}"}]

        with mock.patch.object(sync, "build_opencli_base", return_value=["opencli"]), \
            mock.patch.object(sync, "ensure_shein_session"), \
            mock.patch.object(sync, "fetch_shein_rows_for_day", side_effect=fake_fetch), \
            mock.patch.object(sync, "save_raw_activity_rows", side_effect=lambda _args, _client, day, rows: saved.append((day, rows))):
            with self.assertRaisesRegex(sync.SyncError, "second day failed"):
                sync.fetch_and_save_shein_rows(args, Path("."), object(), ["2026-07-01", "2026-07-02"])

        self.assertEqual(saved, [("2026-07-01", [{"snapshot_date": "2026-07-01", "skc": "skc-2026-07-01"}])])

    def test_enriches_raw_rows_with_store_profile_and_snapshot_date_before_saving(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
        })()

        rows = sync.enrich_raw_activity_rows(args, "2026-07-30", [{"skc": "skc-1", "store": "", "profile": ""}])

        self.assertEqual(rows[0]["snapshot_date"], "2026-07-30")
        self.assertEqual(rows[0]["store"], "店1")
        self.assertEqual(rows[0]["profile"], "profile1")
        self.assertEqual(rows[0]["raw_db_type"], sync.DEFAULT_RAW_DB_TYPE)
        self.assertEqual(rows[0]["raw_key"], "shein_activity:店1:profile1:2026-07-30")

    def test_save_raw_activity_rows_writes_empty_snapshot_before_mongodb_save(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "raw_db": True,
            "dry_run": False,
            "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
            "raw_db_worksheet_name": "",
            "raw_db_worksheet_suffix": "活动数据",
            "raw_db_save_path": sync.DEFAULT_RAW_DB_SAVE_PATH,
        })()

        class FakeClient:
            def __init__(self):
                self.calls = []

            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                self.calls.append((path, payload, timeout))
                return {"success": True}

        client = FakeClient()
        sync.save_raw_activity_rows(args, client, "2026-07-30", [])

        update_call = client.calls[1]
        self.assertEqual(client.calls[0][0], "/api/v1/excel/update_range")
        self.assertEqual(update_call[0], "/api/v1/excel/update_data_keep_headers")
        self.assertEqual(update_call[1]["data"][0]["record_type"], "empty_snapshot")
        self.assertEqual(update_call[1]["data"][0]["raw_db_type"], "shein_activity")
        self.assertEqual(update_call[1]["data"][0]["raw_key"], "shein_activity:店1:profile1:2026-07-30")
        self.assertEqual(update_call[1]["data"][0]["snapshot_date"], "2026-07-30")
        self.assertEqual(update_call[1]["data"][0]["store"], "店1")
        self.assertEqual(update_call[1]["data"][0]["profile"], "profile1")
        self.assertEqual(client.calls[2][0], sync.DEFAULT_RAW_DB_SAVE_PATH)

    def test_save_raw_activity_rows_retries_legacy_save_payload_if_key_args_rejected(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "raw_db": True,
            "dry_run": False,
            "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
            "raw_db_worksheet_name": "",
            "raw_db_worksheet_suffix": "活动数据",
            "raw_db_save_path": sync.DEFAULT_RAW_DB_SAVE_PATH,
            "raw_db_type": "shein_activity",
        })()

        class FakeClient:
            def __init__(self):
                self.save_payloads = []

            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                if path == sync.DEFAULT_RAW_DB_SAVE_PATH:
                    self.save_payloads.append(payload)
                    if len(self.save_payloads) == 1:
                        return {"success": False, "error": "unexpected key in tool_args"}
                return {"success": True}

        client = FakeClient()
        sync.save_raw_activity_rows(args, client, "2026-07-30", [{"activity_name": "A"}])

        self.assertIn("raw_key", client.save_payloads[0]["tool_args"])
        self.assertNotIn("raw_key", client.save_payloads[1]["tool_args"])
        self.assertEqual(client.save_payloads[1]["tool_args"], {
            "data_date": "2026-07-30",
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
            "worksheet_name": "店1活动数据",
        })

    def test_skip_sheet_write_still_fetches_without_target_sheet_io(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": True,
            "skip_existing_days": False,
            "raw_db": True,
            "etl_source": "raw-api",
            "sheet_display_days": 30,
        })()

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "build_sheet_target") as build_sheet_target, \
            mock.patch.object(sync, "read_sheet_records") as read_sheet_records, \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"snapshot_date": "2026-07-01", "skc": "skc-1"}]) as fetch_rows, \
            mock.patch.object(sync, "write_sheet_records") as write_records:
            sync.run_sync(args, Path("."))

        fetch_rows.assert_called_once()
        build_sheet_target.assert_not_called()
        read_sheet_records.assert_not_called()
        write_records.assert_not_called()

    def test_skip_sheet_write_requires_raw_db_so_crawl_only_does_not_drop_rows(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": True,
            "skip_existing_days": False,
            "raw_db": False,
            "etl_source": "fresh",
            "sheet_display_days": 30,
        })()

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01"]):
            with self.assertRaisesRegex(sync.SyncError, "--skip-sheet-write requires --raw-db"):
                sync.run_sync(args, Path("."))

    def test_raw_api_uses_crawl_window_for_skip_and_display_window_for_sheet_etl(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": True,
            "raw_db": False,
            "etl_source": "raw-api",
            "raw_read_days": 30,
            "sheet_display_days": 2,
            "_cli_override_keys": {"sheet_display_days"},
            "clear_worksheet_data": True,
            "ensure_headers": False,
        })()
        plan_response = {"result": {"snapshots": [
            {"data_date": "2026-07-01", "headers": ["snapshot_date", "skc"], "rows": [["2026-07-01", "plan-01"]]},
            {"data_date": "2026-07-03", "headers": ["snapshot_date", "skc"], "rows": [["2026-07-03", "plan-03"]]},
            {"data_date": "2026-07-04", "headers": ["snapshot_date", "skc"], "rows": [["2026-07-04", "plan-04"]]},
        ]}}
        display_response = {"result": {"snapshots": [
            {"data_date": "2026-07-03", "headers": ["snapshot_date", "activity_name", "skc"], "rows": [["2026-07-03", "display-03", "skc-3"]]},
            {"data_date": "2026-07-04", "headers": ["snapshot_date", "activity_name", "skc"], "rows": [["2026-07-04", "display-04", "skc-4"]]},
        ]}}
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "活动数据ETL")), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", side_effect=[plan_response, display_response]) as read_raw, \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"snapshot_date": "2026-07-02", "activity_name": "fresh-02", "skc": "skc-2"}]) as fetch_rows, \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)):
            sync.run_sync(args, Path("."))

        self.assertEqual(fetch_rows.call_args.args[3], ["2026-07-02"])
        self.assertEqual(read_raw.call_count, 2)
        self.assertGreaterEqual(read_raw.call_args_list[0].kwargs["read_days"], 4)
        self.assertEqual(read_raw.call_args_list[1].kwargs["read_days"], 2)
        self.assertEqual([row["活动名称"] for row in written_records], ["display-03", "display-04"])

    def test_raw_api_includes_fresh_display_rows_when_raw_snapshot_read_lags(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": True,
            "raw_db": False,
            "etl_source": "raw-api",
            "raw_read_days": 30,
            "sheet_display_days": 2,
            "_cli_override_keys": {"sheet_display_days"},
            "clear_worksheet_data": True,
            "ensure_headers": False,
        })()
        plan_response = {"result": {"snapshots": [
            {"data_date": "2026-07-29", "headers": ["snapshot_date", "activity_name", "skc"], "rows": [["2026-07-29", "display-29", "skc-29"]]},
        ]}}
        stale_display_response = {"result": {"snapshots": [
            {"data_date": "2026-07-29", "headers": ["snapshot_date", "activity_name", "skc"], "rows": [["2026-07-29", "display-29", "skc-29"]]},
        ]}}
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-29", "2026-07-30"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "活动数据ETL")), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", side_effect=[plan_response, stale_display_response]), \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"snapshot_date": "2026-07-30", "activity_name": "fresh-30", "skc": "skc-30"}]), \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)):
            sync.run_sync(args, Path("."))

        self.assertEqual([row["活动名称"] for row in written_records], ["display-29", "fresh-30"])

    def test_raw_api_sheet_write_replaces_current_store_rows_and_keeps_other_stores(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": True,
            "raw_db": False,
            "etl_source": "raw-api",
            "raw_read_days": 30,
            "sheet_display_days": 1,
            "_cli_override_keys": {"sheet_display_days"},
            "clear_worksheet_data": False,
            "ensure_headers": False,
        })()
        plan_response = {"result": {"snapshots": [{"data_date": "2026-07-30", "headers": ["snapshot_date"], "rows": [["2026-07-30"]]}]}}
        display_response = {"result": {"snapshots": [
            {"data_date": "2026-07-30", "headers": ["snapshot_date", "activity_name", "skc"], "rows": [["2026-07-30", "new-current-store", "skc-new"]]},
        ]}}
        existing = [
            {"店铺": "店1", "活动名称": "old-current-store", "活动开始时间": "2026-01-01", "活动商品skc": "skc-old", "活动商品供方货号": ""},
            {"店铺": "店2", "活动名称": "keep-other-store", "活动开始时间": "2026-01-01", "活动商品skc": "skc-2", "活动商品供方货号": ""},
        ]
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-30"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "活动数据ETL")), \
            mock.patch.object(sync, "read_sheet_records", return_value=existing), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", side_effect=[plan_response, display_response]), \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[]), \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)):
            sync.run_sync(args, Path("."))

        self.assertEqual([row["活动名称"] for row in written_records], ["new-current-store", "keep-other-store"])

    def test_raw_api_zero_etl_rows_clears_current_store_rows_and_writes_remaining_stores(self) -> None:
        args = type("Args", (), {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": True,
            "raw_db": False,
            "etl_source": "raw-api",
            "raw_read_days": 30,
            "sheet_display_days": 1,
            "_cli_override_keys": {"sheet_display_days"},
            "clear_worksheet_data": False,
            "ensure_headers": False,
        })()
        plan_response = {"result": {"snapshots": [{"data_date": "2026-07-30", "headers": ["snapshot_date"], "rows": [["2026-07-30"]]}]}}
        display_response = {"result": {"snapshots": [
            {"data_date": "2026-07-30", "headers": ["record_type", "snapshot_date"], "rows": [["empty_snapshot", "2026-07-30"]]},
        ]}}
        existing = [
            {"店铺": "店1", "活动名称": "old-current-store", "活动开始时间": "2026-01-01", "活动商品skc": "skc-old", "活动商品供方货号": ""},
            {"店铺": "店2", "活动名称": "keep-other-store", "活动开始时间": "2026-01-01", "活动商品skc": "skc-2", "活动商品供方货号": ""},
        ]
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-30"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "活动数据ETL")), \
            mock.patch.object(sync, "read_sheet_records", return_value=existing), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", side_effect=[plan_response, display_response]), \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[]), \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)):
            sync.run_sync(args, Path("."))

        self.assertEqual([row["活动名称"] for row in written_records], ["keep-other-store"])

    def test_builds_save_table_worksheet_to_mongodb_payload(self) -> None:
        args = type("Args", (), {
            "raw_db_worksheet_name": "",
            "raw_db_worksheet_suffix": "活动数据",
            "raw_db_type": "shein_activity",
            "profile": "profile1",
        })()

        payload = sync.build_save_table_worksheet_to_mongodb_payload(
            args,
            data_date="2026-07-30",
            uri="https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
            store="店1",
        )

        self.assertEqual(payload, {
            "app": "function_call",
            "tool_id": "excel__save_table_worksheet_to_mongodb",
            "tool_name": "save_table_worksheet_to_mongodb",
            "tool_args": {
                "data_date": "2026-07-30",
                "uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
                "worksheet_name": "店1活动数据",
                "key": "shein_activity:店1:profile1:2026-07-30",
                "raw_key": "shein_activity:店1:profile1:2026-07-30",
                "raw_db_type": "shein_activity",
                "store": "店1",
                "profile": "profile1",
            },
        })

    def test_rejects_placeholder_raw_db_uri_when_raw_db_is_needed(self) -> None:
        args = type("Args", (), {
            "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/<raw-activity-doc-id>?gid=0",
        })()

        with self.assertRaisesRegex(sync.SyncError, "raw DB URI is still a placeholder"):
            sync.validate_raw_db_uri(args)

    def test_build_sheet_target_resolves_worksheet_from_sheet_url_gid(self) -> None:
        args = type("Args", (), {
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=40",
            "worksheet_name": None,
            "_cli_override_keys": set(),
        })()

        class FakeClient:
            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                self.request = (path, payload, timeout)
                return {"worksheets": [
                    {"gid": 0, "worksheet_name": "旧表"},
                    {"gid": 40, "worksheet_name": "活动数据ETL"},
                ]}

        client = FakeClient()
        target, worksheet_name = sync.build_sheet_target(args, client)

        self.assertEqual(client.request, (
            "/api/v1/excel/list_worksheets",
            {"uri": "https://www.maybe.ai/docs/spreadsheets/d/doc"},
            30,
        ))
        self.assertEqual(target, {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=40",
            "worksheet_name": "活动数据ETL",
        })
        self.assertEqual(worksheet_name, "活动数据ETL")

    def test_cli_sheet_url_override_ignores_config_worksheet_name_so_gid_wins(self) -> None:
        args = argparse.Namespace(
            sheet_url="https://www.maybe.ai/docs/spreadsheets/d/cli-doc?gid=41",
            worksheet_name=None,
            _cli_override_keys={"sheet_url"},
        )
        config = {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/config-doc?gid=40",
            "worksheet_name": "旧活动表",
        }

        scoped = sync.args_for_store_config(args, config)

        self.assertEqual(scoped.sheet_url, "https://www.maybe.ai/docs/spreadsheets/d/cli-doc?gid=41")
        self.assertIsNone(scoped.worksheet_name)

    def test_extracts_row_count_from_dimensions_response_variants(self) -> None:
        self.assertEqual(sync.extract_worksheet_row_count({"data": {"dimensions": {"rows": 8}}}), 8)
        self.assertEqual(sync.extract_worksheet_row_count({"data": {"row_count": 9}}), 9)
        self.assertEqual(sync.extract_worksheet_row_count({"worksheets": [{"dimensions": {"rows": 10}}]}), 10)

    def test_crawl_plan_raw_read_days_cover_explicit_historical_window(self) -> None:
        args = argparse.Namespace()

        with mock.patch.object(sync, "default_yesterday", return_value="2026-07-30"):
            self.assertEqual(sync.raw_read_days_for_requested_window(args, ["2026-07-01", "2026-07-02"]), 30)
            self.assertEqual(sync.raw_read_days_for_requested_window(args, ["2026-07-29", "2026-07-30"]), 2)

    def test_read_sheet_records_reads_ranges_with_header_only_from_first_chunk(self) -> None:
        class FakeClient:
            def __init__(self):
                self.payloads = []

            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                self.payloads.append((path, payload))
                if path == sync.WORKSHEET_DIMENSIONS_PATH:
                    return {"worksheets": [{"dimensions": {"rows": 10003}}]}
                if payload.get("range_address") == "A1:K10001":
                    return {"values": [sync.SHEET_HEADERS, ["店1", "A", "", "", "skc-1", "", "", "", "", "", "开启"]]}
                if payload.get("range_address") == "A10002:K10003":
                    return {"values": [["店2", "B", "", "", "skc-2", "", "", "", "", "", "开启"]]}
                return {"values": []}

        client = FakeClient()
        records = sync.read_sheet_records(client, {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=40",
            "worksheet_name": "活动数据ETL",
        })

        self.assertEqual([record["店铺"] for record in records], ["店1", "店2"])
        dimensions_payload = client.payloads[0][1]
        self.assertEqual(dimensions_payload["gid"], "40")
        self.assertEqual(dimensions_payload["sheet_id"], "40")

    def test_read_sheet_records_retries_dimensions_with_gid_only_and_accepts_data_records(self) -> None:
        class FakeClient:
            def __init__(self):
                self.dimension_payloads = []

            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                if path == sync.WORKSHEET_DIMENSIONS_PATH:
                    self.dimension_payloads.append(payload)
                    if len(self.dimension_payloads) == 1:
                        return {"success": True, "worksheets": []}
                    return {"success": True, "worksheets": [{"dimensions": {"rows": 2}}]}
                return {"data": [{"店铺": "店1", "活动名称": "A", "活动商品skc": "skc-1"}]}

        client = FakeClient()
        records = sync.read_sheet_records(client, {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=40",
            "worksheet_name": "旧活动表",
        })

        self.assertEqual(records, [{"店铺": "店1", "活动名称": "A", "活动商品skc": "skc-1"}])
        self.assertEqual(client.dimension_payloads[0]["worksheet_name"], "旧活动表")
        self.assertNotIn("worksheet_name", client.dimension_payloads[1])

    def test_loads_three_store_prod_config_profiles(self) -> None:
        config = sync.load_store_configs(Path(__file__).with_name("shein-activity-prod.json"))

        self.assertEqual([(item["store"], item["profile"]) for item in config], [
            ("店1", "jegkb2wv"),
            ("店2", "m3cjm28a"),
            ("店3", "w2db43wa"),
        ])

    def test_prod_config_has_real_raw_db_uri(self) -> None:
        config = sync.load_store_configs(Path(__file__).with_name("shein-activity-prod.json"))

        for item in config:
            sync.validate_raw_db_uri(argparse.Namespace(raw_db_uri=item["raw_db_uri"]))


if __name__ == "__main__":
    unittest.main()
