# SHEIN Activity Benchmark

## 目的

本 benchmark 定义 `opencli shein activity` 和 `scripts/sync-shein-activity-to-sheet.py` 的验收方法。重点验证正确性、幂等、DB skip、crawl/display window 分离、多店合并、只爬不写表、性能、重试和回归测试。

端到端测试需要：

- 一个安全 Maybe Sheet，不能直接用重要生产表做首次验证；
- 至少一个已登录且 Browser Bridge 可用的 SHEIN profile；
- 生产三店验收时需要 `店1/jegkb2wv`、`店2/m3cjm28a`、`店3/w2db43wa` 均已登录。

## 环境记录

| Field | Value |
|---|---|
| Date run | |
| Git commit | |
| Machine | |
| Network | |
| MaybeAI base URL | |
| Safe target sheet URL | |
| Raw DB workbook URI | |
| Store/profile | |
| Browser Bridge connected | yes/no |
| `opencli doctor` | |
| `opencli shein whoami` | |

## 基础命令

Doctor：

```bash
npm exec -- opencli doctor
```

Session preflight：

```bash
npm exec -- opencli --profile w2db43wa shein whoami -f json
```

Adapter smoke：

```bash
npm exec -- opencli --profile w2db43wa shein activity \
  --snapshotDate 2026-07-29 \
  --limitActivities 1 \
  --limitRows 5 \
  --requestTimeout 120 \
  -f json
```

Script dry run：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --profile w2db43wa \
  --store 店3 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<safe-doc>?gid=<gid>" \
  --start-date 2026-07-29 \
  --end-date 2026-07-29 \
  --limit-activities 1 \
  --limit-rows 5 \
  --dry-run
```

Raw DB crawl：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --profile w2db43wa \
  --store 店3 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<safe-doc>?gid=<gid>" \
  --raw-db-uri "https://www.maybe.ai/docs/spreadsheets/d/<raw-doc>?gid=0" \
  --raw-db \
  --etl-source raw-api \
  --start-date 2026-07-29 \
  --end-date 2026-07-29 \
  --skip-sheet-write
```

Write test：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --profile w2db43wa \
  --store 店3 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<safe-doc>?gid=<gid>" \
  --raw-db-uri "https://www.maybe.ai/docs/spreadsheets/d/<raw-doc>?gid=0" \
  --raw-db \
  --etl-source raw-api \
  --start-date 2026-07-29 \
  --end-date 2026-07-29 \
  --sheet-display-days 1 \
  --ensure-headers
```

Production three-store dry run：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store-config scripts/shein-activity-prod.json \
  --crawl-last-days 30 \
  --sheet-display-days 30 \
  --etl-source raw-api \
  --raw-db \
  --skip-sheet-write
```

Production raw workbook:

```text
https://www.maybe.ai/docs/spreadsheets/d/6a6b38cac5b0a12620ef6c91
```

## Unit Gates

Adapter：

```bash
npm run test:adapter -- clis/shein/activity.test.js
npm run test:adapter -- clis/shein/activity.test.js clis/shein/daily-traffic.test.js clis/shein/aftersales.test.js clis/shein/feedback.test.js
```

Script：

```bash
python3 scripts/sync-shein-activity-to-sheet.test.py
python3 scripts/sync-shein-activity-to-sheet.py --self-test
```

Manifest：

```bash
npm run build-manifest
```

Pass：

| Gate | Pass |
|---|---|
| Adapter tests | 100% pass |
| Script tests | 100% pass, no network |
| Adjacent SHEIN tests | No regression |
| Manifest | Includes `shein/activity` |

## 正确性验收

### Adapter Shape

运行 adapter smoke。

Pass：

- 输出是 JSON array；
- row count 在 `0..5` 内；如果 live 店铺当天没有活动商品，0 row 允许，但日志必须显示 list stage 成功；
- 每个非空 row 包含 `snapshot_date`、`activity_id`、`activity_name`、`activity_type_id`、`start_time`、`end_time`、`state`、`skc`、`sku_supplier_no`、`image_url`；
- raw fields 存在：`raw_activity_json`、`raw_detail_json` 或 `raw_json`；
- `snapshot_date` 等于请求的 `--snapshotDate`；
- JSON blob fields 不会进入业务 Sheet mapping。

Record：

| Metric | Value |
|---|---|
| activity list count | |
| detail row count | |
| output rows | |
| first list request URL | |
| first detail request URL | |
| missing required scalar count | |

### Request Semantics

运行：

```bash
npm exec -- opencli --profile w2db43wa shein activity \
  --snapshotDate 2026-07-29 \
  --insertStartTime "2026-07-29 00:00:00" \
  --insertEndTime "2026-07-29 23:59:59" \
  --pageSize 10 \
  --maxListPages 2 \
  --maxDetailPages 1 \
  --detailConcurrency 2 \
  --requestDelayMinMs 200 \
  --requestDelayMaxMs 800 \
  --limitActivities 2 \
  -f json
```

