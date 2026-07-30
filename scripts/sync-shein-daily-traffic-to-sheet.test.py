#!/usr/bin/env python3
"""Network-free tests for sync-shein-daily-traffic-to-sheet.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("sync-shein-daily-traffic-to-sheet.py")
SPEC = importlib.util.spec_from_file_location("sync_shein_daily_traffic_to_sheet", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync)


class SheinDailyTrafficSyncTests(unittest.TestCase):
    def test_sheet_headers_match_legacy_play_be_output_without_json_columns(self) -> None:
        legacy_headers_without_json = [
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

        self.assertEqual(sync.SHEET_HEADERS, legacy_headers_without_json)
        for forbidden in ["每日流量明细JSON", "活动信息JSON", "权益活动JSON", "原始JSON"]:
            self.assertNotIn(forbidden, sync.SHEET_HEADERS)

    def test_resolves_daily_date_ranges(self) -> None:
        self.assertEqual(sync.normalize_date_input("2026-7-8"), "2026-07-08")
        self.assertEqual(sync.normalize_date_input("20260709"), "2026-07-09")
        self.assertEqual(sync.resolve_date_range("2026-07-12", "2026-07-10"), ["2026-07-10", "2026-07-11", "2026-07-12"])
        self.assertEqual(sync.resolve_date_range("2026-07-08", None), ["2026-07-08"])
        self.assertEqual(sync.resolve_date_range(None, "2026-07-09"), ["2026-07-09"])

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
            "bad_comment_cnt": 4,
            "prom_names": "活动A | 活动B",
            "prom_ids": "100 | 200",
            "raw_json": {"should": "not leak"},
        }, "店3")

        self.assertEqual(record["站点"], "SHEIN")
        self.assertEqual(record["店铺"], "店3")
        self.assertEqual(record["日期"], "2026-07-08")
        self.assertEqual(record["商品"], "Kitchen Rack")
        self.assertEqual(record["商品当前状态"], "在售")
        self.assertEqual(record["件数（已下单）"], 0)
        self.assertEqual(record["件数（已确认订单）"], 0)
        self.assertEqual(set(record), set(sync.SHEET_HEADERS))
        for forbidden in ["每日流量明细JSON", "活动信息JSON", "权益活动JSON", "原始JSON", "raw_json"]:
            self.assertNotIn(forbidden, record)

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
