# SHEIN Daily Traffic OpenCLI Migration Design

## Goal

把 play-be `POST /api/v1/excel/shein_daily_traffic_analysis_data` 里依赖的外部 Browser Scraper task 迁移到 opencli 的 `shein` adapter 中，并新增一个和现有 SHEIN 售后/评价同步脚本风格一致的业务脚本，把日流量分析数据写入 MaybeAI Sheet。本轮不修改 play-be；opencli 命令和业务脚本本身要能独立完成抓取、ETL、写表。

## Context

现有 opencli SHEIN 代码已经有三类可复用经验：

- `clis/shein/aftersales.js`：在真实 SHEIN GSP 页面内捕获首个接口请求，提取可复放 headers/body，再用 `page.fetchJson` 分页和补详情。
- `clis/shein/feedback.js`：在 SHEIN 页面点击搜索或 reload 捕获列表请求，把时间范围注入请求体后复放分页。
- `scripts/sync-shein-aftersales-to-sheet_v1.py` 与 `scripts/sync-shein-feedback-to-sheet.py`：负责 `whoami`/`login` 预检、OpenCLI 子进程重试、读表、按业务唯一键 merge、`update_data_keep_headers` 写入。

play-be 当前接口的关键行为来自 `/Users/duke/projects/maybeai-uni/fastestai-playground/src/fastestai_playground/excel/router/api.py`：

- 路由：`POST /api/v1/excel/shein_daily_traffic_analysis_data`
- 外部 task 名：`extractDailyProductAnalyticsFromShein`
- 默认 SHEIN 页面：`https://sso.geiwohuo.com/#/sbn/merchandise/details`
- 默认目标表：`https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0`
- 默认店铺名：`普通店铺`
- 日期规则：未传日期时默认昨天；只传 `start_date` 或 `end_date` 时另一个取同一天；`start_date > end_date` 时交换顺序；内部按天展开，逐日调用爬虫。
- 写表规则：默认不清表；是否需要重新爬取由 raw DB snapshot 决定，不由目标 ETL Sheet 决定。raw DB 已存在某个店铺日期的原始快照时跳过爬虫；目标 ETL Sheet 只用于 merge/write 时保留其他已有行。写完后读表校验目标日期可见。
- 店铺/profile 规则：一个店铺绑定一个 Chrome Browser Bridge profile。脚本既支持一次只处理一个 `--store` + `--profile` 组合，也支持通过 `--store-config` 在同一次业务脚本运行里顺序处理多个店铺。每个店铺仍必须使用独立 profile，不能共享同一个已登录 Chrome profile。
- 数据边界：SHEIN 原始数据已经由 DB 保存；业务脚本只负责从 OpenCLI/原始数据结果做 ETL 并写 MaybeAI Sheet，不再往 Sheet 或本地文件里冗余写 JSON 字段。

另外，旧项目 `/Users/duke/projects/opencli 2/src/clis/custom/listSKCsFromSHEIN.ts` 给出了隐藏 task 的可疑核心 endpoint：

- 捕获路径：`/sbn/new_goods/get_skc_diagnose_list`
- 请求 body 关键字段：`areaCd`, `dt`, `countrySite`, `startDate`, `endDate`, `pageNum`, `pageSize`
- 返回数据位置：`payload.info.data`
- 总数位置：`payload.info.meta.count`

该 endpoint 已在当前 opencli 环境中用真实 SHEIN session 验证；live run 能通过 `/sbn/new_goods/get_skc_diagnose_list` 分页返回 400+ 行/日。注意 2026-07-29 曾返回 0 行，这应按 SHEIN 源站数据为空处理，不能在写后验证里要求该天一定有 ETL 行。

## Recommended Approach

推荐做成两个独立交付单元：

1. 新增 `opencli shein daily-traffic` browser adapter，只负责从 SHEIN 页面抓取日流量分析行并输出 JSON。
2. 新增 `scripts/sync-shein-daily-traffic-to-sheet.py`，只负责登录预检、调用 OpenCLI、ETL、读写 MaybeAI Sheet、跳过已存在日期、merge 和日志。

