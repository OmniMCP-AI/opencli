# SHEIN Daily Traffic OpenCLI Migration Design

## Goal

把 play-be `POST /api/v1/excel/shein_daily_traffic_analysis_data` 里依赖的外部 Browser Scraper task 迁移到 opencli 的 `shein` adapter 中，并新增一个和现有 SHEIN 售后/评价同步脚本风格一致的业务脚本，把日流量分析数据写入 MaybeAI Sheet。

## Context

现有 opencli SHEIN 代码已经有三类可复用经验：

- `clis/shein/aftersales.js`：在真实 SHEIN GSP 页面内捕获首个接口请求，提取可复放 headers/body，再用 `page.fetchJson` 分页和补详情。
- `clis/shein/feedback.js`：在 SHEIN 页面点击搜索或 reload 捕获列表请求，把时间范围注入请求体后复放分页。
- `scripts/sync-shein-aftersales-to-sheet_v1.py` 与 `scripts/sync-shein-feedback-to-sheet.py`：负责 `whoami`/`login` 预检、OpenCLI 子进程重试、保存 raw JSON、读表、按业务唯一键 merge、`update_data_keep_headers` 写入。

play-be 当前接口的关键行为来自 `/Users/duke/projects/maybeai-uni/fastestai-playground/src/fastestai_playground/excel/router/api.py`：

- 路由：`POST /api/v1/excel/shein_daily_traffic_analysis_data`
- 外部 task 名：`extractDailyProductAnalyticsFromShein`
- 默认 SHEIN 页面：`https://sso.geiwohuo.com/#/sbn/merchandise/details`
- 默认目标表：`https://www.maybe.ai/docs/spreadsheets/d/69d8a907505279d17a357c87?gid=0`
- 默认店铺名：`普通店铺`
- 日期规则：未传日期时默认昨天；只传 `start_date` 或 `end_date` 时另一个取同一天；`start_date > end_date` 时交换顺序；内部按天展开，逐日调用爬虫。
- 写表规则：默认不清表；先读目标表，已存在某个 `店铺 + 日期` 的行则跳过该天；没有数据时抓取并追加；写完后读表校验目标日期可见。

另外，旧项目 `/Users/duke/projects/opencli 2/src/clis/custom/listSKCsFromSHEIN.ts` 给出了隐藏 task 的可疑核心 endpoint：

- 捕获路径：`/sbn/new_goods/get_skc_diagnose_list`
- 请求 body 关键字段：`areaCd`, `dt`, `countrySite`, `startDate`, `endDate`, `pageNum`, `pageSize`
- 返回数据位置：`payload.info.data`
- 总数位置：`payload.info.meta.count`

该 endpoint 仍需在当前 opencli 环境中用真实 SHEIN session 验证一次，验证方式是用 `opencli browser analyze` 或新增 adapter 的首轮 capture 日志确认当前页面仍调用同一路径。

## Recommended Approach

推荐做成两个独立交付单元：

1. 新增 `opencli shein daily-traffic` browser adapter，只负责从 SHEIN 页面抓取日流量分析行并输出 JSON。
2. 新增 `scripts/sync-shein-daily-traffic-to-sheet.py`，只负责登录预检、调用 OpenCLI、保存 raw JSON、读写 MaybeAI Sheet、跳过已存在日期、merge 和日志。

这个拆分和现有 `aftersales`/`feedback` 保持一致：浏览器鉴权、接口捕获、分页抓取留在 JS adapter；业务表头、店铺名、增量策略、MaybeAI API 留在 Python 脚本。play-be 后续可以改成 shell out 到这个脚本，或者外部调度直接跑脚本，从而移除对 `extractDailyProductAnalyticsFromShein` SSE task 的依赖。

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

- `--startDate <date>`: `YYYY-MM-DD` or `YYYYMMDD`; defaults to yesterday.
- `--endDate <date>`: `YYYY-MM-DD` or `YYYYMMDD`; defaults to `startDate`.
- `--areaCd <code>`: defaults to captured body value, then `cn`.
- `--countrySite <value>`: repeatable or comma-separated; defaults to captured body value, then `shein-all`.
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
   - `requestHeaders`, sanitized with the same allowlist style as `aftersales.js`/`feedback.js`; do not replay `cookie`, `host`, `content-length`, `sec-*`, `origin`, or `referer`.
   - `requestBodyPreview`, parsed as JSON.
   - `responsePreview`, parsed and validated with `code === 0`.
6. For each requested date, build daily request body from the captured body:
   - Preserve page filters from the captured body.
   - Override `dt`, `startDate`, and `endDate` to the daily `YYYYMMDD`.
   - Override `areaCd`, `countrySite`, `pageNum`, and `pageSize` from CLI args when provided.
