#!/usr/bin/env python3
"""Base routing tests for the SHEIN aftersales sync."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import maybeai_base_sync as base_sync


SCRIPT_PATH = Path(__file__).with_name("sync-shein-aftersales-to-sheet.py")
SPEC = importlib.util.spec_from_file_location("shein_aftersales_sync", SCRIPT_PATH)
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


class FormulaClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict, timeout: int = 30) -> dict:
        del timeout
        self.calls.append((path, payload))
        return self.response


def base_target() -> base_sync.Target:
    return base_sync.Target(
        uri="https://www.maybe.ai/docs/spreadsheets/d/doc-aftersales?gid=12",
        document_id="doc-aftersales",
        gid=12,
        worksheet_name="售后订单",
        engine="base",
        table_id="tbl_aftersales",
    )


class FakeSnapshot:
    def __init__(self, rows: list[dict]) -> None:
        self.target = base_target()
        self.revision = 18
        self.rows = rows
        self.mapped_rows: list[dict] | None = None

    def records_from_rows(self, rows: list[dict]) -> list[dict]:
        self.mapped_rows = rows
        return [{"fld_request_time": row["requestTime"]} for row in rows]


class AftersalesBaseRouteTests(unittest.TestCase):
    def test_recalculate_base_formulas_requires_execution_evidence(self) -> None:
        client = FormulaClient({"success": True, "source_info": {}})

        with self.assertRaisesRegex(
            sync.SyncError,
            "no base_table_formula_execution evidence",
        ):
            sync.recalculate_base_formulas(client, base_target())

        self.assertEqual(
            client.calls,
            [
                (
                    "/api/v1/excel/recalculate_formulas",
                    {
                        "uri": base_target().uri,
                        "document_id": "doc-aftersales",
                        "gid": 12,
                        "table_id": "tbl_aftersales",
                        "worksheet_name": "售后订单",
                    },
                )
            ],
        )

    def test_infer_since_request_time_reads_base_snapshot(self) -> None:
        args = SimpleNamespace(
            since_request_time=None,
            sheet_url=base_target().uri,
            worksheet_name=None,
            read_range=None,
            ensure_headers=False,
            store="店3",
        )
        client = RejectLegacyClient()
        snapshot = FakeSnapshot(
            [
                {"store": "店3", "requestTime": "2026-08-01 00:00:00"},
                {"store": "店3", "requestTime": "2026-08-03 12:30:00"},
            ]
        )

        with mock.patch.object(sync, "build_maybeai_client", return_value=client), \
             mock.patch.object(sync.base_sync, "resolve_target", return_value=base_target()), \
             mock.patch.object(sync.base_sync, "read_snapshot", return_value=snapshot):
            sync.infer_since_request_time(args)

        self.assertEqual(args.since_request_time, "2026-08-03 12:30:00")
        self.assertEqual(client.calls, [])

    def test_write_sheet_uses_base_snapshot_replace_without_legacy_calls(self) -> None:
        args = SimpleNamespace(
            sheet_url=base_target().uri,
            worksheet_name=None,
            read_range=None,
            ensure_headers=False,
            store="店3",
            recalculate_formulas=False,
            recalculate_sheet_url=None,
            recalculate_worksheet_name=None,
        )
        client = RejectLegacyClient()
        snapshot = FakeSnapshot(
            [{"store": "店2", "requestTime": "2026-08-01 00:00:00"}]
        )
        replace_result = {"success": True, "revision": 19}
        source_records = [{"source": "fresh"}]
        current_records = [{"store": "店3", "requestTime": "2026-08-02 00:00:00"}]

        with mock.patch.object(sync, "build_maybeai_client", return_value=client), \
             mock.patch.object(sync.base_sync, "resolve_target", return_value=base_target()), \
             mock.patch.object(sync.base_sync, "read_snapshot", return_value=snapshot), \
             mock.patch.object(sync, "rows_to_records", return_value=current_records), \
             mock.patch.object(sync.base_sync, "replace_snapshot", return_value=replace_result) as replace_snapshot:
            sync.write_sheet(args, source_records)

        self.assertEqual(client.calls, [])
        self.assertEqual(
            [(row["store"], row["requestTime"]) for row in snapshot.mapped_rows or []],
            [("店3", "2026-08-02 00:00:00"), ("店2", "2026-08-01 00:00:00")],
        )
        replace_snapshot.assert_called_once_with(
            client,
            snapshot,
            [{"fld_request_time": "2026-08-02 00:00:00"}, {"fld_request_time": "2026-08-01 00:00:00"}],
        )


if __name__ == "__main__":
    unittest.main()