这个拆分和现有 `aftersales`/`feedback` 保持一致：浏览器鉴权、接口捕获、分页抓取留在 JS adapter；业务表头、店铺名、增量策略、MaybeAI API 留在 Python 脚本。本轮交付完成后，外部调度可以直接跑脚本；play-be 迁移只作为后续可选工作，不进入本轮实现范围。

## Alternatives Considered

### Option A: 只写 Python 脚本直接调 SHEIN 接口

不推荐。Python 拿不到 Browser Bridge 的页面会话和 SHEIN 前端动态 headers，最后会重新发明 `aftersales.js` 已经解决过的捕获与复放逻辑。

### Option B: 在 opencli adapter 里同时写 MaybeAI Sheet

不推荐。opencli adapter 应保持“从网站读数据”的边界，写 Sheet 会把 MaybeAI token、目标表合并规则、日志归档混进 JS adapter，不利于测试和复用。

### Option C: adapter 输出 raw 行，Python 脚本做中文表头归一化

推荐。它最贴近现有 SHEIN 同步脚本，也保留 play-be 的字段归一化能力。adapter 输出稳定的 snake_case 原始业务字段；脚本映射成中文表头。

## OpenCLI Adapter Design

### File

- Create: `clis/shein/daily-traffic.js`
- Create: `clis/shein/daily-traffic.test.js`
- Modify: `docs/adapters/browser/shein.md`

### Command

```bash
opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --pageSize 100 \
  -f json
```

### CLI Arguments

- `--startDate <date>`: `YYYY-MM-DD` or `YYYYMMDD`.
- `--endDate <date>`: `YYYY-MM-DD` or `YYYYMMDD`.
- Date resolution:
  - neither `--startDate` nor `--endDate`: use yesterday for both.
  - only `--startDate`: use it for both start and end.
  - only `--endDate`: use it for both start and end.
  - start later than end: swap them.
- `--areaCd <code>`: defaults to captured body value, then `cn`.
- `--countrySite <value>`: string argument. If provided, split by comma, trim blank values, and send an array. If omitted, keep captured body `countrySite` when it is a non-empty array/string; otherwise send `['shein-all']`.
- `--pageSize <n>`: defaults to captured body value, then `100`.
- `--limit <n>`: max returned rows across all requested days.
- `--maxPages <n>`: page cap per day for bounded tests.
- `--requestTimeout <seconds>`: single page-side capture/fetch timeout, default `60`.
- `--retryAttempts <n>`: page API retry count, default `3`.
- `--retryDelayMs <n>`: retry base delay, default `1000`.
- `--timeout <seconds>`: whole OpenCLI command timeout, default `3600`.

### Browser Flow

1. Open `https://sso.geiwohuo.com/#/sbn/merchandise/details`.
2. Verify the current URL remains under `https://sso.geiwohuo.com`; otherwise raise `CommandExecutionError` with current URL.
3. Install a fetch/XHR capture harness matching `/sbn/new_goods/get_skc_diagnose_list`.
4. Click the visible `搜索` button; if unavailable, reload the same page and wait for the endpoint.
5. Extract first successful capture:
   - `requestHeaders`, sanitized by blocklist. Preserve captured SHEIN business/risk-control headers, but do not replay `cookie`, `host`, `content-length`, `accept-encoding`, `connection`, `sec-*`, `origin`, or `referer`.
   - `requestBodyPreview`, parsed as JSON.
   - `responsePreview`, parsed and validated with `code === 0`.
6. For each requested date, build daily request body from the captured body:
   - Preserve page filters from the captured body.
   - Override `dt`, `startDate`, and `endDate` to the daily `YYYYMMDD`.
   - Override `areaCd`, `countrySite`, `pageNum`, and `pageSize` from CLI args when provided.
7. Fetch page 1 through `page.fetchJson`, then paginate one day at a time until one of:
   - `pageNum > maxPages`
   - global returned row count reaches `limit`
   - `info.data` is empty
   - current page has fewer rows than page size
   - `pageNum >= ceil(info.meta.count / pageSize)`, where `info.meta.count` is the raw SHEIN total count for that day's request.
8. Return flattened rows.

### Adapter Output Columns

