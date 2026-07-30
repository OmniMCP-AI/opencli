# SHEIN Daily Traffic OpenCLI Design

## Purpose

This design turns the SHEIN daily traffic migration spec into an implementation shape for opencli. The delivery is limited to opencli and repo-local scripts:

- add `opencli shein daily-traffic`;
- add `scripts/sync-shein-daily-traffic-to-sheet.py`;
- document and benchmark the flow.

play-be is not changed in this work. The new command and script must be enough for an external scheduler to fetch one store/day or a date range and write the MaybeAI Sheet.

## Source Boundaries

SHEIN raw data is retained outside MaybeAI Sheet. This flow does not use MaybeAI Sheet as a raw archive.

- OpenCLI adapter: source-shaped scalar output plus raw per-row payload fields for DB storage.
- Python script: optional daily raw worksheet save-to-MongoDB call, optional raw API read-back, then ETL into business sheet columns.
- MaybeAI Sheet: current business-facing projection only.
- DB raw records: audit/replay/future ETL source of truth.

No JSON blob sheet columns are emitted:

- `每日流量明细JSON`
- `活动信息JSON`
- `权益活动JSON`
- `原始JSON`

## Files

Create:

- `clis/shein/daily-traffic.js`
- `clis/shein/daily-traffic.test.js`
- `scripts/sync-shein-daily-traffic-to-sheet.py`
- `scripts/shein-daily-traffic-prod.json`

Modify:

- `docs/adapters/browser/shein.md`

Reference:

- `clis/shein/aftersales.js`
- `clis/shein/feedback.js`
- `scripts/sync-shein-aftersales-to-sheet_v1.py`
- `scripts/sync-shein-feedback-to-sheet.py`
- `docs/specs/2026-07-29-shein-daily-traffic-opencli-design.md`

## Adapter Contract

Command:

```bash
opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --pageSize 100 \
  -f json
```

Adapter metadata:

- `site`: `shein`
- `name`: `daily-traffic`
- `strategy`: `Strategy.COOKIE`
- `browser`: `true`
- `navigateBefore`: `false`
- `defaultWindowMode`: `foreground`
- `defaultFormat`: `json`
- `domain`: `sso.geiwohuo.com`

Arguments:

| Argument | Meaning |
|---|---|
| `startDate` | `YYYY-MM-DD` or `YYYYMMDD`. |
| `endDate` | `YYYY-MM-DD` or `YYYYMMDD`. |
| `areaCd` | Defaults to captured request body value, then `cn`. |
| `countrySite` | String. Comma-split when provided. Captured array/string when omitted. Fallback `['shein-all']`. |
| `pageSize` | Defaults to captured request body value, then `100`. |
| `limit` | Global returned-row limit across the whole date range. |
| `maxPages` | Per-day page cap. |
| `requestTimeout` | Single capture/fetch timeout seconds. Default `60`. |
| `retryAttempts` | Page API retry count. Default `3`. |
| `retryDelayMs` | Retry base delay. Default `1000`. |
| `timeout` | Whole command timeout. Default `3600`. |

Date resolution must match both adapter and script:

| Input | Resolved Range |
|---|---|
| neither start nor end | yesterday to yesterday |
| only start | start to start |
| only end | end to end |
| start later than end | swap |

The adapter expands the range into one request per calendar day.

## Adapter Flow

1. Navigate to `https://sso.geiwohuo.com/#/sbn/merchandise/details`.
2. Wait for the SHEIN app shell and verify `location.href` is under `https://sso.geiwohuo.com`.
3. Install a temporary fetch/XHR capture harness for `/sbn/new_goods/get_skc_diagnose_list`.
4. Click visible `搜索`. If the button is unavailable or no capture arrives, reload the route and wait for the same endpoint.
5. Extract the first successful endpoint capture:
   - request body JSON;
   - sanitized replay headers;
   - response JSON with `code === 0`.