Pass：

- list request body 使用指定 `insert_start_time` / `insert_end_time`；
- list page 2 只递增 page number；
- detail request body 使用列表 row 的 `activity_id`；
- detail page 不超过 `maxDetailPages`；
- detail stage 并发不超过 `detailConcurrency`，请求日志里可看到 delay window 生效；
- output rows 不超过 `limitRows`，活动数量不超过 `limitActivities`；
- headers 不包含 cookie、host、content-length、sec-*。

### ETL Shape

运行 script dry run。

Pass：

- summary 包含 crawl window、display window、store、profile、fetched/skipped day count、raw row count、ETL row count；
- sample ETL row 只有 11 个 legacy header；
- `活动规格` 映射 `31/1/2/9/21`；
- `状态` 映射 `3/4/5/6`；
- `活动时间` 由开始/结束时间生成；
- 空详情或空 `活动商品skc` 时仍保留活动业务行，商品字段为空，以对齐 legacy play-be live 产物。

## 幂等验收

### First Raw Save

运行 raw DB crawl。

Pass：

- 缺失的 store/day 调用一次 `opencli shein activity`；
- 当天爬完立即写 raw staging worksheet；
- 随后立即调用 `excel__save_table_worksheet_to_mongodb`；
- save payload 包含 `data_date`、`uri`、`worksheet_name`；
- 0 row snapshot 也保存成功，并在 raw staging worksheet 写入 `record_type=empty_snapshot`；
- 本地没有生成 raw JSON 文件。
- `--skip-sheet-write` 未同时传 `--raw-db` 时应 fail fast，避免只爬不保存。

Record：

| Metric | Value |
|---|---|
| fetched days | |
| raw rows saved | |
| save calls | |
| snapshot days | |

### Rerun DB Skip

对同一 store/day 重跑默认 `--skip-existing-days`。

Pass：

- 脚本先读取 raw DB snapshot；
- raw DB 已有 `店铺 + 日期` snapshot 时标记 skipped；
- 不启动 `opencli shein activity` subprocess；
- 目标业务 Sheet 即使存在或不存在行，都不影响 skip；
- 退出码为 0。

Record：

| Metric | Value |
|---|---|
| raw snapshot days | |
| skipped day count | |
| OpenCLI fetch count | |

### Forced Refresh

运行：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --profile w2db43wa \
  --store 店3 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<safe-doc>?gid=<gid>" \
  --raw-db-uri "https://www.maybe.ai/docs/spreadsheets/d/<raw-doc>?gid=0" \
  --raw-db \
  --etl-source raw-api \
  --start-date 2026-07-29 \
  --end-date 2026-07-29 \
  --no-skip-existing-days \
  --skip-sheet-write
```

Pass：

- 即使 raw DB 有 snapshot，也重新调用 opencli；
- 新 snapshot 保存成功；
- display ETL 去重后不因重复 snapshot 产生重复业务行。

## Crawl/Display 分离验收

运行：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store-config scripts/shein-activity-prod.json \
  --crawl-last-days 60 \
  --sheet-display-days 30 \
  --etl-source raw-api \
  --raw-db \
  --skip-sheet-write
```

Pass：

- crawl planning 读取 60 天 raw DB snapshot；
- 每一天、每个店独立判断 skip/fetch；
- display read 只读取 30 天 raw DB snapshot；
- 日志分别打印 crawl window 和 display window；
- display window 不反向减少 crawl window。

Record：

| Metric | Value |
|---|---|
| crawl days checked | |
| display days read | |
| missing days fetched | |
| skipped days | |

## 多店合并验收

运行三店 write test，使用安全 Sheet。

Pass：

- 配置包含 `店1/jegkb2wv`、`店2/m3cjm28a`、`店3/w2db43wa`；
- 三店顺序处理，各自 raw worksheet 独立；
- 最终写入同一个 target worksheet，由 `--sheet-url` gid 解析；
- Sheet 内存在三店的 `店铺` 值；
- merge 保留其他店数据；
- duplicate key 不增加行数。

建议业务去重 key：

```text
店铺 + 活动名称 + 活动开始时间 + 活动商品skc + 活动商品供方货号
```

如果 raw row 有稳定 `activity_id`，内部先用：

```text
店铺 + activity_id + skc + sku_supplier_no
```

## 只爬不写表验收

运行 `--skip-sheet-write`。

Pass：

- 缺失日期仍然调用 opencli；
- `--raw-db` 时仍然逐日 save DB；
- 不调用 `list_worksheets`、目标 Sheet read、`update_data_keep_headers` 或 write verification；
- summary 显示 `sheet_write_skipped=true`；
- 目标业务 Sheet row count 不变。

