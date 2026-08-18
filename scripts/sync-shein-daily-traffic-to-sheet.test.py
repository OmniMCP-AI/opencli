#!/usr/bin/env python3
"""Network-free tests for sync-shein-daily-traffic-to-sheet.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import maybeai_base_sync as base_sync


MODULE_PATH = Path(__file__).with_name("sync-shein-daily-traffic-to-sheet.py")
SPEC = importlib.util.spec_from_file_location("sync_shein_daily_traffic_to_sheet", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync)


class SheinDailyTrafficSyncTests(unittest.TestCase):
    def test_recalculate_traffic_worksheets_posts_in_order_with_expected_payloads(self) -> None:
        class FormulaClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []
                self.timeouts: list[int] = []
                self.token = "test-token"

            def post(self, path: str, payload: dict, timeout: int = 30) -> dict:
                self.calls.append((path, payload))
                self.timeouts.append(timeout)
                return {"success": True}

        formula_client = FormulaClient()
        args = type(
            "Args",
            (),
            {
                "store": "店3",
                "maybeai_api_attempts": 1,
                "maybeai_api_retry_delay_seconds": 0,
            },
        )()
        with mock.patch.object(sync, "MaybeAIClient", return_value=formula_client) as client_ctor:
            result = sync.recalculate_traffic_worksheets(args, type("Client", (), {"token": "test-token"})())

        self.assertEqual(len(result), 6)
        self.assertEqual([payload["worksheet_name"] for _, payload in formula_client.calls], [
            "产品_SKU日事实表",
            "产品_日趋势汇总表",
            "产品_类目周期明细表",
            "产品_生命周期周期汇总表",
            "产品_预设周期汇总表",
            "SKC区域运费当月",
        ])
        self.assertTrue(all(path == "/api/v1/excel/recalculate_formulas" for path, _ in formula_client.calls))
        self.assertEqual(formula_client.timeouts, [sync.DEFAULT_MAYBEAI_API_TIMEOUT] * 6)
        self.assertEqual(client_ctor.call_args.args[:2], (sync.DEFAULT_MAYBEAI_BASE_URL, "test-token"))
        self.assertEqual(formula_client.calls[0][1], {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=91",
            "clear_cache": False,
            "formula_engine": "base",
            "workbook_scope": False,
            "sync_save": False,
            "worksheet_name": "产品_SKU日事实表",
        })
        self.assertEqual(formula_client.calls[-1][1], {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=123",
            "clear_cache": False,
            "sync_save": True,
            "worksheet_name": "SKC区域运费当月",
        })

    def sheet_values(self, rows: list[dict]) -> list[list]:
        return [
            sync.SHEET_HEADERS,
            *[[row.get(header, "") for header in sync.SHEET_HEADERS] for row in rows],
        ]

    def resolved_sheet_target(self) -> base_sync.Target:
        return base_sync.Target(
            uri="etl-sheet",
            document_id="doc-sheet",
            gid=0,
            worksheet_name="每日流量ETL",
            engine="sheet",
            table_id=None,
        )

    def test_base_target_replaces_display_snapshot_without_legacy_sheet_calls(self) -> None:
        target = base_sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=41",
            document_id="69b91dd6bf42f58633fdc53b",
            gid=41,
            worksheet_name="每日流量ETL",
            engine="base",
            table_id="tbl_daily_traffic",
        )
        args = type("Args", (), {"read_range": None, "ensure_headers": False})()

        class Snapshot:
            revision = 41
            rows: list[dict] = []

            def records_from_rows(self, rows: list[dict]) -> list[dict]:
                return [{"fld_store": row["店铺"], "fld_day": row["日期"]} for row in rows]

        class RejectLegacyClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def post(self, path: str, payload: dict, timeout: int = 30) -> dict:
                del timeout
                self.calls.append((path, payload))
                raise AssertionError(f"Base daily traffic route attempted legacy endpoint: {path}")

        client = RejectLegacyClient()
        display_records = [{"店铺": "店3", "日期": "2026-08-06"}]
        snapshot = Snapshot()
        with mock.patch.object(sync.base_sync, "replace_snapshot", return_value={"success": True, "revision": 42}) as replace_snapshot:
            result = sync.write_resolved_target(client, target, snapshot, display_records, args)

        self.assertEqual(client.calls, [])
        self.assertEqual(result["write_api"], "table_record_replace")
        self.assertEqual(result["expected_revision"], 41)
        replace_snapshot.assert_called_once_with(
            client,
            snapshot,
            [{"fld_store": "店3", "fld_day": "2026-08-06"}],
        )

    def test_base_sync_merges_other_stores_before_replacing_snapshot(self) -> None:
        target = base_sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            document_id="doc-traffic",
            gid=41,
            worksheet_name="每日流量ETL",
            engine="base",
            table_id="tbl_daily_traffic",
        )
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": target.uri,
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": False,
            "raw_db": False,
            "etl_source": "fresh",
            "sheet_display_days": None,
            "clear_worksheet_data": False,
            "ensure_headers": False,
            "read_range": None,
        })()

        class Snapshot:
            revision = 41
            rows = [
                {"店铺": "店1", "日期": "2026-08-06", "商品货号": "store1-skc"},
                {"店铺": "店2", "日期": "2026-08-06", "商品货号": "store2-skc"},
            ]

        written_records: list[dict] = []
        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-08-06"]), \
             mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
             mock.patch.object(sync, "resolve_write_target", return_value=target), \
             mock.patch.object(sync.base_sync, "read_snapshot", return_value=Snapshot()), \
             mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"date": "2026-08-06", "skc": "store3-skc"}]), \
             mock.patch.object(sync, "write_resolved_target", side_effect=lambda _client, _target, _snapshot, records, _args: written_records.extend(records) or {"success": True}), \
             mock.patch.object(sync, "verify_base_written_days"), \
             mock.patch.object(sync, "recalculate_traffic_worksheets"):
            sync.run_sync(args, Path("."))

        self.assertEqual(
            {(row["店铺"], row["商品货号"]) for row in written_records},
            {("店1", "store1-skc"), ("店2", "store2-skc"), ("店3", "store3-skc")},
        )

    def test_raw_db_base_target_uses_preexisting_fields_without_header_write(self) -> None:
        target = base_sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-raw?gid=0",
            document_id="doc-raw",
            gid=0,
            worksheet_name="店3每日流量",
            engine="base",
            table_id="tbl_raw_daily_traffic",
        )
        args = type(
            "Args",
            (),
            {
                "raw_db_uri": target.uri,
                "raw_db_worksheet_name": "店3每日流量",
                "raw_db_worksheet_suffix": "每日流量",
                "store": "店3",
            },
        )()

        class Snapshot:
            revision = 11
            rows: list[dict] = []

            def records_from_rows(self, rows: list[dict]) -> list[dict]:
                return [{"fld_day": row["date"], "fld_skc": row["skc"]} for row in rows]

        class RejectLegacyClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def post(self, path: str, payload: dict, timeout: int = 30) -> dict:
                del timeout
                self.calls.append((path, payload))
                raise AssertionError(f"Base raw staging attempted legacy endpoint: {path}")

        client = RejectLegacyClient()
        snapshot = Snapshot()
        with mock.patch.object(sync.base_sync, "resolve_target", return_value=target), \
             mock.patch.object(sync.base_sync, "read_snapshot", return_value=snapshot), \
             mock.patch.object(sync.base_sync, "replace_snapshot", return_value={"success": True, "revision": 12}) as replace_snapshot:
            uri, worksheet_name = sync.write_raw_worksheet_for_day(
                args,
                client,
                "2026-08-06",
                [{"date": "2026-08-06", "skc": "skc-1"}],
            )

        self.assertEqual((uri, worksheet_name), (target.uri, target.worksheet_name))
        self.assertEqual(client.calls, [])
        replace_snapshot.assert_called_once_with(
            client,
            snapshot,
            [{"fld_day": "2026-08-06", "fld_skc": "skc-1"}],
        )

    def test_sheet_headers_include_traffic_quality_and_return_metrics_without_json_columns(self) -> None:
        expected_headers_without_json = [
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
            "点击率",
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
            "商品评价数",
            "差评数",
            "差评率",
            "退货订单数",
            "退货件数",
            "一级分类",
            "二级分类",
            "三级分类",
            "四级分类",
        ]

        self.assertEqual(sync.SHEET_HEADERS, expected_headers_without_json)
        for forbidden in ["每日流量明细JSON", "活动信息JSON", "权益活动JSON", "原始JSON"]:
            self.assertNotIn(forbidden, sync.SHEET_HEADERS)

    def test_resolves_daily_date_ranges(self) -> None:
        self.assertEqual(sync.normalize_date_input("2026-7-8"), "2026-07-08")
        self.assertEqual(sync.normalize_date_input("20260709"), "2026-07-09")
        self.assertEqual(sync.resolve_date_range("2026-07-12", "2026-07-10"), ["2026-07-10", "2026-07-11", "2026-07-12"])
        self.assertEqual(sync.resolve_date_range("2026-07-08", None), ["2026-07-08"])
        self.assertEqual(sync.resolve_date_range(None, "2026-07-09"), ["2026-07-09"])

    def test_resolves_last_days_window_from_end_date(self) -> None:
        args = type("Args", (), {
            "start_date": None,
            "end_date": "2026-07-29",
            "last_days": 3,
        })()

        self.assertEqual(sync.resolve_requested_days(args), ["2026-07-27", "2026-07-28", "2026-07-29"])

    def test_resolves_crawl_last_days_window_from_end_date(self) -> None:
        args = type("Args", (), {
            "start_date": None,
            "end_date": "2026-07-29",
            "last_days": None,
            "crawl_last_days": 3,
        })()

        self.assertEqual(sync.resolve_requested_days(args), ["2026-07-27", "2026-07-28", "2026-07-29"])

    def test_crawl_last_days_rejects_last_days_alias(self) -> None:
        args = type("Args", (), {
            "start_date": None,
            "end_date": "2026-07-29",
            "last_days": 30,
            "crawl_last_days": 3,
        })()

        with self.assertRaisesRegex(sync.SyncError, "--crawl-last-days cannot be combined with --last-days"):
            sync.resolve_requested_days(args)

    def test_last_days_rejects_start_date(self) -> None:
        args = type("Args", (), {
            "start_date": "2026-07-01",
            "end_date": "2026-07-29",
            "last_days": 30,
        })()

        with self.assertRaisesRegex(sync.SyncError, "--last-days cannot be combined with --start-date"):
            sync.resolve_requested_days(args)

    def test_formats_progress_label(self) -> None:
        self.assertEqual(sync.progress_label(3, 26), "3/26 (11.5%)")
        self.assertEqual(sync.progress_label(0, 0), "0/0")

    def test_fetch_and_save_raw_rows_saves_each_day_immediately(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "raw_db": True,
            "dry_run": False,
            "etl_source": "fresh",
        })()
        saved: list[tuple[str, list[dict]]] = []

        def fake_fetch(_args, _repo_root, day, _opencli):
            if day == "2026-07-02":
                raise sync.SyncError("second day failed")
            return [{"date": day, "skc": f"skc-{day}"}]

        with mock.patch.object(sync, "build_opencli_base", return_value=["opencli"]), \
            mock.patch.object(sync, "ensure_shein_session"), \
            mock.patch.object(sync, "fetch_shein_rows_for_day", side_effect=fake_fetch), \
            mock.patch.object(sync, "save_raw_daily_rows", side_effect=lambda _args, _client, day, rows: saved.append((day, rows))):
            with self.assertRaisesRegex(sync.SyncError, "second day failed"):
                sync.fetch_and_save_shein_rows(args, Path("."), object(), ["2026-07-01", "2026-07-02"])

        self.assertEqual(saved, [("2026-07-01", [{"date": "2026-07-01", "skc": "skc-2026-07-01"}])])

    def test_raw_api_mode_saves_raw_rows_when_raw_db_is_enabled(self) -> None:
        args = type("Args", (), {
            "raw_db": True,
            "dry_run": False,
            "etl_source": "raw-api",
        })()

        self.assertTrue(sync.should_save_raw_daily_rows(args, object()))

    def test_raw_api_fetch_and_save_logs_raw_db_save_progress(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "raw_db": True,
            "dry_run": False,
            "etl_source": "raw-api",
        })()
        saved: list[tuple[str, list[dict]]] = []

        with mock.patch.object(sync, "build_opencli_base", return_value=["opencli"]), \
            mock.patch.object(sync, "ensure_shein_session"), \
            mock.patch.object(sync, "fetch_shein_rows_for_day", return_value=[{"date": "2026-08-02", "skc": "skc-1"}]), \
            mock.patch.object(sync, "save_raw_daily_rows", side_effect=lambda _args, _client, day, rows: saved.append((day, rows))), \
            mock.patch("builtins.print") as print_mock:
            rows = sync.fetch_and_save_shein_rows(args, Path("."), object(), ["2026-08-02"])

        self.assertEqual(rows, [{"date": "2026-08-02", "skc": "skc-1"}])
        self.assertEqual(saved, [("2026-08-02", [{"date": "2026-08-02", "skc": "skc-1"}])])
        printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("Raw DB save started 1/1 (100.0%) day=2026-08-02, rows=1", printed)
        self.assertIn("Raw DB save completed 1/1 (100.0%) day=2026-08-02, rows=1", printed)

    def test_skip_sheet_write_still_fetches_without_etl_sheet_io(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": True,
            "skip_existing_days": False,
            "raw_db": True,
            "etl_source": "fresh",
            "sheet_display_days": 30,
        })()

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()) as build_client, \
            mock.patch.object(sync, "build_sheet_target") as build_sheet_target, \
            mock.patch.object(sync, "read_existing_for_sync") as read_existing, \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"date": "2026-07-01", "skc": "skc-1"}]) as fetch_rows, \
            mock.patch.object(sync, "write_sheet_records") as write_records:
            sync.run_sync(args, Path("."))

        build_client.assert_called_once()
        fetch_rows.assert_called_once()
        build_sheet_target.assert_not_called()
        read_existing.assert_not_called()
        write_records.assert_not_called()

    def test_raw_api_mode_fetches_and_saves_missing_days_before_sheet_etl(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "etl-sheet",
            "dry_run": False,
            "skip_sheet_write": False,
            "skip_existing_days": True,
            "raw_db": False,
            "etl_source": "raw-api",
            "sheet_display_days": None,
            "clear_worksheet_data": True,
            "ensure_headers": False,
        })()
        raw_response = {"result": {"snapshots": [{"data_date": "2026-07-01", "headers": ["date", "skc"], "rows": [["2026-07-01", "raw-skc"]]}]}}
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01", "2026-07-02"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "resolve_write_target", return_value=self.resolved_sheet_target()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "每日流量ETL")), \
            mock.patch.object(sync, "read_existing_for_sync", return_value=[]), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", return_value=raw_response), \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"date": "2026-07-02", "skc": "fresh-skc"}]) as fetch_rows, \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)), \
            mock.patch.object(sync, "verify_written_days"):
            sync.run_sync(args, Path("."))

        fetch_args = fetch_rows.call_args.args[0]
        self.assertTrue(fetch_args.raw_db)
        self.assertEqual(fetch_rows.call_args.args[3], ["2026-07-02"])
        self.assertEqual([row["商品货号"] for row in written_records], ["fresh-skc", "raw-skc"])

    def test_raw_api_uses_crawl_window_for_skip_and_display_window_for_sheet_etl(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
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
            {"data_date": "2026-07-01", "headers": ["date", "skc"], "rows": [["2026-07-01", "plan-01"]]},
            {"data_date": "2026-07-03", "headers": ["date", "skc"], "rows": [["2026-07-03", "plan-03"]]},
            {"data_date": "2026-07-04", "headers": ["date", "skc"], "rows": [["2026-07-04", "plan-04"]]},
        ]}}
        display_response = {"result": {"snapshots": [
            {"data_date": "2026-07-03", "headers": ["date", "skc"], "rows": [["2026-07-03", "display-03"]]},
            {"data_date": "2026-07-04", "headers": ["date", "skc"], "rows": [["2026-07-04", "display-04"]]},
        ]}}
        written_records: list[dict] = []

        with mock.patch.object(sync, "resolve_requested_days", return_value=["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]), \
            mock.patch.object(sync, "build_maybeai_client", return_value=object()), \
            mock.patch.object(sync, "resolve_write_target", return_value=self.resolved_sheet_target()), \
            mock.patch.object(sync, "build_sheet_target", return_value=({"uri": "etl-sheet"}, "每日流量ETL")), \
            mock.patch.object(sync, "read_existing_for_sync", return_value=[]), \
            mock.patch.object(sync, "read_raw_api_snapshot_response", side_effect=[plan_response, display_response]) as read_raw, \
            mock.patch.object(sync, "fetch_and_save_shein_rows", return_value=[{"date": "2026-07-02", "skc": "fresh-02"}]) as fetch_rows, \
            mock.patch.object(sync, "write_sheet_records", side_effect=lambda _client, _target, records, _args: written_records.extend(records)), \
            mock.patch.object(sync, "verify_written_days"):
            sync.run_sync(args, Path("."))

        self.assertEqual(fetch_rows.call_args.args[3], ["2026-07-02"])
        self.assertEqual(read_raw.call_count, 2)
        self.assertEqual(read_raw.call_args_list[0].kwargs["read_days"], 4)
        self.assertEqual(read_raw.call_args_list[1].kwargs["read_days"], 2)
        self.assertEqual({row["商品货号"] for row in written_records}, {"display-03", "display-04"})

    def test_raw_api_replaces_only_current_store_display_window_rows(self) -> None:
        requested_days = ["2026-07-01", "2026-07-02", "2026-07-03"]
        existing_records = [
            {"店铺": "店3", "日期": "2026-07-02", "商品货号": "old-store3-02"},
            {"店铺": "店3", "日期": "2026-07-03", "商品货号": "old-store3-03"},
            {"店铺": "店2", "日期": "2026-07-03", "商品货号": "keep-store2-03"},
            {"店铺": "店3", "日期": "2026-07-01", "商品货号": "keep-store3-01"},
        ]
        fresh_records = [
            {"店铺": "店3", "日期": "2026-07-02", "商品货号": "new-store3-02"},
            {"店铺": "店3", "日期": "2026-07-03", "商品货号": "new-store3-03"},
        ]

        replacement_days = sync.display_day_set_from_requested_days(requested_days, 2)
        filtered_existing, removed_count = sync.remove_store_records_for_days(existing_records, "店3", replacement_days)
        display_records = sync.filter_records_for_sheet_display(
            sync.merge_records_by_unique_key(filtered_existing, fresh_records),
            requested_days,
            2,
        )

        self.assertEqual(removed_count, 2)
        self.assertEqual(
            {row["商品货号"] for row in display_records},
            {"keep-store2-03", "new-store3-02", "new-store3-03"},
        )
        self.assertNotIn("old-store3-02", {row["商品货号"] for row in display_records})
        self.assertNotIn("old-store3-03", {row["商品货号"] for row in display_records})

    def test_maps_adapter_rows_to_business_sheet_records_without_json_columns(self) -> None:
        record = sync.adapter_row_to_record({
            "date": "2026-07-08",
            "queried_start_date": "20260708",
            "queried_end_date": "20260708",
            "goods_name": "Kitchen Rack",
            "img_url": "https://img.ltwebstatic.com/rack.jpg",
            "spu": "spu-1",
            "skc": "skc-1",
            "sku_supplier_no": "supplier-sku",
            "sale_flag": 1,
            "onsale_flag": 0,
            "new_goods_tag": 1,
            "multicolor_flag": "false",
            "goods_uv_idx": 10,
            "eps_uv_idx": 40,
            "pay_order_cnt": "",
            "sale_cnt": "",
            "total_comment_cnt": 11,
            "bad_comment_cnt": 4,
            "bad_comment_rate": 0.2,
            "return_order_cnt": 3,
            "return_qty": 5,
            "prom_names": "活动A | 活动B",
            "prom_ids": "100 | 200",
            "raw_json": {"should": "not leak"},
        }, "店3")

        self.assertEqual(record["站点"], "SHEIN")
        self.assertEqual(record["店铺"], "店3")
        self.assertEqual(record["日期"], "2026-07-08")
        self.assertEqual(record["商品"], "Kitchen Rack")
        self.assertEqual(record["商品当前状态"], "在售")
        self.assertEqual(record["点击率"], 0.25)
        self.assertEqual(record["件数（已下单）"], 0)
        self.assertEqual(record["件数（已确认订单）"], 0)
        self.assertEqual(record["商品评价数"], 11)
        self.assertEqual(record["差评数"], 4)
        self.assertEqual(record["差评率"], 0.2)
        self.assertEqual(record["退货订单数"], 3)
        self.assertEqual(record["退货件数"], 5)
        self.assertEqual(set(record), set(sync.SHEET_HEADERS))
        for forbidden in ["每日流量明细JSON", "活动信息JSON", "权益活动JSON", "原始JSON", "raw_json"]:
            self.assertNotIn(forbidden, record)

    def test_quality_and_return_metrics_default_to_zero_when_blank(self) -> None:
        record = sync.adapter_row_to_record({
            "date": "2026-07-08",
            "spu": "spu-1",
            "skc": "skc-1",
            "goods_uv_idx": "",
            "eps_uv_idx": "",
            "total_comment_cnt": "",
            "bad_comment_cnt": "",
            "bad_comment_rate": "",
            "return_order_cnt": "",
            "return_qty": "",
        }, "店3")

        for header in ["点击率", "商品评价数", "差评数", "差评率", "退货订单数", "退货件数"]:
            self.assertEqual(record[header], 0)

    def test_maps_zero_sale_flag_to_legacy_non_sale_status(self) -> None:
        record = sync.adapter_row_to_record({
            "date": "2026-07-08",
            "goods_name": "Kitchen Rack",
            "spu": "spu-1",
            "skc": "skc-1",
            "sale_flag": 0,
        }, "店3")

        self.assertEqual(record["商品当前状态"], "非在售")

    def test_builds_daily_raw_db_document_with_stable_key(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "nkgh6pe5",
            "raw_db_type": "shein_daily_traffic",
        })()
        rows = [
            {
                "date": "2026-07-08",
                "skc": "skc-1",
                "spu": "spu-1",
                "sku_supplier_no": "sku-1",
                "raw_json": {"skc": "skc-1", "goodsName": "Rack"},
            },
        ]

        document = sync.build_raw_daily_document(rows, args, "2026-07-08", fetched_at="2026-07-29T10:00:00")

        self.assertEqual(document["source"], "shein_daily_traffic")
        self.assertEqual(document["raw_key"], "shein_daily_traffic:店3:nkgh6pe5:2026-07-08")
        self.assertEqual(document["store"], "店3")
        self.assertEqual(document["profile"], "nkgh6pe5")
        self.assertEqual(document["date"], "2026-07-08")
        self.assertEqual(document["row_count"], 1)
        self.assertEqual(document["rows"], rows)

    def test_builds_save_table_worksheet_to_mongodb_payload(self) -> None:
        args = type("Args", (), {
            "raw_db_worksheet_name": "",
            "raw_db_worksheet_suffix": "每日流量",
        })()
        payload = sync.build_save_table_worksheet_to_mongodb_payload(
            args,
            data_date="2026-07-08",
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc?gid=4",
            store="店3",
        )

        self.assertEqual(payload, {
            "app": "function_call",
            "tool_id": "excel__save_table_worksheet_to_mongodb",
            "tool_name": "save_table_worksheet_to_mongodb",
            "tool_args": {
                "data_date": "2026-07-08",
                "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=4",
                "worksheet_name": "店3每日流量",
            },
        })

    def test_raw_db_uri_defaults_to_staging_workbook(self) -> None:
        args = type("Args", (), {
            "raw_db_uri": "",
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/etl?gid=0",
        })()

        self.assertEqual(sync.raw_db_uri(args), "https://www.maybe.ai/docs/spreadsheets/d/6a69d73b0e55e966f026dee3?gid=0")

    def test_extracts_row_count_from_dimensions_worksheet_response(self) -> None:
        response = {
            "success": True,
            "worksheets": [
                {
                    "worksheet_name": "每日流量ETL",
                    "gid": 3,
                    "dimensions": {"rows": 13337, "columns": 30},
                    "row_count": 13337,
                    "column_count": 30,
                },
            ],
        }

        self.assertEqual(sync.extract_worksheet_row_count(response), 13337)

    def test_build_sheet_target_resolves_worksheet_from_sheet_url_gid(self) -> None:
        args = type("Args", (), {
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=3",
            "worksheet_name": None,
        })()

        class FakeClient:
            def post(self, path, payload, timeout=sync.DEFAULT_MAYBEAI_API_TIMEOUT):
                self.request = (path, payload, timeout)
                return {"worksheets": [
                    {"gid": 0, "worksheet_name": "旧表"},
                    {"gid": 3, "worksheet_name": "每日流量ETL"},
                ]}

        client = FakeClient()
        target, worksheet_name = sync.build_sheet_target(args, client)

        self.assertEqual(client.request, (
            "/api/v1/excel/list_worksheets",
            {"uri": "https://www.maybe.ai/docs/spreadsheets/d/doc"},
            30,
        ))
        self.assertEqual(target, {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=3",
            "worksheet_name": "每日流量ETL",
        })
        self.assertEqual(worksheet_name, "每日流量ETL")

    def test_builds_read_recent_worksheet_snapshots_payload(self) -> None:
        args = type("Args", (), {
            "raw_read_days": 30,
        })()

        payload = sync.build_read_recent_worksheet_snapshots_payload(
            args,
            uri="https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
            worksheet_name="店3每日流量",
        )

        self.assertEqual(payload, {
            "app": "function_call",
            "tool_id": "excel__read_recent_worksheet_snapshots",
            "tool_name": "read_recent_worksheet_snapshots",
            "tool_args": {
                "uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
                "worksheet_name": "店3每日流量",
                "last_n_days": 30,
            },
        })

    def test_raw_read_days_defaults_to_sheet_display_days(self) -> None:
        args = type("Args", (), {
            "raw_read_days": 30,
            "sheet_display_days": 3,
            "_cli_override_keys": {"sheet_display_days"},
        })()

        payload = sync.build_read_recent_worksheet_snapshots_payload(
            args,
            uri="https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
            worksheet_name="店3每日流量",
        )

        self.assertEqual(payload["tool_args"]["last_n_days"], 3)

    def test_explicit_raw_read_days_overrides_sheet_display_days(self) -> None:
        args = type("Args", (), {
            "raw_read_days": 10,
            "sheet_display_days": 3,
            "_cli_override_keys": {"raw_read_days", "sheet_display_days"},
        })()

        payload = sync.build_read_recent_worksheet_snapshots_payload(
            args,
            uri="https://www.maybe.ai/docs/spreadsheets/d/raw?gid=4",
            worksheet_name="店3每日流量",
        )

        self.assertEqual(payload["tool_args"]["last_n_days"], 10)

    def test_loads_store_config_and_applies_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "stores.json"
            config_path.write_text(
                """{
                  "defaults": {
                    "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/etl?gid=0",
                    "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
                    "worksheet_name": "每日流量ETL",
                    "sheet_display_days": 30
                  },
                  "stores": [
                    {"store": "店1", "profile": "profile1"},
                    {"store": "店2", "profile": "profile2", "sheet_display_days": 7}
                  ]
                }""",
                encoding="utf-8",
            )

            configs = sync.load_store_configs(config_path)

        self.assertEqual(configs, [
            {
                "store": "店1",
                "profile": "profile1",
                "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/etl?gid=0",
                "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
                "worksheet_name": "每日流量ETL",
                "sheet_display_days": 30,
            },
            {
                "store": "店2",
                "profile": "profile2",
                "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/etl?gid=0",
                "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/raw?gid=0",
                "worksheet_name": "每日流量ETL",
                "sheet_display_days": 7,
            },
        ])

    def test_applies_store_config_to_args_without_mutating_base_args(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "base-sheet",
            "worksheet_name": None,
            "raw_db_uri": "base-raw",
            "raw_db_worksheet_name": None,
            "sheet_display_days": None,
            "store_config": None,
            "store_key": [],
        })()

        scoped = sync.args_for_store_config(args, {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "store-sheet",
            "worksheet_name": "店1每日流量ETL",
            "raw_db_worksheet_name": "店1每日流量",
            "sheet_display_days": 14,
        })

        self.assertEqual(scoped.store, "店1")
        self.assertEqual(scoped.profile, "profile1")
        self.assertEqual(scoped.sheet_url, "store-sheet")
        self.assertEqual(scoped.worksheet_name, "店1每日流量ETL")
        self.assertEqual(scoped.raw_db_uri, "base-raw")
        self.assertEqual(scoped.raw_db_worksheet_name, "店1每日流量")
        self.assertEqual(scoped.sheet_display_days, 14)
        self.assertEqual(args.store, "店3")

    def test_command_line_sheet_display_days_overrides_store_config_default(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "base-sheet",
            "worksheet_name": None,
            "raw_db_uri": "base-raw",
            "raw_db_worksheet_name": None,
            "sheet_display_days": 3,
            "store_config": "stores.json",
            "store_key": [],
            "_cli_override_keys": {"sheet_display_days"},
        })()

        scoped = sync.args_for_store_config(args, {
            "store": "店1",
            "profile": "profile1",
            "raw_db_worksheet_name": "店1每日流量",
            "sheet_display_days": 30,
        })

        self.assertEqual(scoped.store, "店1")
        self.assertEqual(scoped.profile, "profile1")
        self.assertEqual(scoped.raw_db_worksheet_name, "店1每日流量")
        self.assertEqual(scoped.sheet_display_days, 3)

    def test_command_line_sheet_url_overrides_store_config_default(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "cli-sheet",
            "worksheet_name": None,
            "raw_db_uri": "base-raw",
            "raw_db_worksheet_name": None,
            "sheet_display_days": None,
            "store_config": "stores.json",
            "store_key": [],
            "_cli_override_keys": {"sheet_url"},
        })()

        scoped = sync.args_for_store_config(args, {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "store-sheet",
        })

        self.assertEqual(scoped.store, "店1")
        self.assertEqual(scoped.profile, "profile1")
        self.assertEqual(scoped.sheet_url, "cli-sheet")

    def test_command_line_sheet_url_gid_ignores_config_worksheet_name(self) -> None:
        args = type("Args", (), {
            "store": "店3",
            "profile": "profile3",
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/cli?gid=3",
            "worksheet_name": None,
            "raw_db_uri": "base-raw",
            "raw_db_worksheet_name": None,
            "sheet_display_days": None,
            "store_config": "stores.json",
            "store_key": [],
            "_cli_override_keys": {"sheet_url"},
        })()

        scoped = sync.args_for_store_config(args, {
            "store": "店1",
            "profile": "profile1",
            "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/config?gid=0",
            "worksheet_name": "配置里的默认worksheet",
        })

        self.assertEqual(scoped.sheet_url, "https://www.maybe.ai/docs/spreadsheets/d/cli?gid=3")
        self.assertIsNone(scoped.worksheet_name)

    def test_raw_sheet_records_serialize_json_payloads(self) -> None:
        records = sync.raw_rows_to_sheet_records([
            {
                "date": "2026-07-08",
                "skc": "skc-1",
                "prom_inf_ing_json": [{"promId": 100}],
                "right_campaign_json": [{"id": 1}],
                "raw_json": {"skc": "skc-1"},
            },
        ])

        self.assertEqual(records[0]["date"], "2026-07-08")
        self.assertEqual(records[0]["skc"], "skc-1")
        self.assertEqual(records[0]["prom_inf_ing_json"], '[{"promId": 100}]')
        self.assertEqual(records[0]["right_campaign_json"], '[{"id": 1}]')
        self.assertEqual(records[0]["raw_json"], '{"skc": "skc-1"}')

    def test_extracts_adapter_rows_from_raw_api_documents(self) -> None:
        response = {
            "data": [
                {
                    "type": "shein_daily_traffic",
                    "data": {
                        "raw_key": "shein_daily_traffic:店3:nkgh6pe5:2026-07-08",
                        "rows": [{"date": "2026-07-08", "skc": "skc-1"}],
                    },
                },
                {
                    "data": {
                        "rows": [{"date": "2026-07-09", "skc": "skc-2"}],
                    },
                },
            ],
        }

        self.assertEqual(sync.extract_raw_api_rows(response), [
            {"date": "2026-07-08", "skc": "skc-1"},
            {"date": "2026-07-09", "skc": "skc-2"},
        ])

    def test_extracts_rows_from_recent_worksheet_snapshots(self) -> None:
        response = {
            "result": {
                "snapshots": [
                    {
                        "data_date": "2026-07-28",
                        "headers": ["站点", "店铺", "日期", "商品", "商品货号", "主商品货号"],
                        "rows": [["SHEIN", "店3", "2026-07-28", "Rack", "skc-1", "spu-1"]],
                    },
                    {
                        "data_date": "2026-07-29",
                        "headers": ["date", "goods_name", "skc", "spu"],
                        "rows": [["2026-07-29", "Cart", "skc-2", "spu-2"]],
                    },
                ],
            },
        }

        rows = sync.extract_raw_api_rows(response)

        self.assertEqual(rows, [
            {"站点": "SHEIN", "店铺": "店3", "日期": "2026-07-28", "商品": "Rack", "商品货号": "skc-1", "主商品货号": "spu-1"},
            {"date": "2026-07-29", "goods_name": "Cart", "skc": "skc-2", "spu": "spu-2"},
        ])

    def test_extracts_raw_snapshot_days_including_empty_snapshots(self) -> None:
        response = {
            "result": {
                "snapshots": [
                    {"data_date": "2026-07-27", "headers": ["date", "skc"], "rows": []},
                    {"data_date": "2026-07-28", "headers": ["date", "skc"], "rows": [["2026-07-28", "skc-1"]]},
                ],
            },
        }

        self.assertEqual(sync.extract_raw_snapshot_days(response), {"2026-07-27", "2026-07-28"})

    def test_missing_days_are_based_on_raw_db_snapshot_days_not_target_sheet_rows(self) -> None:
        target_sheet_records = [
            {"店铺": "店1", "日期": "2026-07-27", "商品货号": "from-etl-sheet"},
        ]
        raw_snapshot_days = {"2026-07-28"}

        missing, skipped = sync.compute_missing_days_from_existing_days(
            ["2026-07-27", "2026-07-28"],
            raw_snapshot_days,
            True,
        )

        self.assertTrue(target_sheet_records)
        self.assertEqual(missing, ["2026-07-27"])
        self.assertEqual(skipped, ["2026-07-28"])

    def test_rows_to_records_accepts_legacy_sheet_records(self) -> None:
        records = sync.rows_to_records([
            {
                "站点": "SHEIN",
                "店铺": "店3",
                "日期": "2026-07-28",
                "商品": "Rack",
                "商品货号": "skc-1",
                "主商品货号": "spu-1",
            },
        ], "店3")

        self.assertEqual(records[0]["站点"], "SHEIN")
        self.assertEqual(records[0]["店铺"], "店3")
        self.assertEqual(records[0]["日期"], "2026-07-28")
        self.assertEqual(records[0]["商品"], "Rack")
        self.assertEqual(records[0]["商品货号"], "skc-1")

    def test_rows_to_records_fills_blank_legacy_fields_from_raw_payload(self) -> None:
        adapter_row = sync.adapter_row_from_raw_sources({
            "站点": "SHEIN",
            "店铺": "店3",
            "日期": "2026-07-28",
            "商品": "Legacy Name",
            "商品货号": "skc-1",
            "主商品货号": "spu-1",
            "商品质量等级": "",
            "退货件数": "",
            "活动名称": "",
            "请求URL": "https://captured.example/list",
            "page_num": 3,
            "raw_json": {
                "goodsName": "Raw Name",
                "totalQualityLevel": "A",
                "payBadCommentCnt": 2,
                "returnQty": 4,
                "promCampaign": {
                    "promInfIng": [
                        {"promNm": "Summer", "promId": 101},
                        {"promNm": "VIP", "promId": 102},
                    ]
                },
            },
        })

        self.assertEqual(adapter_row["goods_name"], "Legacy Name")
        self.assertEqual(adapter_row["total_quality_level"], "A")
        self.assertEqual(adapter_row["bad_comment_cnt"], 2)
        self.assertEqual(adapter_row["return_qty"], 4)
        self.assertEqual(adapter_row["prom_names"], "Summer | VIP")
        self.assertEqual(adapter_row["prom_ids"], "101 | 102")
        self.assertEqual(adapter_row["request_url"], "https://captured.example/list")
        self.assertEqual(adapter_row["page_num"], 3)

    def test_rows_to_records_derives_bad_comment_count_when_raw_count_is_blank(self) -> None:
        rows = [
            sync.adapter_row_from_raw_sources({
                "站点": "SHEIN",
                "店铺": "店3",
                "日期": "2026-07-28",
                "商品货号": "skc-1",
                "主商品货号": "spu-1",
                "raw_json": {
                    "totalCommentCnt": 3,
                    "badCommentRate": 0.3333,
                    "payBadCommentCnt": None,
                },
            }),
            sync.adapter_row_from_raw_sources({
                "站点": "SHEIN",
                "店铺": "店3",
                "日期": "2026-07-28",
                "商品货号": "skc-2",
                "主商品货号": "spu-2",
                "total_comment_cnt": 3,
                "bad_comment_rate": 0,
            }),
        ]

        self.assertEqual(rows[0]["bad_comment_cnt"], 1)
        self.assertEqual(rows[1]["bad_comment_cnt"], 0)

    def test_zero_raw_values_are_not_treated_as_blank(self) -> None:
        adapter_row = sync.adapter_row_from_raw_sources({
                "站点": "SHEIN",
                "店铺": "店3",
                "日期": "2026-07-28",
                "商品货号": "skc-1",
                "主商品货号": "spu-1",
                "raw_json": {"returnQty": 0},
        })

        self.assertEqual(adapter_row["return_qty"], 0)

    def test_zero_adapter_values_on_legacy_rows_are_not_overwritten(self) -> None:
        adapter_row = sync.adapter_row_from_raw_sources({
                "站点": "SHEIN",
                "店铺": "店3",
                "日期": "2026-07-28",
                "商品货号": "skc-1",
                "主商品货号": "spu-1",
                "return_qty": 0,
        })

        self.assertEqual(adapter_row["return_qty"], 0)

    def test_summary_counts_adapter_and_legacy_sheet_dates(self) -> None:
        summary = sync.traffic_rows_summary(
            [{"date": "2026-07-28"}, {"日期": "2026-07-29"}],
            [],
            ["2026-07-28", "2026-07-29"],
            ["2026-07-28", "2026-07-29"],
            [],
        )

        self.assertEqual(summary["by_date"], {"2026-07-28": 1, "2026-07-29": 1})

    def test_write_verification_days_exclude_empty_fetched_days(self) -> None:
        records = [
            {"店铺": "店1", "日期": "2026-07-27", "商品货号": "skc-1"},
            {"店铺": "店1", "日期": "2026-07-28", "商品货号": "skc-2"},
            {"店铺": "店2", "日期": "2026-07-29", "商品货号": "other-store"},
        ]

        days = sync.days_with_etl_records(records, "店1", ["2026-07-27", "2026-07-28", "2026-07-29"])

        self.assertEqual(days, ["2026-07-27", "2026-07-28"])

    def test_read_sheet_records_reads_entire_sheet_in_ranges(self) -> None:
        class FakeClient:
            def __init__(fake_self) -> None:
                fake_self.payloads = []

            def post(fake_self, path: str, payload: dict, timeout: int = 300) -> dict:
                fake_self.payloads.append(payload)
                if path == "/api/v1/excel_v2/worksheet/dimensions":
                    return {"data": {"row_count": 5}}
                range_address = payload.get("range_address")
                if range_address == "A1:AJ3":
                    return {"values": self.sheet_values([
                        {"店铺": "店1", "日期": "2026-07-30", "商品货号": "row-1"},
                        {"店铺": "店1", "日期": "2026-07-29", "商品货号": "row-2"},
                    ])}
                if range_address == "A4:AJ5":
                    return {"values": self.sheet_values([
                        {"店铺": "店1", "日期": "2026-07-28", "商品货号": "row-3"},
                        {"店铺": "店1", "日期": "2026-07-27", "商品货号": "row-4"},
                    ])[1:]}
                self.fail(f"unexpected read range: {range_address}")

        old_chunk_rows = sync.SHEET_READ_CHUNK_ROWS
        sync.SHEET_READ_CHUNK_ROWS = 2
        try:
            client = FakeClient()
            records = sync.read_sheet_records(client, {"uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=3", "worksheet_name": "每日流量ETL"})
        finally:
            sync.SHEET_READ_CHUNK_ROWS = old_chunk_rows

        self.assertEqual([(row["日期"], row["商品货号"]) for row in records], [
            ("2026-07-30", "row-1"),
            ("2026-07-29", "row-2"),
            ("2026-07-28", "row-3"),
            ("2026-07-27", "row-4"),
        ])
        self.assertEqual(client.payloads[0], {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=3",
            "worksheet_name": "每日流量ETL",
            "gid": "3",
            "sheet_id": "3",
        })
        self.assertEqual([payload["range_address"] for payload in client.payloads[1:]], ["A1:AJ3", "A4:AJ5"])

    def test_read_worksheet_row_count_retries_dimensions_with_gid_only_payload(self) -> None:
        class FakeClient:
            def __init__(fake_self) -> None:
                fake_self.calls = []

            def post(fake_self, path: str, payload: dict, timeout: int = 300) -> dict:
                fake_self.calls.append((path, payload, timeout))
                if len(fake_self.calls) == 1:
                    return {
                        "success": True,
                        "engine": "composite",
                        "worksheet_count": 0,
                        "worksheets": [],
                    }
                return {
                    "success": True,
                    "engine": "base",
                    "worksheets": [{
                        "gid": 41,
                        "worksheet_name": "每日流量",
                        "dimensions": {"rows": 26392, "columns": 30},
                        "row_count": 26392,
                    }],
                }

        client = FakeClient()
        row_count = sync.read_worksheet_row_count(
            client,
            {"uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=41", "worksheet_name": "每日流量"},
        )

        self.assertEqual(row_count, 26392)
        self.assertEqual(client.calls[0][1], {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=41",
            "worksheet_name": "每日流量",
            "gid": "41",
            "sheet_id": "41",
        })
        self.assertEqual(client.calls[1][1], {
            "uri": "https://www.maybe.ai/docs/spreadsheets/d/doc?gid=41",
            "gid": "41",
            "sheet_id": "41",
        })

    def test_write_verification_reads_each_fetched_day_by_written_row_range(self) -> None:
        class FakeClient:
            def __init__(fake_self) -> None:
                fake_self.payloads = []

            def post(fake_self, path: str, payload: dict) -> dict:
                fake_self.payloads.append(payload)
                if payload.get("filter_tokens"):
                    return {
                        "success": False,
                        "source_info": {"reason": "unsupported_filter_read"},
                        "message": "Base-only read_sheet does not yet support workbook/filter projection semantics",
                    }
                if payload.get("range_address") == "A4:AJ4":
                    return {"values": self.sheet_values([
                        {"店铺": "店1", "日期": "2026-07-01", "商品货号": "old-day"},
                    ])[1:]}
                return {"values": self.sheet_values([
                    {"店铺": "店1", "日期": "2026-07-30", "商品货号": "recent-day"},
                ])}

        client = FakeClient()
        args = type("Args", (), {"store": "店1", "read_range": None})()
        display_records = [
            {"店铺": "店1", "日期": "2026-07-30", "商品货号": "recent-day"},
            {"店铺": "店2", "日期": "2026-07-01", "商品货号": "other-store"},
            {"店铺": "店1", "日期": "2026-07-01", "商品货号": "old-day"},
        ]

        sync.verify_written_days(client, {"uri": "sheet", "worksheet_name": "每日流量ETL"}, args, display_records, ["2026-07-01"])

        self.assertEqual(client.payloads[0].get("filter_tokens"), None)
        self.assertEqual(client.payloads[0]["range_address"], "A4:AJ4")

    def test_sheet_display_days_keeps_recent_window_across_stores(self) -> None:
        records = [
            {"店铺": "店1", "日期": "2026-07-26", "商品货号": "old"},
            {"店铺": "店2", "日期": "2026-07-27", "商品货号": "also-old"},
            {"店铺": "店1", "日期": "2026-07-28", "商品货号": "recent-1"},
            {"店铺": "店3", "日期": "2026-07-29", "商品货号": "recent-2"},
        ]

        visible = sync.filter_records_for_sheet_display(
            records,
            ["2026-07-27", "2026-07-28", "2026-07-29"],
            2,
        )

        self.assertEqual([(row["店铺"], row["日期"], row["商品货号"]) for row in visible], [
            ("店1", "2026-07-28", "recent-1"),
            ("店3", "2026-07-29", "recent-2"),
        ])

    def test_sheet_display_days_uses_latest_merged_record_date_not_requested_end(self) -> None:
        records = [
            {"店铺": "店1", "日期": "2026-07-26", "商品货号": "backfill-end"},
            {"店铺": "店2", "日期": "2026-07-27", "商品货号": "latest-1"},
            {"店铺": "店1", "日期": "2026-07-28", "商品货号": "latest-2"},
            {"店铺": "店3", "日期": "2026-07-29", "商品货号": "latest-3"},
        ]

        visible = sync.filter_records_for_sheet_display(
            records,
            ["2026-07-01", "2026-07-26"],
            3,
        )

        self.assertEqual([(row["店铺"], row["日期"], row["商品货号"]) for row in visible], [
            ("店2", "2026-07-27", "latest-1"),
            ("店1", "2026-07-28", "latest-2"),
            ("店3", "2026-07-29", "latest-3"),
        ])

    def test_preserves_unknown_boolean_flag_values(self) -> None:
        self.assertEqual(sync.map_yes_no("待确认"), "待确认")
        self.assertEqual(sync.map_yes_no("混合"), "混合")

    def test_detects_existing_store_days_and_skips_whole_day(self) -> None:
        existing = [
            {"店铺": "店3", "日期": "2026-07-08", "商品货号": "skc-1"},
            {"店铺": "店4", "日期": "2026-07-09", "商品货号": "skc-2"},
        ]
        missing, skipped = sync.compute_missing_days(["2026-07-08", "2026-07-09"], existing, "店3", True)
        self.assertEqual(missing, ["2026-07-09"])
        self.assertEqual(skipped, ["2026-07-08"])

    def test_merges_by_unique_key_and_sorts_by_date_desc_skc_asc(self) -> None:
        existing = [
            {"店铺": "店3", "日期": "2026-07-08", "商品货号": "skc-b", "主商品货号": "spu-1", "供应商SKU": "sku-1", "商品": "old"},
            {"店铺": "店4", "日期": "2026-07-08", "商品货号": "skc-a", "主商品货号": "spu-2", "供应商SKU": "sku-2", "商品": "other"},
        ]
        fresh = [
            {"店铺": "店3", "日期": "2026-07-08", "商品货号": "skc-b", "主商品货号": "spu-1", "供应商SKU": "sku-1", "商品": "fresh"},
            {"店铺": "店3", "日期": "2026-07-09", "商品货号": "skc-a", "主商品货号": "spu-3", "供应商SKU": "sku-3", "商品": "new"},
        ]

        merged = sync.sort_records(sync.merge_records_by_unique_key(existing, fresh))
        self.assertEqual([(row["店铺"], row["日期"], row["商品货号"], row["商品"]) for row in merged], [
            ("店3", "2026-07-09", "skc-a", "new"),
            ("店4", "2026-07-08", "skc-a", "other"),
            ("店3", "2026-07-08", "skc-b", "fresh"),
        ])


if __name__ == "__main__":
    unittest.main()
