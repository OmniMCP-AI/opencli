"""Engine-aware Base table read/write primitives for standalone sync scripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, urlparse


METADATA_PATH = "/api/v1/excel_v2/worksheet/metadata"
# The public dev deployment exposes table APIs through the legacy-compatible
# /excel prefix while metadata is registered only under /excel_v2.
TABLE_READ_PATH = "/api/v1/excel/table/read"
TABLE_REPLACE_PATH = "/api/v1/excel/table/record/replace"
# Daily traffic Base tables can contain many historical rows. Read the full
# working set in one request in the normal case; pagination remains available
# for tables larger than this limit.
TABLE_READ_PAGE_SIZE = 100000


class PostClient(Protocol):
    def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: int = 30,
    ) -> dict[str, Any]: ...


class BaseSyncError(ValueError):
    """Raised when a standalone sync cannot safely use a Base table."""


@dataclass(frozen=True)
class Target:
    uri: str
    document_id: str
    gid: int
    worksheet_name: str
    engine: Literal["sheet", "base"]
    table_id: str | None


@dataclass(frozen=True)
class Field:
    field_id: str
    name: str
    logical_type: str
    is_formula: bool = False
    is_read_only: bool = False


@dataclass(frozen=True)
class Snapshot:
    target: Target
    revision: int
    fields: Sequence[Field]
    rows: Sequence[dict[str, Any]]

    def records_from_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        fields_by_name = _fields_by_name(self.fields)
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise BaseSyncError("Each incoming row must be a mapping")
            record: dict[str, Any] = {}
            for name, value in row.items():
                field = fields_by_name.get(str(name))
                if field is None:
                    raise BaseSyncError(f"Unknown incoming header: {name}")
                if field.is_formula or field.is_read_only:
                    if _is_blank(value):
                        continue
                    kind = "Formula" if field.is_formula else "Read-only"
                    raise BaseSyncError(f"{kind} field has input: {field.name}")
                record[field.field_id] = _coerce_value(field, value)
            records.append(record)
        return records


def resolve_target(
    client: PostClient,
    url: str,
    worksheet_name: str | None,
) -> Target:
    uri, document_id, gid = _parse_target_url(url)
    metadata = _require_success(client.post(METADATA_PATH, {"uri": uri}, timeout=30), METADATA_PATH)
    worksheet = _select_worksheet(
        metadata,
        gid=gid,
        worksheet_name=worksheet_name,
    )
    resolved_gid = _integer(worksheet.get("gid") or worksheet.get("sheet_id"))
    if resolved_gid is None:
        raise BaseSyncError("worksheet/metadata returned a worksheet without gid")
    resolved_name = _worksheet_name(worksheet)
    if not resolved_name:
        raise BaseSyncError("worksheet/metadata returned a worksheet without worksheet_name")
    data_engine = str(worksheet.get("data_engine") or worksheet.get("engine") or "sheet").lower()
    engine: Literal["sheet", "base"] = "base" if data_engine == "base" else "sheet"
    table_id = _optional_string(worksheet.get("table_id"))
    if engine == "base" and not table_id:
        raise BaseSyncError("Base worksheet metadata is missing table_id")
    return Target(
        uri=uri,
        document_id=document_id,
        gid=resolved_gid,
        worksheet_name=resolved_name,
        engine=engine,
        table_id=table_id,
    )


def read_snapshot(client: PostClient, target: Target) -> Snapshot:
    if target.engine != "base" or not target.table_id:
        raise BaseSyncError("read_snapshot requires a resolved Base target")
    fields: tuple[Field, ...] | None = None
    rows: list[dict[str, Any]] = []
    revision: int | None = None
    offset = 0

    while True:
        response = _require_success(
            client.post(
                TABLE_READ_PATH,
                {
                    "document_id": target.document_id,
                    "gid": target.gid,
                    "table_id": target.table_id,
                    "worksheet_name": target.worksheet_name,
                    "limit": TABLE_READ_PAGE_SIZE,
                    "offset": offset,
                },
                timeout=30,
            ),
            TABLE_READ_PATH,
        )
        table = _table_response(response)
        page_fields = _fields_from_response(table)
        if fields is None:
            fields = page_fields
        elif page_fields != fields:
            raise BaseSyncError("Base table schema changed while reading pages")
        page_revision = _integer(table.get("revision"))
        if page_revision is None:
            raise BaseSyncError("Base table/read did not return revision")
        if revision is None:
            revision = page_revision
        elif revision != page_revision:
            raise BaseSyncError("Base table revision changed while reading pages")

        fields_by_id = {field.field_id: field for field in fields}
        records = table.get("records")
        if not isinstance(records, list):
            raise BaseSyncError("Base table/read returned invalid records")
        for raw_record in records:
            if not isinstance(raw_record, Mapping):
                continue
            raw_fields = raw_record.get("fields")
            if not isinstance(raw_fields, Mapping):
                continue
            row = {
                field.name: raw_fields[field_id]
                for field_id, field in fields_by_id.items()
                if field_id in raw_fields
            }
            rows.append(row)

        has_more_marker = table.get("has_more", table.get("hasMore"))
        # Some Base responses omit the pagination marker. In that case, a
        # full page is evidence that another page may exist.
        has_more = (
            len(records) >= TABLE_READ_PAGE_SIZE
            if has_more_marker is None
            else _boolean(has_more_marker)
        )
        if not has_more:
            break
        if not records:
            raise BaseSyncError("Base table/read declared another page without records")
        offset += len(records)

    if fields is None or revision is None:
        raise BaseSyncError("Base table/read returned no table snapshot")
    return Snapshot(target=target, revision=revision, fields=fields, rows=rows)


def replace_snapshot(
    client: PostClient,
    snapshot: Snapshot,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target = snapshot.target
    if target.engine != "base" or not target.table_id:
        raise BaseSyncError("replace_snapshot requires a resolved Base target")
    payload = {
        "document_id": target.document_id,
        "gid": target.gid,
        "table_id": target.table_id,
        "worksheet_name": target.worksheet_name,
        "records": [dict(record) for record in records],
        "expected_revision": snapshot.revision,
    }
    return _require_success(client.post(TABLE_REPLACE_PATH, payload, timeout=30), TABLE_REPLACE_PATH)


def require_base_compatible_options(
    target: Target,
    *,
    read_range: str | None,
    ensure_headers: bool,
) -> None:
    if target.engine != "base":
        return
    if read_range:
        raise BaseSyncError("--read-range is Sheet-only for a Base target")
    if ensure_headers:
        raise BaseSyncError("--ensure-headers is Sheet-only; migrate Base fields explicitly")


def _parse_target_url(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    marker = "/spreadsheets/d/"
    if marker not in parsed.path:
        raise BaseSyncError(f"Cannot parse document id from sheet URL: {url}")
    document_id = parsed.path.split(marker, 1)[1].split("/", 1)[0].strip()
    if not document_id:
        raise BaseSyncError(f"Cannot parse document id from sheet URL: {url}")
    query = parse_qs(parsed.query)
    gid_values = query.get("gid")
    gid = _integer(gid_values[-1]) if gid_values else None
    if gid_values and gid is None:
        raise BaseSyncError(f"Cannot parse gid from sheet URL: {url}")
    return url, document_id, gid


def _select_worksheet(
    response: Mapping[str, Any],
    *,
    gid: int | None,
    worksheet_name: str | None,
) -> Mapping[str, Any]:
    worksheets = _worksheets(response)
    if gid is not None:
        for worksheet in worksheets:
            candidate_gid = _integer(worksheet.get("gid") or worksheet.get("sheet_id"))
            if candidate_gid == gid:
                return worksheet
        raise BaseSyncError(f"worksheet/metadata did not return gid={gid}")
    if worksheet_name:
        matches = [item for item in worksheets if _worksheet_name(item) == worksheet_name]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise BaseSyncError(f"worksheet/metadata did not return worksheet_name={worksheet_name}")
        raise BaseSyncError(f"worksheet/metadata returned multiple worksheets named {worksheet_name}")
    raise BaseSyncError("Base target requires gid or worksheet_name")


def _worksheets(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for container in (response, _mapping(response.get("data")), _mapping(response.get("result"))):
        worksheets = container.get("worksheets")
        if isinstance(worksheets, list):
            return [worksheet for worksheet in worksheets if isinstance(worksheet, Mapping)]
    raise BaseSyncError("worksheet/metadata returned invalid worksheets")


def _table_response(response: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _mapping(response.get("data"))
    return data if data else response


def _fields_from_response(table: Mapping[str, Any]) -> tuple[Field, ...]:
    raw_fields = table.get("fields")
    if not isinstance(raw_fields, list):
        raise BaseSyncError("Base table/read returned invalid fields")
    fields: list[Field] = []
    field_ids: set[str] = set()
    names: set[str] = set()
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            raise BaseSyncError("Base table/read returned a non-object field")
        field_id = _optional_string(raw_field.get("field_id") or raw_field.get("id"))
        name = _optional_string(raw_field.get("name"))
        if not field_id or not name:
            raise BaseSyncError("Base table/read returned a field without id or name")
        if field_id in field_ids or name in names:
            raise BaseSyncError("Base table/read returned duplicate field metadata")
        logical_type = str(raw_field.get("logical_type") or raw_field.get("type") or "text")
        fields.append(
            Field(
                field_id=field_id,
                name=name,
                logical_type=logical_type,
                is_formula=_boolean(raw_field.get("is_formula")) or logical_type.lower() == "formula",
                is_read_only=_boolean(raw_field.get("is_read_only")) or _boolean(raw_field.get("read_only")),
            )
        )
        field_ids.add(field_id)
        names.add(name)
    return tuple(fields)


def _fields_by_name(fields: Sequence[Field]) -> dict[str, Field]:
    result: dict[str, Field] = {}
    for field in fields:
        if not field.field_id.strip() or not field.name.strip():
            raise BaseSyncError("Base schema contains a blank field id or name")
        if field.name in result:
            raise BaseSyncError(f"Duplicate Base field name: {field.name}")
        result[field.name] = field
    return result


def _coerce_value(field: Field, value: Any) -> Any:
    logical_type = field.logical_type.strip().lower()
    if value is None:
        return None
    if logical_type in {"integer", "int"}:
        return _coerce_integer(field.name, value)
    if logical_type in {"number", "float", "double", "decimal", "currency", "percent"}:
        return _coerce_number(field.name, value)
    if logical_type in {"boolean", "bool"}:
        return _coerce_boolean(field.name, value)
    return value


def _coerce_integer(field_name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise BaseSyncError(f"Integer field has boolean input: {field_name}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise BaseSyncError(f"Invalid integer input for field: {field_name}") from error
    if not number.is_finite() or number != number.to_integral_value():
        raise BaseSyncError(f"Invalid integer input for field: {field_name}")
    return int(number)


def _coerce_number(field_name: str, value: Any) -> int | float:
    if isinstance(value, bool):
        raise BaseSyncError(f"Number field has boolean input: {field_name}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise BaseSyncError(f"Invalid number input for field: {field_name}") from error
    if not number.is_finite():
        raise BaseSyncError(f"Invalid number input for field: {field_name}")
    return int(number) if number == number.to_integral_value() else float(number)


def _coerce_boolean(field_name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise BaseSyncError(f"Invalid boolean input for field: {field_name}")


def _require_success(response: Any, endpoint: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise BaseSyncError(f"MaybeAI {endpoint} returned a non-object response")
    if response.get("success") is False:
        raise BaseSyncError(f"MaybeAI {endpoint} did not succeed: {response}")
    return response


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _worksheet_name(worksheet: Mapping[str, Any]) -> str | None:
    for key in ("worksheet_name", "title", "name", "sheet_name"):
        name = _optional_string(worksheet.get(key))
        if name:
            return name
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