6. Build daily request bodies from captured body plus CLI overrides.
7. Fetch page 1 through `page.fetchJson`.
8. Continue pages until page cap, total count, short page, empty page, or global `limit`.
9. Flatten every raw item into scalar output fields.

## Capture And Replay

Endpoint candidate:

```text
POST /sbn/new_goods/get_skc_diagnose_list
```

The first implementation must validate this against a live SHEIN profile before treating it as stable.

Replay header strategy:

- preserve captured business headers, including SHEIN risk-control or device headers;
- drop browser-managed or sensitive headers: `accept-encoding`, `connection`, `content-length`, `cookie`, `host`, `origin`, `referer`, and `sec-*`.

Do not replay cookies or browser-managed transport headers manually. `page.fetchJson` runs inside the authenticated page session. Live E2E on 2026-07-29 showed `/sbn/new_goods/get_skc_diagnose_list` returns `HTTP 403` when the replay header set is reduced to a narrow allowlist, so the adapter uses a blocklist for unsafe headers instead.

Request body construction:

```js
{
  ...capturedBody,
  areaCd,
  countrySite,
  dt: dailyYYYYMMDD,
  startDate: dailyYYYYMMDD,
  endDate: dailyYYYYMMDD,
  pageNum,
  pageSize
}
```

`countrySite` handling:

- CLI value `shein-jp,shein-us` becomes `['shein-jp', 'shein-us']`.
- Captured array is preserved when CLI value is absent.
- Captured string is wrapped as a one-element array when CLI value is absent.
- Empty values fall back to `['shein-all']`.

## Adapter Columns

Output columns, in order:

```text
date, queried_start_date, queried_end_date, total_count, page_num, request_url,
goods_name, img_url, spu, skc, sku_supplier_no, new_goods_tag, layer_name,
onsale_flag, sale_flag, multicolor_flag, goods_uv_idx, eps_uv_idx,
bounce_uv_idx, bounce_rate, search_click_cnt, like_cnt, cart_uv_idx,
cart_pv_idx, gds_cart_ctr_idx, pay_uv_idx, pay_order_cnt, gmv,
gds_pay_ctr_idx, sale_uv_idx, sale_cnt, sale_gmv, gds_sale_ctr_idx,
confirm_ctr_idx, total_quality_level, total_comment_cnt, bad_comment_cnt, bad_comment_rate,
return_order_cnt, return_qty, new_cate_1_name, new_cate_2_name,
new_cate_3_name, new_cate_4_name, brand, list_name, list_type, list_rank,
prom_tag, prom_names, prom_ids, prom_inf_ing_json, right_campaign_json,
raw_json
```

`prom_inf_ing_json`, `right_campaign_json`, and `raw_json` let the script save raw crawler records to DB. These fields are never written to the business Sheet.

Field rules:

