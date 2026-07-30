# SHEIN

**Mode**: 🔐 Browser · **Primary domain**: `sso.geiwohuo.com`

OpenCLI supports SHEIN seller GSP session checks, aftersales order export, product feedback export, and daily traffic product analytics through a live Chrome profile with the Browser Bridge extension enabled.

## Commands

| Command | Description |
|---------|-------------|
| `opencli shein login` | Open the SHEIN SSO login page, optionally autofill credentials, and wait for the GSP aftersales session to become usable |
| `opencli shein whoami` | Probe whether the current SHEIN GSP session is ready |
| `opencli shein aftersales` | Export SHEIN aftersales orders and flatten each order by goods row |
| `opencli shein feedback` | Export SHEIN product feedback rows |
| `opencli shein daily-traffic` | Export SHEIN daily product traffic analytics rows |

## Usage Examples

```bash
# Login with environment-provided credentials
SHEIN_USERNAME=... SHEIN_PASSWORD=... \
opencli --profile profile1 shein login -f json

# Check the current GSP session
opencli --profile profile1 shein whoami -f json

# Export the first 10 aftersales goods rows
opencli --profile profile1 shein aftersales --limit 10 -f json

# Export aftersales rows newer than a known request time
opencli --profile profile1 shein aftersales \
  --sinceRequestTime "2026-07-06 19:26:29" \
  --requestTimeout 120 \
  -f json

# Export product feedback for a time window
opencli --profile profile1 shein feedback \
  --sinceCommentTime "2026-07-01 00:00:00" \
  --untilCommentTime "2026-07-07 23:59:59" \
  --requestTimeout 120 \
  -f json

# Export daily product traffic analytics for one day
opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --limit 20 \
  --requestTimeout 120 \
  -f json

# Export daily product traffic analytics for a date range
opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-26 \
  --endDate 2026-07-28 \
  --pageSize 100 \
  -f json
```

## Login And Profiles

- The adapter uses the Browser Bridge profile selected by `opencli --profile`, not a Chrome profile folder path.
- Run `opencli profile list` to see connected Browser Bridge profile ids and aliases.
- Use `opencli profile rename <id> profile1` to give a connected profile a stable alias.
- The selected Chrome profile must already have the Browser Bridge extension installed and connected.
- `opencli shein login` reads `--username` / `--password`, or the `SHEIN_USERNAME` / `SHEIN_PASSWORD` environment variables.
- `whoami` and data commands depend on the SHEIN GSP subsystem session, not just the SSO login form being submitted.

## Aftersales Export

`opencli shein aftersales` opens:

```text
https://sso.geiwohuo.com/#/gsp/order-management/after-sales-list
```

It captures the first `/gsp/aftersalesOrder/list` request from the page, replays list pagination through the page session, then captures order detail and evidence requests for fields that are not present on the list response.

### Aftersales Options

| Option | Description |
|--------|-------------|
| `--limit <n>` | Maximum number of aftersales orders to process. Omit for all pages available from the list response. |
| `--sinceRequestTime <time>` | Keep rows with `requestTime` greater than this value. Accepts `YYYY-M-D` or `YYYY-M-D HH:mm[:ss]`. |
| `--maxPages <n>` | Maximum list pages to fetch, useful for bounded tests. |
| `--timeout <seconds>` | Whole command timeout. Defaults to `1800`. |
| `--requestTimeout <seconds>` | Timeout for a single page-side API capture or request. Defaults to `60`. |
| `--retryAttempts <n>` | Retry count for page-side API requests. Defaults to `3`. |
| `--retryDelayMs <ms>` | Base retry delay. Defaults to `1000`. |

### Aftersales Output Fields

```text
requestTime, aftersalesOrderNo, returnOrderNo, orderNo, site,
orderSubStatusName, aftersalesResolutionPlanName, refundMethod,
sellerResolutionPlanName, sellerInstruction, etaTime, goodsThumb,
goodsTitle, goodsSn, suffix, skuSn, quantity, afterSalesReason,
buyerInstruction, returnExpressNos, return_attachments, priceAmount,
checkEstimateIncomeMoney, returnExpense, performancePrice,
promotionAmount, refundRatio, estimateIncomeMoney, goodsSettlePrice,
goodsServiceCharge, freezeAmount
```

Notes:

- `returnExpressNos` comes from the list response `returnExpressInfoList[].expressNo`.
- `buyerInstruction`, `sellerResolutionPlanName`, and `sellerInstruction` come from the evidence work order detail capture when available.
- `refundRatio` comes from the aftersales detail response.
- `refundMethod` is derived from `aftersalesResolutionPlanName` and `refundRatio`.
- `afterSalesReason` is normalized to a comma-separated string.