The adapter should output stable snake_case fields that are close to the legacy task payload:

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
prom_tag, prom_names, prom_ids
```

Mapping examples from SHEIN raw payload:

- requested daily date -> `date`, formatted as `YYYY-MM-DD`
- requested daily date -> `queried_start_date` and `queried_end_date`, formatted as `YYYYMMDD`
- `goodsUvIdx -> goods_uv_idx`
- `epsUvIdx -> eps_uv_idx`
- `bounceUvIdx -> bounce_uv_idx`
- `gdsCartCtrIdx -> gds_cart_ctr_idx`
- `payUvIdx -> pay_uv_idx`
- `payOrderCnt -> pay_order_cnt`
- `gdsPayCtrIdx -> gds_pay_ctr_idx`
- `saleUvIdx -> sale_uv_idx`
- `saleGmv -> sale_gmv`
- `gdsSaleCtrIdx -> gds_sale_ctr_idx`
- `confirmCtrIdx -> confirm_ctr_idx`
- `newCate1Nm -> new_cate_1_name`
- `layerNm -> layer_name`
- `promCampaign.promInfIng[].promNm -> prom_names`, joined by ` | `
- `promCampaign.promInfIng[].promId -> prom_ids`, joined by ` | `
- Include raw payload fields `raw_json`, `prom_inf_ing_json`, and `right_campaign_json` in the adapter JSON output so the business script can persist raw crawler data. These fields must not be written to the business Sheet.

## Business Script Design

### File

- Create: `scripts/sync-shein-daily-traffic-to-sheet.py`

### Usage

```bash
python3 scripts/sync-shein-daily-traffic-to-sheet.py \
  --profile profile1 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0" \
  --store 店3 \
  --start-date 2026-07-28 \
  --end-date 2026-07-28
```

### Environment

- `MAYBEAI_API_TOKEN`, `MAYBEAI_AUTH_TOKEN`, or `MAYBEAI_API_KEY` for MaybeAI API.
- `SHEIN_USERNAME` / `SHEIN_USER` and `SHEIN_PASSWORD` / `SHEIN_PASS` for optional automatic login.
- No credentials or bearer tokens should be committed into repo scripts.

### Script Arguments

- `--start-date`: accepts `YYYY-MM-DD` or `YYYYMMDD`.
- `--end-date`: accepts `YYYY-MM-DD` or `YYYYMMDD`.
- `--crawl-last-days <n>`: crawl/check the latest `n` days ending at `--end-date`, or yesterday when `--end-date` is omitted. Cannot be combined with `--start-date`.
- `--last-days <n>`: legacy alias for `--crawl-last-days`; prefer `--crawl-last-days` in new commands.
- Date resolution:
  - neither `--start-date` nor `--end-date`: use yesterday for both.
  - only `--start-date`: use it for both start and end.
  - only `--end-date`: use it for both start and end.
  - start later than end: swap them.
- `--store`: value written to `店铺`, default `店3`.
- `--sheet-url`: target MaybeAI spreadsheet URL with `gid`.
- `--worksheet-name`: optional worksheet override.
- `--read-range`: optional existing sheet range.
- `--profile`: OpenCLI Browser Bridge profile. One store should use one dedicated Chrome/OpenCLI profile; the script must not switch store inside a profile during a run.
- `--opencli-cmd`: default `npm exec -- opencli`.
- `--area-cd`, `--country-site`, `--page-size`, `--limit`, `--max-pages`: forwarded to `opencli shein daily-traffic`.
- `--request-timeout`, `--api-retry-attempts`, `--api-retry-delay-ms`, `--opencli-timeout`: forwarded to OpenCLI.
- `--attempts`, `--retry-delay-seconds`, `--login-on-retry`, `--cli-timeout`, `--login-timeout`, `--login-wait-seconds`, `--preflight-login`: same behavior as existing SHEIN scripts.
- `--skip-existing-days` / `--no-skip-existing-days`: default true. When enabled, skip OpenCLI crawling only when the configured raw DB worksheet already has a snapshot for that date. Target ETL Sheet rows must not decide crawl skipping.
- `--clear-worksheet-data`: default false; when true, clear data rows while preserving headers before writing fresh rows.
- `--ensure-headers`: rewrite header row before writing.
- `--raw-db`: default false. When true, after each successful daily CLI crawl, immediately write the fetched rows into the raw staging worksheet and call `excel__save_table_worksheet_to_mongodb` before crawling the next day.
- `--raw-db-save-path`: default `/api/v1/tool/function_call`.
- `--raw-db-uri`: spreadsheet URI used by `save_table_worksheet_to_mongodb`; defaults to `https://www.maybe.ai/docs/spreadsheets/d/6a69d73b0e55e966f026dee3?gid=0`.
- `--raw-db-worksheet-name`: explicit raw worksheet name; defaults to `<store><raw-db-worksheet-suffix>`.
- `--raw-db-worksheet-suffix`: default `每日流量`, matching the staging worksheet pattern such as `店3每日流量`.
- `--raw-db-type`: default `shein_daily_traffic`, used by the later raw read API query.
- `--etl-source fresh|raw-api`: default `fresh`. `raw-api` calls `--raw-db-read-path` for the full requested crawl window, crawls and saves any requested days missing from raw DB, then reads the Sheet display window from raw DB for ETL.
- `--raw-db-read-path`: required when `--etl-source raw-api`.
- `--raw-read-days`: overrides the final Sheet ETL raw read window; defaults to `--sheet-display-days` when set, otherwise 30.
- `--sheet-display-days`: optional most-recent-day display window for the ETL Sheet, ending at the latest date present in merged ETL records. This controls how many days remain visible in Sheet after merge/write; raw DB crawl checks and saves still use the full requested date range.
- `--skip-sheet-write`: skip final ETL Sheet merge/write. With `--etl-source fresh --raw-db`, the script still crawls missing requested days and saves each successful day to raw DB, but does not update the business Sheet.
- `--store-config`: JSON config for sequential multi-store runs. Defaults can hold shared ETL/raw workbook URIs, worksheet name, and display window; store entries provide `key`, `store`, `profile`, and raw worksheet name.
- `--store-key`: optional repeatable filter for `--store-config` keys, ids, or store names.
- `--dry-run`: fetch, run ETL, print a summary/sample, and skip MaybeAI write.
- `--env-file`: load one or more env files before reading tokens.
- `--log-dir`: default `artifacts/shein-daily-traffic/logs`.

