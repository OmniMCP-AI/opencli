#!/usr/bin/env python3
"""Unit tests for the engine-aware MaybeAI Base table adapter."""

from __future__ import annotations

import unittest
from typing import Any

import maybeai_base_sync as sync


class FakeClient:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self._responses = {path: list(items) for path, items in responses.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: int = 30,
    ) -> dict[str, Any]:
        del timeout
        self.calls.append((path, dict(payload)))
        try:
            return self._responses[path].pop(0)
        except (KeyError, IndexError) as error:
            raise AssertionError(f"Unexpected MaybeAI request: {path} {payload}") from error


def base_metadata() -> dict[str, Any]:
    return {
        "success": True,
        "worksheets": [
            {
                "gid": 41,
                "worksheet_name": "每日流量",
                "data_engine": "base",
                "table_id": "tbl_traffic",
            }
        ],
    }


def base_table_page(
    *,
    revision: int,
    records: list[dict[str, Any]],
    has_more: bool,
) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "revision": revision,
            "has_more": has_more,
            "fields": [
                {"field_id": "fld_store", "name": "店铺", "logical_type": "text"},
                {"field_id": "fld_orders", "name": "订单数", "logical_type": "integer"},
                {
                    "field_id": "fld_total",
                    "name": "总额",
                    "logical_type": "formula",
                    "is_formula": True,
                },
            ],
            "records": records,
        },
    }


class BaseSyncTests(unittest.TestCase):
    def test_resolve_base_target_uses_metadata_and_gid(self) -> None:
        client = FakeClient({"/api/v1/excel_v2/worksheet/metadata": [base_metadata()]})

        target = sync.resolve_target(
            client,
            "https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            None,
        )

        self.assertEqual(target.document_id, "doc-traffic")
        self.assertEqual(target.gid, 41)
        self.assertEqual(target.engine, "base")
        self.assertEqual(target.table_id, "tbl_traffic")
        self.assertEqual(target.worksheet_name, "每日流量")
        self.assertEqual(
            client.calls,
            [
                (
                    "/api/v1/excel_v2/worksheet/metadata",
                    {"uri": "https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41"},
                )
            ],
        )

    def test_read_snapshot_pages_records_and_maps_field_ids_to_names(self) -> None:
        target = sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            document_id="doc-traffic",
            gid=41,
            worksheet_name="每日流量",
            engine="base",
            table_id="tbl_traffic",
        )
        client = FakeClient(
            {
                "/api/v1/excel/table/read": [
                    base_table_page(
                        revision=7,
                        has_more=True,
                        records=[
                            {
                                "record_id": "rec-1",
                                "fields": {"fld_store": "店1", "fld_orders": 3},
                            }
                        ],
                    ),
                    base_table_page(
                        revision=7,
                        has_more=False,
                        records=[
                            {
                                "record_id": "rec-2",
                                "fields": {"fld_store": "店2", "fld_orders": 5},
                            }
                        ],
                    ),
                ]
            }
        )

        snapshot = sync.read_snapshot(client, target)

        self.assertEqual(snapshot.revision, 7)
        self.assertEqual(
            snapshot.rows,
            [
                {"店铺": "店1", "订单数": 3},
                {"店铺": "店2", "订单数": 5},
            ],
        )
        self.assertEqual(
            [payload for _, payload in client.calls],
            [
                {
                    "document_id": "doc-traffic",
                    "gid": 41,
                    "table_id": "tbl_traffic",
                    "worksheet_name": "每日流量",
                    "limit": 100000,
                    "offset": 0,
                },
                {
                    "document_id": "doc-traffic",
                    "gid": 41,
                    "table_id": "tbl_traffic",
                    "worksheet_name": "每日流量",
                    "limit": 100000,
                    "offset": 1,
                },
            ],
        )

    def test_read_snapshot_uses_full_page_as_fallback_when_pagination_marker_missing(self) -> None:
        target = sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            document_id="doc-traffic",
            gid=41,
            worksheet_name="每日流量",
            engine="base",
            table_id="tbl_traffic",
        )
        original_page_size = sync.TABLE_READ_PAGE_SIZE
        sync.TABLE_READ_PAGE_SIZE = 2
        try:
            first_page = base_table_page(
                revision=7,
                has_more=False,
                records=[
                    {"record_id": "rec-1", "fields": {"fld_store": "店1"}},
                    {"record_id": "rec-2", "fields": {"fld_store": "店2"}},
                ],
            )
            del first_page["data"]["has_more"]
            second_page = base_table_page(
                revision=7,
                has_more=False,
                records=[{"record_id": "rec-3", "fields": {"fld_store": "店3"}}],
            )
            del second_page["data"]["has_more"]
            client = FakeClient({"/api/v1/excel/table/read": [first_page, second_page]})

            snapshot = sync.read_snapshot(client, target)
        finally:
            sync.TABLE_READ_PAGE_SIZE = original_page_size

        self.assertEqual([row["店铺"] for row in snapshot.rows], ["店1", "店2", "店3"])
        self.assertEqual([payload["offset"] for _, payload in client.calls], [0, 2])

    def test_snapshot_rejects_sheet_options_unknown_headers_and_formula_input(self) -> None:
        target = sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            document_id="doc-traffic",
            gid=41,
            worksheet_name="每日流量",
            engine="base",
            table_id="tbl_traffic",
        )
        snapshot = sync.Snapshot(
            target=target,
            revision=7,
            fields=(
                sync.Field("fld_store", "店铺", "text"),
                sync.Field("fld_orders", "订单数", "integer"),
                sync.Field("fld_total", "总额", "formula", is_formula=True),
            ),
            rows=(),
        )

        with self.assertRaisesRegex(sync.BaseSyncError, "read-range"):
            sync.require_base_compatible_options(
                target,
                read_range="A2:C3",
                ensure_headers=False,
            )
        with self.assertRaisesRegex(sync.BaseSyncError, "Unknown incoming header: 未知"):
            snapshot.records_from_rows([{"未知": "x"}])
        with self.assertRaisesRegex(sync.BaseSyncError, "Formula field has input: 总额"):
            snapshot.records_from_rows([{"总额": 3}])
        self.assertEqual(
            snapshot.records_from_rows([{"店铺": "店3", "订单数": "9", "总额": ""}]),
            [{"fld_store": "店3", "fld_orders": 9}],
        )

    def test_replace_snapshot_forwards_revision_without_sheet_payload(self) -> None:
        target = sync.Target(
            uri="https://www.maybe.ai/docs/spreadsheets/d/doc-traffic?gid=41",
            document_id="doc-traffic",
            gid=41,
            worksheet_name="每日流量",
            engine="base",
            table_id="tbl_traffic",
        )
        snapshot = sync.Snapshot(target=target, revision=7, fields=(), rows=())
        client = FakeClient(
            {
                "/api/v1/excel/table/record/replace": [
                    {"success": True, "revision": 8}
                ]
            }
        )

        result = sync.replace_snapshot(client, snapshot, [{"fld_store": "店3"}])

        self.assertEqual(result["revision"], 8)
        self.assertEqual(
            client.calls,
            [
                (
                    "/api/v1/excel/table/record/replace",
                    {
                        "document_id": "doc-traffic",
                        "gid": 41,
                        "table_id": "tbl_traffic",
                        "worksheet_name": "每日流量",
                        "records": [{"fld_store": "店3"}],
                        "expected_revision": 7,
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