## Product Feedback Export

`opencli shein feedback` opens:

```text
https://sso.geiwohuo.com/#/mgs/store-management/product-feedback
```

It captures `/mgs-api-prefix/goods/comment/list`, injects the requested comment time range into the captured request body, replays page 1 and later pages through the browser session, and keeps a local comment-time filter as a final guard.

### Feedback Options

| Option | Description |
|--------|-------------|
| `--limit <n>` | Maximum number of feedback rows. |
| `--perPage <n>` | Page size for replayed list requests. |
| `--maxPages <n>` | Maximum list pages to fetch. |
| `--sinceCommentTime <time>` | Keep rows with `commentTime` greater than this value. Accepts `YYYY-M-D` or `YYYY-M-D HH:mm[:ss]`. |
| `--untilCommentTime <time>` | Keep rows with `commentTime` less than or equal to this value. Accepts `YYYY-M-D` or `YYYY-M-D HH:mm[:ss]`. |
| `--timeout <seconds>` | Whole command timeout. Defaults to `3600`. |
| `--requestTimeout <seconds>` | Timeout for a single page-side API capture or request. Defaults to `60`. |
| `--retryAttempts <n>` | Retry count for page-side API requests. Defaults to `3`. |
| `--retryDelayMs <ms>` | Base retry delay. Defaults to `1000`. |

### Feedback Output Fields

```text
commentId, countrySiteCn, supplierId, goodsTitle, goodsThumb,
goodsAttribute, goodsUrl, goodSn, spu, skc, sku, goodsCommentStar,
goodsCommentStarName, goodsCommentContent, goodsCommentImages,
logisticCommentStar, logisticCommentContent, commentTime, orderTime,
billNo, memberOverallFitLabelList, badCommentLabelList
```

When time filters are passed, the adapter sets `startCommentTime` and `commentEndTime` on the replayed list API body before fetching page 1 and later pages. `goodsCommentImages` is returned as an array. `memberOverallFitLabelList` and `badCommentLabelList` are flattened to comma-separated label strings.

## Daily Traffic Export

`opencli shein daily-traffic` opens:

```text
https://sso.geiwohuo.com/#/sbn/merchandise/details
```

It captures `/sbn/new_goods/get_skc_diagnose_list`, preserves the page filters from the captured request body, overrides the requested day fields, and replays pagination through the authenticated browser session. Date ranges are expanded one day at a time.

### Daily Traffic Options

| Option | Description |
|--------|-------------|
| `--startDate <date>` | Start date. Accepts `YYYY-MM-DD` or `YYYYMMDD`. Defaults to yesterday when both dates are omitted. |
| `--endDate <date>` | End date. Accepts `YYYY-MM-DD` or `YYYYMMDD`. Defaults to `startDate` when omitted. |
| `--areaCd <code>` | Optional `areaCd`; falls back to the captured request body, then `cn`. |
| `--countrySite <value>` | Optional comma-separated `countrySite`; falls back to the captured body array/string, then `shein-all`. |
| `--pageSize <n>` | Page size for replayed requests. Falls back to the captured request body, then `100`. |
| `--limit <n>` | Maximum returned rows across the requested date range. |
| `--maxPages <n>` | Maximum pages fetched per day, useful for bounded tests. |
| `--timeout <seconds>` | Whole command timeout. Defaults to `3600`. |
| `--requestTimeout <seconds>` | Timeout for a single page-side API capture or request. Defaults to `60`. |
| `--retryAttempts <n>` | Retry count for page-side API requests. Defaults to `3`. |
| `--retryDelayMs <ms>` | Base retry delay. Defaults to `1000`. |

If `startDate` is later than `endDate`, the adapter swaps them before expanding the daily range.

### Daily Traffic Output Fields

```text
date, queried_start_date, queried_end_date, total_count, page_num,
request_url, goods_name, img_url, spu, skc, sku_supplier_no,
new_goods_tag, layer_name, onsale_flag, sale_flag, multicolor_flag,
goods_uv_idx, eps_uv_idx, bounce_uv_idx, bounce_rate,
search_click_cnt, like_cnt, cart_uv_idx, cart_pv_idx,
gds_cart_ctr_idx, pay_uv_idx, pay_order_cnt, gmv, gds_pay_ctr_idx,
sale_uv_idx, sale_cnt, sale_gmv, gds_sale_ctr_idx, confirm_ctr_idx,
total_quality_level, total_comment_cnt, bad_comment_cnt, bad_comment_rate,
return_order_cnt, return_qty, new_cate_1_name, new_cate_2_name,
new_cate_3_name, new_cate_4_name, brand, list_name, list_type,
list_rank, prom_tag, prom_names, prom_ids, prom_inf_ing_json,
right_campaign_json, raw_json
```