### Sheet Headers

```text
站点,店铺,日期,商品编号,商品,商品当前状态,规格编号,规格名称,规格当前状态,商品货号,主商品货号,
商品访客（访问）,商品页面访客,跳出商品页面的访客数,商品跳出率,搜索点击数,赞,
商品访客（添加至购物车）,件数 (加入购物车）,转化率 (加入购物车率),
买家数（已下单）,件数（已下单）,销售额（已下单）,转化率（已下单）,
买家数（已确认订单）,件数（已确认订单）,一级分类,二级分类,三级分类,四级分类
```

### Sheet Mapping

- `站点`: constant `SHEIN`
- `店铺`: `--store`
- `日期`: adapter `date`, formatted `YYYY-MM-DD`
- `商品`: `goods_name`
- `商品当前状态`: map `sale_flag` with `1 -> 在售`, `0 -> 非在售`; preserve explicit source text such as `下架` as-is.
- `商品货号`: `skc`
- `主商品货号`: `spu`
- `商品访客（访问）`: `goods_uv_idx`
- `商品页面访客`: `eps_uv_idx`
- `跳出商品页面的访客数`: `bounce_uv_idx`
- `商品跳出率`: `bounce_rate`
- `搜索点击数`: `search_click_cnt`
- `赞`: `like_cnt`
- `商品访客（添加至购物车）`: `cart_uv_idx`
- `件数 (加入购物车）`: `cart_pv_idx`
- `转化率 (加入购物车率)`: `gds_cart_ctr_idx`
- `买家数（已下单）`: `pay_uv_idx`
- `件数（已下单）`: `pay_order_cnt`, default `0` only when source is blank.
- `销售额（已下单）`: `gmv`
- `转化率（已下单）`: `gds_pay_ctr_idx`
- `买家数（已确认订单）`: `sale_uv_idx`
- `件数（已确认订单）`: `sale_cnt`, default `0` only when source is blank.
- Category fields map one-to-one from adapter columns.
- Raw-only fields such as query dates, image URL, supplier SKU, status flags, click rate, rating counts, return metrics, campaign metadata, `store_name`, and JSON payloads stay in the raw DB worksheet.

