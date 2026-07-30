# SHEIN Daily Traffic Benchmark

## Purpose

This benchmark defines how to judge the `opencli shein daily-traffic` adapter and `scripts/sync-shein-daily-traffic-to-sheet.py` script once implemented. It measures correctness, idempotency, performance, and operational reliability for one store/profile at a time.

The benchmark is not a synthetic performance race. SHEIN is a live authenticated SaaS page, so the pass/fail criteria prioritize stable business output and safe writes over absolute speed.

## Scope

In scope:

- one Chrome/OpenCLI profile per store;
- one-day fetch;
- small date-range fetch;
- dry-run ETL;
- MaybeAI Sheet write;
- rerun skip behavior;
- raw payload fields in adapter output for optional DB persistence;
- no JSON blob columns in sheet output.

Out of scope:

- play-be migration;
- production DB write validation;
- multi-store scheduler;
- long historical backfill beyond the measured date range;
- comparing against stale legacy task payloads as a hard truth when SHEIN live values differ.

## Environment Record

Fill this before each live benchmark run:

| Field | Value |
|---|---|
| Date run | |
| Git commit | |
| Machine | |
| Network | |
| OpenCLI profile | |
| Store name | |
| Target sheet URL | |
| Browser Bridge connected | yes/no |
| `opencli doctor` result | |
| SHEIN login preflight result | |

## Commands

Doctor:

```bash
npm exec -- opencli doctor
```

Session preflight:

```bash
npm exec -- opencli --profile profile1 shein whoami -f json
```

Adapter smoke:

```bash
npm exec -- opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --limit 5 \
  --requestTimeout 120 \
  -f json
```

Script dry run:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28 \
  --limit 5 \
  --dry-run
```

Script write test:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28 \
  --limit 5
```

Rerun skip test:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28
```

## Unit Gates

Adapter:

```bash
npm run test:adapter -- clis/shein/daily-traffic.test.js
npm run test:adapter -- clis/shein/daily-traffic.test.js clis/shein/aftersales.test.js clis/shein/feedback.test.js
```

Script:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py --self-test
```

Build manifest:

```bash
npm run build-manifest
```

Pass criteria:

| Gate | Pass |
|---|---|
| Adapter tests | 100% pass |
| Adjacent SHEIN adapter tests | 100% pass |
| Script self-test | 100% pass |
| Manifest build | succeeds and includes `shein/daily-traffic` |

## Correctness Benchmarks

### Adapter Shape

Run adapter smoke with `--limit 5`.

Pass:

- output is a JSON array;
- row count is between `1` and `5`;
- every row has all declared adapter columns;
- every row has raw payload fields for DB persistence: `raw_json`, `prom_inf_ing_json`, `right_campaign_json`;
- every row has `date = requested day` as `YYYY-MM-DD`;
- every row has `queried_start_date = queried_end_date = requested day` as `YYYYMMDD`;
- `skc` or `spu` is non-empty on at least 95% of rows in an unbounded run;
- `goods_name` is non-empty on at least 95% of rows in an unbounded run.

Record:

| Metric | Value |
|---|---|
| adapter row count | |
| first capture URL | |
| total count from SHEIN | |
| columns count | |
| missing required field count | |
| raw payload field count | |

### Request Semantics

Run one-day adapter command with `--pageSize 10 --maxPages 2`.

Pass:

- page 1 request body uses `dt/startDate/endDate` equal to requested day `YYYYMMDD`;
- page 2 request body increments only `pageNum`;
- `countrySite` follows CLI or captured fallback rules;
- total output rows do not exceed `20`;
- command stops cleanly without fetching page 3.

Record:

| Metric | Value |
|---|---|
| page size | |
| max pages | |
| observed fetch pages | |
| output rows | |

### ETL Shape

Run script dry run.

Pass:

- script resolves one store/profile pair;
- dry run does not call MaybeAI write APIs;
- summary includes requested date range, fetched day count, skipped day count, adapter rows, ETL rows;
- sample ETL row contains target sheet headers only;
- sample ETL row has no JSON blob fields;
- `点击率` equals `商品访客（访问） / 商品页面访客` when denominator is non-zero;
- `商品当前状态`, `上架状态`, `是否新品`, and `是否多色` are mapped to business text.

Record:

| Metric | Value |
|---|---|
| fetched day count | |
| skipped day count | |
| adapter rows | |
| ETL rows | |
| JSON blob fields in sample | |

## Idempotency Benchmarks

### First Write

Run script write test against a safe target worksheet.

Pass:

- write API is `update_data_keep_headers`;
- data starts at row 2;
- headers remain intact;
- read-back verification finds at least one row for each fetched `店铺 + 日期` that produced ETL rows;
- verification reads the expected written row range, not a filtered `read_sheet` query;
- no rows for other stores are removed.

Record:

| Metric | Value |
|---|---|
| existing rows before | |
| fresh rows | |
| merged rows after | |
| preserved other-store rows | |
| verification attempts | |
| verification ranges | |

### Large Sheet Read

Run against an ETL worksheet with more than 10,000 rows, such as a 30-day multi-store output.

Pass:

- the initial existing-row read uses explicit row ranges, starting with `A1:AD10001`;
- additional chunks continue as `A10002:AD20001`, `A20002:AD30001`, and so on until a short chunk is returned;
- old dates beyond the first 10,000 returned rows are still available for `--skip-existing-days`;
- no `filter_tokens` are sent to MaybeAI `read_sheet`.

Record:

| Metric | Value |
|---|---|
| sheet rows | |
| chunk count | |
| chunk ranges | |
| old-date skip verified | |

### Rerun Skip

Run the same store/day again with default `--skip-existing-days`.

Pass:

- script reads the sheet before SHEIN fetch;
- date is marked skipped because `店铺 + 日期` exists;
- no `opencli shein daily-traffic` subprocess is launched for the skipped day;
- script exits `0`;
- sheet row count remains unchanged.

Record:

| Metric | Value |
|---|---|
| skipped day count | |
| OpenCLI fetch count | |
| row count before | |
| row count after | |

### Forced Merge

Run same store/day with `--no-skip-existing-days --limit 5`.

Pass:

- OpenCLI fetch runs;
- rows merge by `店铺 + 日期 + 商品货号 + 主商品货号 + 供应商SKU`;
- duplicate unique keys do not increase row count;
- newly seen unique keys append;
- final rows sort by `日期` desc, then `商品货号` asc.

Record:

| Metric | Value |
|---|---|
| existing unique keys | |
| fresh unique keys | |
| duplicate keys | |
| final row count | |

## Performance Benchmarks

Targets are advisory because SHEIN page load and risk controls vary by account and network.

| Scenario | Target | Failure Threshold |
|---|---:|---:|
| `whoami` preflight | <= 30s | > 120s |
| adapter smoke, one day, `--limit 5` | <= 120s | > 300s |
| adapter one day, full first page | <= 180s | > 420s |
| script dry run, one day, `--limit 5` | <= 180s | > 360s |
| script write, one day, `--limit 5` | <= 240s | > 480s |
| rerun skip | <= 60s | > 180s |

Record wall-clock with `/usr/bin/time -p`:

```bash
/usr/bin/time -p npm exec -- opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --limit 5 \
  -f json >/tmp/shein-daily-traffic-smoke.json
```

Metrics:

| Metric | Value |
|---|---|
| real seconds | |
| user seconds | |
| sys seconds | |
| rows returned | |
| rows per second | |

## Reliability Benchmarks

Run the adapter smoke 5 times serially against the same profile.

Pass:

- at least 4 of 5 runs succeed;
- failures are typed enough to classify as auth, capture timeout, SHEIN API error, network retry exhaustion, or unexpected;
- no run leaves temp files in repo root, `clis/shein`, or `scripts`.

Record:

| Run | Result | Duration | Row Count | Error Class |
|---|---|---:|---:|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

## Regression Benchmarks

Adjacent SHEIN commands must still pass their unit tests and one smoke command when credentials/profile are available:

```bash
npm run test:adapter -- clis/shein/aftersales.test.js clis/shein/feedback.test.js
```

Optional live smoke:

```bash
npm exec -- opencli --profile profile1 shein aftersales --limit 1 -f json
npm exec -- opencli --profile profile1 shein feedback --limit 1 -f json
```

Pass:

- unit tests pass;
- daily-traffic changes do not modify aftersales/feedback behavior;
- no shared helper change causes column drift.

## Final Benchmark Report Template

```markdown
# SHEIN Daily Traffic Benchmark Report

Commit:
Profile:
Store:
Date range:
Target sheet:

## Summary

- Adapter correctness:
- Script ETL:
- Sheet write:
- Rerun skip:
- Performance:
- Reliability:

## Results

| Gate | Status | Notes |
|---|---|---|
| Unit gates | | |
| Adapter smoke | | |
| Request semantics | | |
| Script dry run | | |
| First write | | |
| Rerun skip | | |
| Forced merge | | |
| Performance | | |
| Reliability | | |
| Regression | | |

## Residual Risks

- 
```

## Pass Definition

The implementation is benchmark-passing when:

- all unit gates pass;
- adapter smoke returns correctly shaped scalar rows plus raw payload fields;
- no JSON blob fields appear in sheet output;
- dry run completes without writing;
- first write is visible in MaybeAI Sheet;
- rerun skip avoids SHEIN fetch for existing `店铺 + 日期`;
- forced merge does not duplicate unique keys;
- reliability is at least 4/5 serial smoke runs;
- no unrelated SHEIN adapter tests regress.