Notes:

- `date` is `YYYY-MM-DD`; `queried_start_date` and `queried_end_date` are the same requested day as `YYYYMMDD`.
- Campaign names and ids come from `promCampaign.promInfIng[]` and are joined with ` | `.
- `prom_inf_ing_json`, `right_campaign_json`, and `raw_json` are emitted only for raw DB persistence. The daily traffic Sheet sync omits the legacy JSON blob columns.

## MaybeAI Sheet Sync Scripts

Helper scripts sync SHEIN CLI output into MaybeAI Sheet with `update_data_keep_headers`.

They require:

```bash
export MAYBEAI_API_TOKEN=...
export SHEIN_USERNAME=...
export SHEIN_PASSWORD=...
```

All scripts:

- Run `opencli shein whoami` before fetching data.
- Run `opencli shein login` first when the GSP session is unavailable.
- Read existing sheet data without a fixed range by default.
- Merge rows by the script-specific unique key.
- Sort merged rows descending by the business time column before writing.
- Write data rows with `update_data_keep_headers`, preserving the existing header row.
- Append structured Python `logging` output to one daily log file by default.

Aftersales and feedback scripts save raw CLI JSON as timestamped files. The daily traffic script does not write local raw JSON files; when `--raw-db` is provided, it writes the fetched day to the raw worksheet and calls `excel__save_table_worksheet_to_mongodb`.

### Sync Aftersales To Sheet

Script:

```bash
python3 scripts/sync-shein-aftersales-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<doc-id>?gid=<gid>" \
  --store 店3
```

Important options:

| Option | Description |
|--------|-------------|
| `--since-request-time <time>` | Explicit incremental cutoff. If omitted, the script reads the sheet and uses the max `退款申请时间` for the selected store. |
| `--limit <n>` | Optional bounded test limit. |
| `--max-pages <n>` | Optional bounded page count. |
| `--profile <id-or-alias>` | Browser Bridge profile id or alias. |
| `--sheet-url <url>` | Target MaybeAI spreadsheet URL with `gid`. |
| `--store <name>` | Value written to the `店铺` column. Defaults to `店3`. |
| `--log-dir <dir>` | Directory for daily log files. Defaults to `artifacts/shein-aftersales/logs`. |
| `--raw-output-dir <dir>` | Directory for per-run raw SHEIN JSON files. Defaults to `artifacts/shein-aftersales/raw`. |
| `--request-timeout <seconds>` | Passed to `opencli shein aftersales --requestTimeout`. |
| `--attempts <n>` | Whole SHEIN CLI retry attempts. Defaults to `3`. |
| `--preflight-login` / `--no-preflight-login` | Enable or disable the `whoami` preflight. Enabled by default. |
| `--recalculate-formulas` / `--no-recalculate-formulas` | Trigger MaybeAI `recalculate_formulas` after a successful sheet write. Enabled by default; failures are logged as warnings and do not fail the sync. |
| `--recalculate-sheet-url <url>` | Optional MaybeAI spreadsheet URL to recalculate after writing. Defaults to `--sheet-url`; use this when data is written to one `gid` but formulas live on another `gid`. |
| `--recalculate-worksheet-name <name>` | Optional `worksheet_name` included in the `recalculate_formulas` payload. Omitted by default. |

Raw JSON is saved as:

```text
artifacts/shein-aftersales/raw/<店铺>售后数据-YYYYMMDD-HHMMSS.json
```

Daily logs are appended to:

```text
artifacts/shein-aftersales/logs/YYYY-MM-DD.log
```

Each log line includes a timestamp, level, and message.

Sheet headers:

```text
店铺,站点,退款申请时间,退款产品图片,售后单号,订单号,商品SKU,售后处理方案,售后单处理状态,售后申请类型,退款原因描述,退款附件,商品结算总金额,退货率约服务费,预计退货总支出,是否已退款,退款方式,退回单号,备注(退款解析)
```

Unique key:

```text
店铺 + 站点 + 退款申请时间 + 售后单号 + 订单号 + 商品SKU
```

### Sync Product Feedback To Sheet

Script:

```bash
python3 scripts/sync-shein-feedback-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<doc-id>?gid=<gid>" \
  --store 店3
```