The final ETL sheet headers must match the legacy SHEIN daily traffic worksheet at `https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=41`. Raw source data lives in the configured raw DB/API path; future re-ETL should read those raw records instead of relying on JSON serialized into MaybeAI Sheet cells.

Production config currently uses one shared ETL worksheet for all stores and separate raw worksheets per store:

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

### Merge And Write Rules

- Read the full worksheet by default, or `--read-range` if provided.
- If `--skip-existing-days` is true, read raw DB worksheet snapshots for the full requested crawl window first and skip OpenCLI fetch only for dates that have a raw DB `data_date` snapshot. Empty raw snapshots still count as existing raw data for that date.
- Target ETL Sheet rows are read for merge/write only; they must not make a date skip crawling.
- Merge fetched rows with existing records by:

```text
店铺 + 日期 + 商品货号 + 主商品货号 + 供应商SKU
```

- Preserve rows for other stores.
- Sort output by `日期` descending, then `商品货号` ascending.
- Write with `/api/v1/excel/update_data_keep_headers`, `preserve_formulas=True`, `skip_recalculation=False`, `start_row=2`.
- When `--clear-worksheet-data` is true, discard existing data rows before writing fresh rows, but still write via `update_data_keep_headers` so headers remain.
- Before reading the full ETL worksheet, call `/api/v1/excel_v2/worksheet/dimensions` to get the used row count. Then read only the needed row ranges. The default chunk is 10,000 data rows: first read `A1:AD10001` with headers, then read `A10002:AD20001`, `A20002:AD30001`, and so on with the fixed ETL headers, capped at the dimensions row count. This avoids MaybeAI's unbounded read cap and avoids probing empty ranges such as `A100002:AD110001`.
- After a successful write, verify only fetched days that produced ETL rows. Verification should compute the written row number from the sorted `display_records` and read back a one-row range such as `A4:AD4`. Do not use MaybeAI `filter_tokens` for this path, because Base-only `read_sheet` currently returns `unsupported_filter_read`.
- If `--sheet-display-days` hides a freshly fetched day outside the display window, that day should be excluded from write visibility verification.

## Raw Data And ETL Boundary

- The OpenCLI adapter returns source-shaped scalar rows plus raw payload fields for raw DB persistence; it does not produce Chinese business headers.
- The Python business script can persist one raw worksheet per day to MongoDB before ETL, then either ETL freshly crawled rows or rows loaded back from the raw API.
- DB raw records are the source of truth for audit/replay and future ETL.
- MaybeAI Sheet output is only the current business-facing projection, not the raw-data archive.

## play-be Migration Contract

This spec does not require any play-be code change. After this lands, a later play-be task can stop calling:

```text
extractDailyProductAnalyticsFromShein
```

and instead use one of these integration modes:

1. Preferred for current architecture: shell out to `python3 scripts/sync-shein-daily-traffic-to-sheet.py` with the request body translated to script args.
2. Lighter future option: shell out to `opencli shein daily-traffic -f json` and keep the play-be write-to-sheet logic.

The first mode removes the Browser Scraper MCP dependency and also moves the existing daily skip/write verification behavior into a reusable script. That migration should be tracked as a separate play-be story.

## Documentation Updates

Update `docs/adapters/browser/shein.md` with:

- `opencli shein daily-traffic` in the command table.
- Usage examples for one-day and date-range fetches.
- Adapter options and output columns.
- New script usage and required env vars.
- Troubleshooting note: daily traffic uses the merchandise details page and `/sbn/new_goods/get_skc_diagnose_list`; if capture times out, run `opencli shein login`, raise `--requestTimeout`, and avoid parallel SHEIN commands on the same profile.

## Tests

### Adapter Unit Tests

`clis/shein/daily-traffic.test.js` should cover:

- Date normalization: `2026-7-8`, `20260708`, missing end date, reversed date range.
- `date`, `queried_start_date`, and `queried_end_date` are derived from the requested daily date, not from wall-clock time.
- Request body construction preserves captured filters and overrides daily `dt/startDate/endDate/pageNum/pageSize`.
- `countrySite` parsing converts `shein-jp,shein-us` to `['shein-jp', 'shein-us']` and preserves captured arrays when omitted.
- Header sanitization drops `cookie`, `host`, `content-length`, `origin`, `referer`, and `sec-*`.
- Payload validation rejects non-zero `code`.
- Row flattening maps raw SHEIN camelCase fields to snake_case output.
- Campaign flattening joins names/ids without returning nested campaign JSON.
- Pagination stops on empty page, short page, total count, `limit`, and `maxPages`.

Run:

```bash
npm run test:adapter -- clis/shein/daily-traffic.test.js
```

### Script Unit Tests

The script should keep pure helpers for date parsing, sheet mapping, unique-key generation, skip-existing-day detection, merge, and sort. If no Python test runner exists in this repo, add a `--self-test` mode or small stdlib `unittest` block that can run without network access.

Manual verification commands:

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

```bash
opencli --profile profile1 shein daily-traffic \
  --startDate 2026-07-28 \
  --endDate 2026-07-28 \
  --limit 5 \
  -f json
```

### Build Verification

Run:

```bash
npm run test:adapter -- clis/shein/daily-traffic.test.js clis/shein/aftersales.test.js clis/shein/feedback.test.js
npm run build-manifest
```

## Acceptance Criteria

- `opencli shein daily-traffic --startDate <day> --endDate <day> -f json` returns non-empty rows for a logged-in SHEIN profile with valid data.
- The adapter does not require committed credentials and does not replay raw cookies manually.
- Adapter output includes all source scalar columns needed for the retained daily-traffic sheet fields and preserves raw payload fields for DB persistence.
- The target sheet omits all JSON blob columns: `每日流量明细JSON`, `活动信息JSON`, `权益活动JSON`, and `原始JSON`.
- With `--raw-db`, the script writes each fetched day to the raw worksheet and calls `save_table_worksheet_to_mongodb` with `data_date`, `uri`, and `worksheet_name` immediately after that day succeeds.
- With `--etl-source raw-api`, the script calls the configured raw read API for a requested window, crawls/saves missing raw DB days, and ETLs the combined raw and fresh rows.
- DB raw records remain the source for future re-ETL; ETL-transformed Chinese sheet rows are only for MaybeAI Sheet output.
- The sync script can dry-run, print a summary/sample, and skip MaybeAI writes.
- The sync script can run crawl-only with `--raw-db --skip-sheet-write`, saving raw DB snapshots without touching the ETL Sheet.
- The sync script can write one store/day to MaybeAI Sheet using `update_data_keep_headers`.
- Re-running the same store/day with `--skip-existing-days` performs no SHEIN fetch only when raw DB already has that store/day snapshot, and exits successfully.
- Re-running with `--no-skip-existing-days` merges rows by unique key instead of duplicating rows.
- `docs/adapters/browser/shein.md` documents the command and script.
- No hardcoded SHEIN usernames, passwords, bearer tokens, or webhook URLs are introduced.

## Risks And Mitigations

- SHEIN may have changed the endpoint from `/sbn/new_goods/get_skc_diagnose_list`. Mitigation: the adapter's first implementation must capture the live request from the page, and tests should isolate endpoint matching in one helper.
- The worksheet-to-MongoDB save path depends on the existing `excel__save_table_worksheet_to_mongodb` tool. Mitigation: raw DB writes are opt-in; production should keep the staging worksheet isolated per store and read/deduplicate by `data_date` when building ETL windows.
- Existing play-be skipped whole days based on any matching ETL row, but this loses raw DB completeness. Mitigation: this script uses raw DB snapshots as the skip source, while offering `--no-skip-existing-days` for backfills or correction runs.
- SHEIN sessions are fragile. Mitigation: copy the existing SHEIN script preflight login and retry behavior, and document that parallel commands against the same Browser Bridge profile are unsupported.

## Self Review

- Placeholder scan: no placeholder sections remain; unknown endpoint enrichment is recorded as a risk with a concrete verification path.
- Scope check: this spec covers one OpenCLI adapter, one sync script, docs, and tests. It explicitly does not require play-be changes in the same implementation branch.
- Consistency check: date defaults, daily expansion, target page, target sheet, skip-existing-day behavior, and field names match the inspected play-be/opencli code paths.