7. Fetch page 1 through `page.fetchJson`, then paginate until one of:
   - `pageNum > maxPages`
   - `rows.length >= limit`
   - `info.data` is empty
   - current page has fewer rows than page size
   - `pageNum >= ceil(info.meta.count / pageSize)`
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
confirm_ctr_idx, total_quality_level, total_comment_cnt, bad_comment_rate,
return_order_cnt, return_qty, new_cate_1_name, new_cate_2_name,
new_cate_3_name, new_cate_4_name, brand, list_name, list_type, list_rank,
prom_tag, prom_names, prom_ids, queried_daily_json, prom_inf_ing_json,
right_campaign_json, raw_json
```

Mapping examples from SHEIN raw payload:

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
- `promCampaign.promInfIng -> prom_inf_ing_json`
- `rightCampaign -> right_campaign_json`
- original item -> `raw_json`

`queried_daily_json` should be an empty string unless a verified SHEIN response field provides per-day nested detail. The business sheet can still be filled correctly because each adapter request is one calendar day.

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

- `--start-date`: default yesterday, accepts `YYYY-MM-DD` or `YYYYMMDD`.
- `--end-date`: default `start-date`, accepts `YYYY-MM-DD` or `YYYYMMDD`.
- `--store`: value written to `店铺`, default `店3`.
- `--sheet-url`: target MaybeAI spreadsheet URL with `gid`.
- `--worksheet-name`: optional worksheet override.
- `--read-range`: optional existing sheet range.
- `--profile`: OpenCLI Browser Bridge profile.
- `--opencli-cmd`: default `npm exec -- opencli`.
- `--area-cd`, `--country-site`, `--page-size`, `--limit`, `--max-pages`: forwarded to `opencli shein daily-traffic`.
- `--request-timeout`, `--api-retry-attempts`, `--api-retry-delay-ms`, `--opencli-timeout`: forwarded to OpenCLI.
- `--attempts`, `--retry-delay-seconds`, `--login-on-retry`, `--cli-timeout`, `--login-timeout`, `--login-wait-seconds`, `--preflight-login`: same behavior as existing SHEIN scripts.
- `--skip-existing-days` / `--no-skip-existing-days`: default true, matching play-be behavior.
- `--clear-worksheet-data`: default false; when true, clear data rows while preserving headers before writing fresh rows.
- `--ensure-headers`: rewrite header row before writing.
- `--dry-run`: fetch and save raw JSON, skip MaybeAI write.
- `--env-file`: load one or more env files before reading tokens.
- `--log-dir`: default `artifacts/shein-daily-traffic/logs`.
- `--raw-output-dir`: default `artifacts/shein-daily-traffic/raw`.

### Sheet Headers

```text
站点,店铺,日期,查询开始日期,查询结束日期,商品编号,商品,商品图片,
商品当前状态,规格编号,规格名称,规格当前状态,商品货号,主商品货号,
供应商SKU,上架状态,是否新品,是否多色,商品访客（访问）,商品页面访客,
点击率,跳出商品页面的访客数,商品跳出率,搜索点击数,赞,
商品访客（添加至购物车）,件数 (加入购物车）,转化率 (加入购物车率),
买家数（已下单）,件数（已下单）,销售额（已下单）,转化率（已下单）,
买家数（已确认订单）,件数（已确认订单）,销售额（已确认订单）,
转化率（已确认订单）,转化率 (将确定),商品质量等级,商品评价数,差评率,
退货订单数,退货件数,一级分类,二级分类,三级分类,四级分类,品牌,
层级名称,榜单名称,榜单类型,榜单排名,活动标签,活动名称,活动ID,
每日流量明细JSON,活动信息JSON,权益活动JSON,请求URL,抓取总数,页码,
原始JSON,store_name,queried_start_date,queried_end_date
```

### Sheet Mapping

- `站点`: constant `SHEIN`
- `店铺`: `--store`
- `日期`: adapter `date`, formatted `YYYY-MM-DD`
- `查询开始日期`: adapter `queried_start_date`, formatted `YYYYMMDD`
- `查询结束日期`: adapter `queried_end_date`, formatted `YYYYMMDD`
- `商品`: `goods_name`
- `商品图片`: `img_url`
- `商品当前状态`: map `sale_flag` with `1 -> 在售`, `0 -> 下架`; preserve other values as-is.
- `商品货号`: `skc`
- `主商品货号`: `spu`
- `供应商SKU`: `sku_supplier_no`
- `上架状态`: map `onsale_flag` with `1 -> 在售`, `0 -> 下架`; preserve other values as-is.
- `是否新品`: map `new_goods_tag` with truthy values to `是`, `0/false/否` to `否`, otherwise preserve.
- `是否多色`: map `multicolor_flag` with `1/true/是 -> 是`, `0/false/否 -> 否`.
- `商品访客（访问）`: `goods_uv_idx`
- `商品页面访客`: `eps_uv_idx`
- `点击率`: calculate `goods_uv_idx / eps_uv_idx` when both are numeric and denominator is non-zero.
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
- `销售额（已确认订单）`: `sale_gmv`
- `转化率（已确认订单）`: `gds_sale_ctr_idx`
- `转化率 (将确定)`: `confirm_ctr_idx`
- Category, brand, layer, rank, campaign fields map one-to-one from adapter columns.
- JSON fields are serialized with `ensure_ascii=False`.
- `store_name`: `--store`
- hidden/raw date columns: adapter `queried_start_date`, `queried_end_date`

### Merge And Write Rules

- Read the full worksheet by default, or `--read-range` if provided.
- If `--skip-existing-days` is true, skip OpenCLI fetch for a date when any existing row matches the same `店铺 + 日期`.
- Merge fetched rows with existing records by:

```text
店铺 + 日期 + 商品货号 + 主商品货号 + 供应商SKU
```

- Preserve rows for other stores.
- Sort output by `日期` descending, then `商品货号` ascending.
- Write with `/api/v1/excel/update_data_keep_headers`, `preserve_formulas=True`, `skip_recalculation=False`, `start_row=2`.
- When `--clear-worksheet-data` is true, discard existing data rows before writing fresh rows, but still write via `update_data_keep_headers` so headers remain.
- After a successful write, read the sheet again and verify each fetched day has at least one `店铺 + 日期` row visible. Treat verification failure as exit code `1`.

## play-be Migration Contract

After this lands, play-be can stop calling:

```text
extractDailyProductAnalyticsFromShein
```

and instead use one of these integration modes:

1. Preferred for current architecture: shell out to `python3 scripts/sync-shein-daily-traffic-to-sheet.py` with the request body translated to script args.
2. Lighter future option: shell out to `opencli shein daily-traffic -f json` and keep the play-be write-to-sheet logic.

The first mode removes the Browser Scraper MCP dependency and also moves the existing daily skip/write verification behavior into a reusable script.

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
- Request body construction preserves captured filters and overrides daily `dt/startDate/endDate/pageNum/pageSize`.
- Header sanitization drops `cookie`, `host`, `content-length`, `origin`, `referer`, and `sec-*`.
- Payload validation rejects non-zero `code`.
- Row flattening maps raw SHEIN camelCase fields to snake_case output.
- Campaign flattening joins names/ids and serializes JSON.
- Pagination stops on empty page, short page, total count, `limit`, and `maxPages`.

Run:

```bash
npm run test:adapter -- clis/shein/daily-traffic.test.js
```

### Script Unit Tests

If the repo does not have Python test infrastructure for scripts, add lightweight tests only if a local pattern exists. Otherwise keep script functions pure enough to test manually with `--dry-run`.

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
- Adapter output includes `raw_json` and all columns needed to reproduce play-be's current `SHEIN_DAILY_TRAFFIC_ANALYSIS_FIELDS`.
- The sync script can dry-run, save raw JSON, and skip MaybeAI writes.
- The sync script can write one store/day to MaybeAI Sheet using `update_data_keep_headers`.
- Re-running the same store/day with `--skip-existing-days` performs no SHEIN fetch and exits successfully.
- Re-running with `--no-skip-existing-days` merges rows by unique key instead of duplicating rows.
- `docs/adapters/browser/shein.md` documents the command and script.
- No hardcoded SHEIN usernames, passwords, bearer tokens, or webhook URLs are introduced.

## Risks And Mitigations

- SHEIN may have changed the endpoint from `/sbn/new_goods/get_skc_diagnose_list`. Mitigation: the adapter's first implementation must capture the live request from the page, and tests should isolate endpoint matching in one helper.
- The legacy task may have enriched `queried_daily_json` from another endpoint. Mitigation: keep the column, default it to empty, and add a focused follow-up only if the target sheet or business owner confirms that nested daily JSON is used downstream.
- Existing play-be skipped whole days based on any matching row. Mitigation: keep the same default in the script, while offering `--no-skip-existing-days` for backfills or correction runs.
- SHEIN sessions are fragile. Mitigation: copy the existing SHEIN script preflight login and retry behavior, and document that parallel commands against the same Browser Bridge profile are unsupported.

## Self Review

- Placeholder scan: no placeholder sections remain; unknown endpoint enrichment is recorded as a risk with a concrete verification path.
- Scope check: this spec covers one OpenCLI adapter, one sync script, docs, and tests. It does not require play-be changes in the same implementation branch.
- Consistency check: date defaults, daily expansion, target page, target sheet, skip-existing-day behavior, and field names match the inspected play-be/opencli code paths.