Important options:

| Option | Description |
|--------|-------------|
| `--start-time <time>` | Start comment time. Defaults to the day before yesterday `00:00:00`. Passed to `--sinceCommentTime`. |
| `--end-time <time>` | End comment time. Defaults to today `23:59:59`. Passed to `--untilCommentTime`. |
| `--limit <n>` | Optional bounded test limit. |
| `--per-page <n>` | Optional feedback page size. |
| `--max-pages <n>` | Optional bounded page count. |
| `--profile <id-or-alias>` | Browser Bridge profile id or alias. |
| `--sheet-url <url>` | Target MaybeAI spreadsheet URL with `gid`. |
| `--store <name>` | Value written to the `店铺` column. Defaults to `店3`. |
| `--log-dir <dir>` | Directory for daily log files. Defaults to `artifacts/shein-feedback/logs`. |
| `--raw-output-dir <dir>` | Directory for per-run raw SHEIN JSON files. Defaults to `artifacts/shein-feedback/raw`. |
| `--request-timeout <seconds>` | Passed to `opencli shein feedback --requestTimeout`. |
| `--attempts <n>` | Whole SHEIN CLI retry attempts. Defaults to `3`. |
| `--preflight-login` / `--no-preflight-login` | Enable or disable the `whoami` preflight. Enabled by default. |

When a date is provided without a time, `--start-time 2026-7-1 --end-time 2026-7-7` becomes:

```text
sinceCommentTime = 2026-07-01 00:00:00
untilCommentTime = 2026-07-07 23:59:59
```

The CLI filter is `commentTime > sinceCommentTime` and `commentTime <= untilCommentTime`.

Raw JSON is saved as:

```text
artifacts/shein-feedback/raw/<店铺>商品评价数据-YYYYMMDD-HHMMSS.json
```

Daily logs are appended to:

```text
artifacts/shein-feedback/logs/YYYY-MM-DD.log
```

Sheet headers:

```text
店铺,评价时间,评论ID,国家站点,SPU,SKC,商品SKU,商品评分,商品评分名称,商品评价内容,商品评价图片,物流评分,物流评价内容,下单时间,订单号,合身标签,差评标签
```

Unique key:

```text
店铺 + 评价时间 + 评论ID
```

### Sync Daily Traffic To Sheet

Script:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<doc-id>?gid=<gid>" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28
```

Important options:

| Option | Description |
|--------|-------------|
| `--start-date <date>` | Start date. Accepts `YYYY-MM-DD` or `YYYYMMDD`. Defaults to yesterday when both dates are omitted. |
| `--end-date <date>` | End date. Accepts `YYYY-MM-DD` or `YYYYMMDD`. Defaults to `start-date` when omitted. |
| `--last-days <n>` | Run the latest `n` days ending at `--end-date`, or yesterday when `--end-date` is omitted. Cannot be combined with `--start-date`. |
| `--store <name>` | Value written to ETL `店铺` and raw `store_name`. Defaults to `店3`. |
| `--profile <id-or-alias>` | Browser Bridge profile id or alias. Use one dedicated OpenCLI/Chrome profile per store. |
| `--store-config <path>` | JSON config for sequential multi-store production runs. The repo includes `scripts/shein-daily-traffic-prod.json`. |
| `--store-key <key>` | Run only matching config keys, ids, or store names. Can be passed multiple times. |
| `--sheet-url <url>` | Target MaybeAI spreadsheet URL with `gid`. |
| `--sheet-display-days <n>` | Keep only the most recent `n` days visible in the ETL worksheet after merge/write. Raw DB saves still use the requested date range. |
| `--area-cd <code>` | Forwarded to `opencli shein daily-traffic --areaCd`. |
| `--country-site <value>` | Forwarded to `opencli shein daily-traffic --countrySite`. |
| `--page-size <n>` | Forwarded to `opencli shein daily-traffic --pageSize`. |
| `--limit <n>` | Optional bounded test limit per fetched day. |
| `--max-pages <n>` | Optional bounded page count per fetched day. |
| `--skip-existing-days` / `--no-skip-existing-days` | Default true. A day is skipped only when the raw DB worksheet already has a snapshot for that `data_date`; target ETL Sheet rows do not decide whether to crawl. |
| `--clear-worksheet-data` | Discard existing data rows before writing fetched rows, while preserving headers. Off by default. |
| `--ensure-headers` | Rewrite the header row before writing. Off by default. |
| `--dry-run` | Fetch with OpenCLI, run ETL, print summary/sample, and skip MaybeAI writes. |
| `--log-dir <dir>` | Directory for daily log files. Defaults to `artifacts/shein-daily-traffic/logs`. |
| `--request-timeout <seconds>` | Passed to `opencli shein daily-traffic --requestTimeout`. |
| `--attempts <n>` | Whole SHEIN CLI retry attempts. Defaults to `3`. |
| `--preflight-login` / `--no-preflight-login` | Enable or disable the `whoami` preflight. Enabled by default. |

Daily logs are appended to:

```text
artifacts/shein-daily-traffic/logs/YYYY-MM-DD.log
```

For production, keep the same profile convention as the aftersales and feedback jobs: create stable OpenCLI aliases such as `profile1`, `profile2`, and `profile3`, with one logged-in Chrome/Browser Bridge profile per store. Then run one scheduled command with a store config:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --store-config scripts/shein-daily-traffic-prod.json \
  --last-days 30 \
  --raw-db \
  --ensure-headers \
  --request-timeout 120 \
  --cli-timeout 3600
```

