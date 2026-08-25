#!/usr/bin/env python3
"""Base routing tests for the SHEIN feedback sync."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import maybeai_base_sync as base_sync


SCRIPT_PATH = Path(__file__).with_name("sync-shein-feedback-to-sheet.py")
SPEC = importlib.util.spec_from_file_location("shein_feedback_sync", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT_PATH}")
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class RejectLegacyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict, timeout: int = 30) -> dict:
        del timeout
        self.calls.append((path, payload))
        if path in {
            "/api/v1/excel/list_worksheets",
            "/api/v1/excel/read_sheet",
            "/api/v1/excel/update_range",
            "/api/v1/excel/update_data_keep_headers",
        }:
            raise AssertionError(f"Base route attempted legacy endpoint: {path}")
        raise AssertionError(f"Unexpected direct client call: {path}")


def base_target() -> base_sync.Target:
    return base_sync.Target(
        uri="https://www.maybe.ai/docs/spreadsheets/d/doc-feedback?gid=8",
        document_id="doc-feedback",
        gid=8,
        worksheet_name="R_店3商品评价",
        engine="base",
        table_id="tbl_feedback",
    )


class FakeSnapshot:
    def __init__(self, rows: list[dict]) -> None:
        self.target = base_target()
        self.revision = 7
        self.rows = rows
        self.fields = [
            base_sync.Field(field_id=f"field-{index}", name=header, logical_type="text")
            for index, header in enumerate(sync.SHEET_HEADERS[1:], start=1)
        ]
        self.mapped_rows: list[dict] | None = None

    def records_from_rows(self, rows: list[dict]) -> list[dict]:
        self.mapped_rows = rows
        return [{"field_comment_time": row["评价时间"]} for row in rows]


class FeedbackBaseRouteTests(unittest.TestCase):
    def test_write_sheet_uses_base_replace_and_drops_store_for_dedicated_table(self) -> None:
        args = SimpleNamespace(
            sheet_url=base_target().uri,
            worksheet_name=None,
            read_range=None,
            ensure_headers=False,
            store="店3",
        )
        client = RejectLegacyClient()
        snapshot = FakeSnapshot(
            [{
                "评价时间": "2026-08-01 00:00:00",
                "评论ID": "old",
                "国家站点": "SHEIN日本站",
            }]
        )
        current_records = [{
            "店铺": "店3",
            "评价时间": "2026-08-02 00:00:00",
            "评论ID": "new",
            "国家站点": "SHEIN日本站",
        }]

        with mock.patch.object(sync, "build_maybeai_client", return_value=client), \
             mock.patch.object(sync.base_sync, "resolve_target", return_value=base_target()), \
             mock.patch.object(sync.base_sync, "read_snapshot", return_value=snapshot), \
             mock.patch.object(sync, "rows_to_records", return_value=current_records), \
             mock.patch.object(sync.base_sync, "replace_snapshot", return_value={"success": True, "revision": 8}) as replace_snapshot:
            sync.write_sheet(args, [{"source": "fresh"}])

        self.assertEqual(client.calls, [])
        self.assertEqual(
            [row["评论ID"] for row in snapshot.mapped_rows or []],
            ["new", "old"],
        )
        self.assertTrue(all("店铺" not in row for row in snapshot.mapped_rows or []))
        replace_snapshot.assert_called_once_with(
            client,
            snapshot,
            [{"field_comment_time": "2026-08-02 00:00:00"}, {"field_comment_time": "2026-08-01 00:00:00"}],
        )

    def test_base_target_rejects_sheet_only_options(self) -> None:
        args = SimpleNamespace(
            sheet_url=base_target().uri,
            worksheet_name=None,
            read_range="A2:Q10",
            ensure_headers=False,
            store="店3",
        )
        client = RejectLegacyClient()
        with mock.patch.object(sync, "build_maybeai_client", return_value=client), \
             mock.patch.object(sync.base_sync, "resolve_target", return_value=base_target()):
            with self.assertRaisesRegex(sync.SyncError, "Sheet-only"):
                sync.write_sheet(args, [])


if __name__ == "__main__":
    unittest.main()