## Sheet 写入验收

运行 write test。

Pass：

- header row 是 legacy 11 列；
- 目标 worksheet 由 `--sheet-url` 的 gid 解析；
- 写入 API 使用 `update_data_keep_headers`；
- data 从 row 2 开始；
- 不写 `raw_json`、`activity_id`、查询参数、价格库存等 raw-only 字段；
- 写后用明确 row range 验证至少一个新 ETL row 可见；
- 不使用 MaybeAI `filter_tokens`。

大表读取：

- 先调用 `/api/v1/excel_v2/worksheet/dimensions`；
- 按 `A1:K10001`、`A10002:K20001` 分块读取；
- 不探测超过 dimensions row count 的空 range。

## 性能验收

性能受 SHEIN 页面、账号权限和风控影响，阈值用于发现明显退化。

| Scenario | Target | Failure Threshold |
|---|---:|---:|
| `whoami` preflight | <= 30s | > 120s |
| adapter smoke, 1 activity, 5 rows | <= 150s | > 360s |
| adapter 1 day, first list page + first detail page | <= 240s | > 600s |
| script dry run, 1 store/day | <= 240s | > 600s |
| raw DB crawl/save, 1 store/day | <= 300s | > 720s |
| rerun DB skip | <= 60s | > 180s |
| three-store skip-sheet-write, 30-day mostly skipped | <= 300s | > 900s |

记录 wall-clock：

```bash
/usr/bin/time -p npm exec -- opencli --profile w2db43wa shein activity \
  --snapshotDate 2026-07-29 \
  --limitActivities 1 \
  --limitRows 5 \
  -f json >/tmp/shein-activity-smoke.json
```

Record：

| Metric | Value |
|---|---|
| real seconds | |
| rows returned | |
| activities processed | |
| rows per second | |

## 重试和可靠性验收

连续运行 adapter smoke 5 次。

Pass：

- 至少 4/5 成功；
- 失败可分类为 auth、capture timeout、SHEIN API non-zero、network retry exhausted、unexpected；
- retry 日志包含 attempt、activity id、page num；
- 风控敏感时可通过降低 `detailConcurrency`、提高 `requestDelayMinMs/requestDelayMaxMs` 恢复稳定；
- 不在 repo root、`clis/shein`、`scripts` 下留下临时 JSON 文件。

Record：

| Run | Result | Duration | Row Count | Error Class |
|---|---|---:|---:|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

## 回归测试

Adjacent SHEIN commands：

```bash
npm run test:adapter -- clis/shein/daily-traffic.test.js clis/shein/aftersales.test.js clis/shein/feedback.test.js
python3 -m unittest scripts/sync-shein-daily-traffic-to-sheet.test.py
```

Optional live smoke：

```bash
npm exec -- opencli --profile w2db43wa shein daily-traffic \
  --startDate 2026-07-29 \
  --endDate 2026-07-29 \
  --limit 1 \
  -f json
```

Pass：

- 每日流量、售后、评价 unit tests 不回归；
- manifest 仍包含既有 SHEIN commands；
- 新 activity helper 没有改变共享 SHEIN 登录或 header sanitize 行为。

## 最终报告模板

```markdown
# SHEIN Activity Benchmark Report

Commit:
Safe sheet:
Raw DB workbook:
Profiles:
Date window:

## Summary

- Unit gates:
- Adapter correctness:
- Raw DB save:
- DB skip:
- Crawl/display separation:
- Sheet write:
- Multi-store:
- Performance:
- Reliability:
- Regression:

## Results

| Gate | Status | Notes |
|---|---|---|
| Unit gates | | |
| Adapter smoke | | |
| Request semantics | | |
| Dry run | | |
| First raw save | | |
| Rerun DB skip | | |
| Crawl/display split | | |
| Multi-store merge | | |
| Skip sheet write | | |
| Sheet write | | |
| Performance | | |
| Reliability | | |
| Regression | | |

## Residual Risks

-
```

## Pass Definition

实现满足以下条件时，可认为 benchmark 通过：

- 所有 unit gates 通过；
- adapter 能用已登录 profile 返回结构正确的活动 raw rows；
- raw DB save 按店铺/日期一天一次执行，0 row snapshot 也可保存；
- rerun skip 只由 raw DB snapshot 决定；
- crawl window 和 display window 分离；
- `--skip-sheet-write` 不读写业务 Sheet；
- 三店数据合并进同一个 target worksheet；
- Sheet header 是 legacy 11 列且无 raw JSON 字段；
- 写后 range verification 通过；
- 可靠性至少 4/5；
- 每日流量、售后、评价无回归。