The config shape is:

```json
{
  "defaults": {
    "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/6a6a2c370e55e966f026e1d8",
    "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/6a6a2c410e55e966f026e1e5",
    "worksheet_name": "每日流量ETL",
    "sheet_display_days": 30
  },
  "stores": [
    {"key": "store1", "store": "店1", "profile": "jegkb2wv", "raw_db_worksheet_name": "店1每日流量"},
    {"key": "store2", "store": "店2", "profile": "m3cjm28a", "raw_db_worksheet_name": "店2每日流量"},
    {"key": "store3", "store": "店3", "profile": "w2db43wa", "raw_db_worksheet_name": "店3每日流量"}
  ]
}
```

ETL sheet headers:

```text
站点,店铺,日期,商品编号,商品,商品当前状态,规格编号,规格名称,规格当前状态,商品货号,主商品货号,商品访客（访问）,商品页面访客,跳出商品页面的访客数,商品跳出率,搜索点击数,赞,商品访客（添加至购物车）,件数 (加入购物车）,转化率 (加入购物车率),买家数（已下单）,件数（已下单）,销售额（已下单）,转化率（已下单）,买家数（已确认订单）,件数（已确认订单）,一级分类,二级分类,三级分类,四级分类
```

Raw-only fields such as image URL, supplier SKU, click rate, rating counts, campaign metadata, query dates, and JSON payloads are retained in the raw DB worksheet and are not written to the final ETL sheet.

Unique key:

```text
店铺 + 日期 + 商品货号 + 主商品货号 + 供应商SKU
```

Skip key:

```text
店铺 + 日期
```

Daily traffic Sheet output intentionally omits `每日流量明细JSON`, `活动信息JSON`, `权益活动JSON`, and `原始JSON`. Raw source data can be saved with `--raw-db`; by default the staging workbook is `https://www.maybe.ai/docs/spreadsheets/d/6a69d73b0e55e966f026dee3?gid=0` and the staging worksheet is `<store>每日流量`, for example `店3每日流量`. Later ETL can read a date range with `--etl-source raw-api --raw-db-read-path <path>`.

Existing ETL worksheet reads first call `/api/v1/excel_v2/worksheet/dimensions` to get the used row count, then read row ranges instead of using an unbounded full-sheet read. The default chunks are `A1:AD10001`, then `A10002:AD20001`, capped at the dimensions row count. Write verification reads back the expected one-row range, such as `A4:AD4`; it does not use MaybeAI `filter_tokens` because Base-only `read_sheet` does not support them.

Daily traffic sync logs include stage and progress markers for production monitoring. In a multi-store run, the script prints the configured store index, store/profile, raw-DB-based date plan, per-day fetch progress, per-day raw DB save progress, ETL/write stages, and a final store completion summary.

## Troubleshooting

- If `opencli profile list` says the daemon is not running, open Chrome with the Browser Bridge extension enabled and retry.
- If a Chrome profile such as `Profile 1` is needed, enable Browser Bridge in that Chrome profile first, then rename the connected OpenCLI profile id with `opencli profile rename`.
- If `whoami` fails after `login` succeeds, the SSO login completed but the GSP subsystem session is not ready. Retry `opencli shein login` and keep the GSP aftersales page open.
- If a list capture times out, raise `--requestTimeout`, rerun after `opencli shein login`, or reduce scope with `--limit` / `--maxPages` while debugging. Daily traffic uses the merchandise details page and `/sbn/new_goods/get_skc_diagnose_list`.
- Avoid running multiple SHEIN browser commands in parallel against the same Browser Bridge profile.