| Output | Source |
|---|---|
| `date` | requested daily date as `YYYY-MM-DD` |
| `queried_start_date` | requested daily date as `YYYYMMDD` |
| `queried_end_date` | requested daily date as `YYYYMMDD` |
| `total_count` | `payload.info.meta.count`, fallback current page rows |
| `page_num` | current request page number |
| `request_url` | captured/fetched endpoint path or URL |
| `goods_name` | `goodsName` |
| `img_url` | `imgUrl` or `imageUrl` |
| `spu` | `spu` |
| `skc` | `skc` |
| `sku_supplier_no` | `skuSupplierNo` |
| `new_goods_tag` | `newGoodsTag` |
| `layer_name` | `layerNm` |
| `onsale_flag` | `onsaleFlag` |
| `sale_flag` | `saleFlag` |
| `multicolor_flag` | `multicolorFlag` |
| `goods_uv_idx` | `goodsUvIdx` |
| `eps_uv_idx` | `epsUvIdx` |
| `bounce_uv_idx` | `bounceUvIdx` |
| `bounce_rate` | `bounceRate` |
| `search_click_cnt` | `searchClickCnt` |
| `like_cnt` | `likeCnt` |
| `cart_uv_idx` | `cartUvIdx` |
| `cart_pv_idx` | `cartPvIdx` |
| `gds_cart_ctr_idx` | `gdsCartCtrIdx` |
| `pay_uv_idx` | `payUvIdx` |
| `pay_order_cnt` | `payOrderCnt` |
| `gmv` | `gmv` |
| `gds_pay_ctr_idx` | `gdsPayCtrIdx` |
| `sale_uv_idx` | `saleUvIdx` |
| `sale_cnt` | `saleCnt` |
| `sale_gmv` | `saleGmv` |
| `gds_sale_ctr_idx` | `gdsSaleCtrIdx` |
| `confirm_ctr_idx` | `confirmCtrIdx` |
| `total_quality_level` | `totalQualityLevel` |
| `total_comment_cnt` | `totalCommentCnt` |
| `bad_comment_cnt` | `payBadCommentCnt` / derived from `totalCommentCnt * badCommentRate` |
| `bad_comment_rate` | `badCommentRate` |
| `return_order_cnt` | `returnOrderCnt` |
| `return_qty` | `returnQty` |
| `new_cate_1_name` | `newCate1Nm` |
| `new_cate_2_name` | `newCate2Nm` |
| `new_cate_3_name` | `newCate3Nm` |
| `new_cate_4_name` | `newCate4Nm` |
| `brand` | `brand` |
| `list_name` | `listName` |
| `list_type` | `listType` |
| `list_rank` | `listRank` |
| `prom_tag` | `promCampaign.promTag` |
| `prom_names` | `promCampaign.promInfIng[].promNm`, joined with ` | ` |
| `prom_ids` | `promCampaign.promInfIng[].promId`, joined with ` | ` |

Missing scalar values should normalize to empty string unless the field is a count where existing play-be behavior expects `0` during sheet ETL.

## Script Contract

Single-store command:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28
```

Production multi-store command:

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --store-config scripts/shein-daily-traffic-prod.json \
  --last-days 30 \
  --raw-db \
  --ensure-headers \
  --request-timeout 120 \
  --cli-timeout 3600
```

The core sync still processes one store/profile pair at a time. `--store-config` runs those store configs sequentially in one process, using one dedicated Browser Bridge profile per store.

Environment:

- `MAYBEAI_API_TOKEN`, `MAYBEAI_AUTH_TOKEN`, or `MAYBEAI_API_KEY`;
- optional `SHEIN_USERNAME`/`SHEIN_USER`;
- optional `SHEIN_PASSWORD`/`SHEIN_PASS`.

Script phases:

1. load env files;
2. normalize date range;
3. set up daily logging;
4. build MaybeAI client and sheet target;
5. read existing target ETL sheet rows for merge/write only;
6. read raw DB worksheet snapshots and compute missing days by raw snapshot `data_date`;
7. preflight SHEIN session with `opencli shein whoami`;
8. login and retry when auth/session failures are detected;
9. call `opencli shein daily-traffic -f json` only for missing days;
10. when `--raw-db` is set, write each successfully fetched day into a raw worksheet and call `excel__save_table_worksheet_to_mongodb` immediately before fetching the next day;
11. when `--etl-source raw-api` is set, read the configured raw API for the 30-day window ending at the requested end date;
12. ETL source rows to sheet records;
13. merge by unique key;
14. sort by date desc, then SKC asc;
15. optionally keep only the `--sheet-display-days` most recent days in the ETL Sheet;
16. write with `update_data_keep_headers`;
17. read back each fetched `店铺 + 日期` by its written one-row range and verify visible days.

`--dry-run` runs through fetch and ETL, then prints a summary/sample and skips MaybeAI write.

Date controls:

- `--start-date` / `--end-date` accept `YYYY-MM-DD` or `YYYYMMDD`.
- With neither date, the script runs yesterday only.
- With only one explicit date, the script runs that one date.
- With `--last-days N`, the script runs the latest `N` days ending at `--end-date`, or yesterday when `--end-date` is omitted. `--last-days` cannot be combined with `--start-date`.
- `--sheet-display-days N` controls how many recent days remain visible in the final ETL worksheet after merge/write, ending at the latest date present in merged ETL records; it does not reduce which requested days are crawled or saved to raw DB.
- `--skip-existing-days` uses raw DB snapshots, not target ETL Sheet rows. If raw DB has a snapshot for a store/day, the crawler is skipped for that day; if the ETL Sheet has rows but raw DB has no snapshot, the day is crawled and saved to raw DB.

Store config:

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

Raw DB options:

- `--raw-db`: enable daily raw worksheet-to-MongoDB saves. Default off to avoid accidental prod writes.
- `--raw-db-save-path`: default `/api/v1/tool/function_call`.
- `--raw-db-uri`: spreadsheet URI used as the raw worksheet staging table; defaults to `https://www.maybe.ai/docs/spreadsheets/d/6a69d73b0e55e966f026dee3?gid=0`.
- `--raw-db-worksheet-name`: explicit raw worksheet name; defaults to `<store><raw-db-worksheet-suffix>`.
- `--raw-db-worksheet-suffix`: default `每日流量`, matching the staging worksheet convention such as `店3每日流量`.
- `--raw-db-type`: default `shein_daily_traffic`, used when querying the later raw API.
- `--etl-source fresh|raw-api`: default `fresh`; `raw-api` reads raw rows back before ETL.
- `--raw-db-read-path`: required by `--etl-source raw-api`; this repo does not assume a concrete read endpoint.
- `--raw-read-days`: default `30`; read window ends at `--end-date`.
- `--skip-sheet-write`: skip final ETL Sheet merge/write after fetch/ETL summary. With `--etl-source fresh --raw-db`, this is the crawl-only mode: each missing day is crawled and saved to raw DB, but the business Sheet is not touched.

MongoDB save tool payload:

```json
{
  "app": "function_call",
  "tool_id": "excel__save_table_worksheet_to_mongodb",
  "tool_name": "save_table_worksheet_to_mongodb",
  "tool_args": {
    "data_date": "YYYY-MM-DD",
    "uri": "<raw-db-uri>",
    "worksheet_name": "<store>每日流量"
  }
}
```

The raw save is called once per successfully crawled store/day, immediately after that day's CLI fetch succeeds. The logged `raw_key` is:

```text
shein_daily_traffic:<store>:<profile>:<YYYY-MM-DD>
```

The MongoDB uniqueness boundary is the save tool input: raw workbook document, worksheet name, and `data_date`. With the prod config above that means each store/day lands in its own raw worksheet/date snapshot, while all stores share the final ETL worksheet.

## Sheet ETL

Target headers match the legacy SHEIN daily traffic worksheet at `https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=41`. Raw source data, including detailed scalar fields and JSON payloads, is stored in the raw DB worksheet and can be read back for future re-ETL.

```text
站点,店铺,日期,商品编号,商品,商品当前状态,规格编号,规格名称,
规格当前状态,商品货号,主商品货号,商品访客（访问）,商品页面访客,
跳出商品页面的访客数,商品跳出率,搜索点击数,赞,
商品访客（添加至购物车）,件数 (加入购物车）,转化率 (加入购物车率),
买家数（已下单）,件数（已下单）,销售额（已下单）,转化率（已下单）,
买家数（已确认订单）,件数（已确认订单）,一级分类,二级分类,三级分类,四级分类
```

Derived fields:

| Sheet Field | Rule |
|---|---|
| `站点` | constant `SHEIN` |
| `店铺` | script `--store` |
| `日期` | adapter `date` |
| `商品当前状态` | map `sale_flag`: `1 -> 在售`, `0 -> 非在售`, otherwise preserve source text such as `下架` |
| `件数（已下单）` | `pay_order_cnt`, blank source becomes `0` |
| `件数（已确认订单）` | `sale_cnt`, blank source becomes `0` |

All other final ETL sheet fields map directly from adapter output. Query dates, image URL, supplier SKU, status flags, click rate, rating counts, return metrics, campaign metadata, `store_name`, and JSON payloads stay in the raw DB worksheet for future re-ETL.

Unique key:

```text
店铺 + 日期 + 商品货号 + 主商品货号 + 供应商SKU
```

Skip key:

```text
店铺 + 日期
```

## Error Handling

Adapter:

- malformed date: `CommandExecutionError`;
- capture timeout: `CommandExecutionError` with endpoint and current URL;
- SHEIN API non-zero code: `CommandExecutionError` with code/message;
- repeated page fetch failure: `CommandExecutionError` with page number and last error;
- logged-out/auth page: fail typed enough for script `looks_auth_required` to match.

Script:

- missing MaybeAI token: fail before OpenCLI fetch;
- invalid sheet URL: fail before OpenCLI fetch;
- `whoami` auth failure: run login, wait, verify again;
- retryable CLI failure: retry whole OpenCLI command;
- non-retryable CLI failure: fail immediately;
- MaybeAI 429/5xx/network: retry with configured backoff;
- write verification failure: exit `1`.

Write verification:

- Only fetched days with at least one ETL row are verified. A source day with zero SHEIN rows is written/saved as raw data when requested, but it is not required to appear in the ETL Sheet.
- Crawl skip decisions come from raw DB snapshots. Target ETL Sheet reads are for merge/write preservation only.
- Full ETL Sheet reads first call `/api/v1/excel_v2/worksheet/dimensions` for the used row count, then read row ranges in chunks of 10,000 data rows: `A1:AD10001`, then `A10002:AD20001`, capped at the dimensions row count. This is used before skip/merge so old dates are not missed in 30-day multi-store worksheets, without probing empty ranges.
- Verification reads back the expected written row with a one-row range such as `A4:AD4`. It does not use MaybeAI `filter_tokens`, because Base-only `read_sheet` currently returns `unsupported_filter_read`.
- These range reads avoid false failures when an unbounded `read_sheet` returns only a capped date-desc slice.

## Test Design

Adapter unit tests expose helpers through `__test__`:

- date normalization;
- date range expansion;
- `countrySite` normalization;
- header sanitization;
- successful capture extraction;
- API payload validation;
- daily body construction;
- flattening;
- campaign name/id joining;
- pagination stop logic.

Script tests should be network-free. Use stdlib `unittest` or a `--self-test` mode if there is no Python test runner:

- date normalization;
- sheet mapping;
- status flag mapping;
- ratio calculation;
- existing-day skip detection;
- unique-key merge;
- sort order;
- dry-run summary shape.

## Documentation Updates

`docs/adapters/browser/shein.md` should add:

- command table entry for `opencli shein daily-traffic`;
- daily traffic usage examples;
- option table;
- output columns;
- sync script usage;
- one-store-one-profile note;
- no JSON sheet fields note;
- troubleshooting for capture timeout and profile/session issues.

## Rollout

1. Implement adapter helpers and unit tests.
2. Implement live adapter flow.
3. Verify with a bounded live run: one store, one day, `--limit 5`.
4. Implement script ETL helpers and self-test/unit tests.
5. Verify script dry run for one store/day.
6. Verify script write to a test worksheet.
7. Document command and script.
8. Run benchmark checklist before considering the work done.

## Non-Goals

- No play-be code change.
- No concurrent multi-store orchestration inside the script. `--store-config` is sequential by design.
- No JSON blob fields in MaybeAI Sheet.
- No local raw JSON archive.
- No default prod DB write; raw DB write is opt-in with `--raw-db`.
