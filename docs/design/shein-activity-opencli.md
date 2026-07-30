# SHEIN Activity OpenCLI Design

## 目标

把 play-be `POST /api/v1/excel/shein_activity_analysis_data` 依赖的 SHEIN 活动数据 Browser Scraper task 迁移到 opencli `shein` adapter，并新增一个业务脚本，按现有“每日流量”同步模型完成：

- 逐日检查 raw DB snapshot；
- 缺失的店铺/日期调用 opencli 补爬；
- 每个店每天爬完后立刻保存 raw DB；
- 展示阶段从 display window 的 raw DB 读取、ETL、三店合并写入同一个目标 worksheet。

本设计不改 play-be。最终交付是 opencli 命令和 repo-local Python 业务脚本，可由外部调度直接执行。

## 已读上下文

- `docs/design/shein-daily-traffic-opencli.md`
- `docs/design/shein-daily-traffic-benchmark.md`
- `docs/specs/2026-07-29-shein-daily-traffic-opencli-design.md`
- `docs/adapters/browser/shein.md`
- `clis/shein/daily-traffic.js`
- `clis/shein/daily-traffic.test.js`
- `scripts/sync-shein-daily-traffic-to-sheet.py`
- `scripts/sync-shein-daily-traffic-to-sheet.test.py`

额外用 `rg` 查找了 `shein_activity_analysis_data` / `activity_analysis`。当前 opencli 仓库内没有活动数据实现；play-be 源码位于 `/Users/duke/projects/maybeai-uni/fastestai-playground/src/fastestai_playground/excel/router/api.py`，旧 Browser Scraper template 位于 `/Users/duke/projects/maybeai-uni/app-factory/apps/plugin/templates/`。

## 旧流程事实

play-be 入口：

```text
POST /api/v1/excel/shein_activity_analysis_data
```

旧 task：

```text
extractActivityListByAPIFromShein
extractActivityGoodDetailByAPIFromShein
```

旧代码还定义了 `extractMarketingToolByAPIFromShein`，但当前 `_sync_shein_activity_analysis_data` 没有把 marketing stage 写入最终活动 Sheet。本轮 opencli 迁移只覆盖 play-be 现有实际使用的活动列表和活动商品详情两段。

旧 SHEIN 页面和候选 API：

| Stage | Page | Candidate API |
|---|---|---|
| 活动列表 | `https://sso.geiwohuo.com/#/mars/tools/list` | `POST /mrs-api-prefix/promotion/obm/query_obm_activity_list` |
| 活动商品详情 | `https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/<activity_id>` | `POST /mrs-api-prefix/promotion/simple_platform/query_goods_detail` |

这些 endpoint 来自旧 Browser Scraper template，实施时必须用已登录 SHEIN profile live capture 再确认。若 live contract 有变化，以 live capture 为准，并在 adapter 测试里固定解析 helper。

旧目标 Sheet header 来源已确认来自 play-be `SHEIN_ACTIVITY_ANALYSIS_HEADERS`：

```text
店铺,活动名称,活动规格,活动商品图片,活动商品skc,活动商品供方货号,
活动时间,活动开始时间,活动结束时间,活动终止时间,状态
```

旧默认目标：

```text
https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40
```

## 文件清单

建议新增：

- `clis/shein/activity.js`
- `clis/shein/activity.test.js`
- `scripts/sync-shein-activity-to-sheet.py`
- `scripts/sync-shein-activity-to-sheet.test.py`
- `scripts/shein-activity-prod.json`

本文档和 benchmark 文档是当前任务唯一落盘文件。本设计不要求本轮修改 `docs/adapters/browser/shein.md`，但实施活动 adapter 时应在该文档补充 `opencli shein activity`。

## 架构边界

Adapter 责任：

- 使用 Browser Bridge profile 内的已登录 SHEIN session；
- 打开活动列表页，捕获并复放活动列表 API；
- 从列表 row 提取 `activity_id`；
- 对每个 `activity_id` 打开或模拟详情页上下文，调用详情 API 并分页；
- 输出 source-shaped scalar fields 和 raw payload fields；
- 不写 DB、不写 Sheet、不读 MaybeAI API、不落本地 JSON 文件。

业务脚本责任：

- 解析日期窗口、store/profile、Sheet URL 和 raw DB 配置；
- 用 raw DB snapshot 判定每个店铺/日期是否需要爬；
- 调用 `opencli shein activity -f json` 补爬缺失日期；
- 每个店每天爬完后立即写 raw staging worksheet，并调用 `excel__save_table_worksheet_to_mongodb`；
- 展示阶段从 display window 的 raw DB 读取活动 raw rows；
- 做 ETL 和去重，三店合并写入同一个目标 worksheet；
- 支持 `--skip-sheet-write` 只补 raw DB，不更新业务 Sheet；
- 不向本地写 raw JSON 文件。
- `--etl-source raw-api` 写业务 Sheet 时刷新当前店铺 rows 并保留其他店铺 rows；legacy 活动表没有日期列，不能像每日流量一样按 `日期` 过滤当前店铺旧行。

MaybeAI Sheet 责任：

- 只保存业务可见投影；
- header 保持 legacy 11 列；
- 不是 raw archive，不能用于判断是否跳过爬虫。

DB raw records 责任：

- 作为审计、重放和未来 ETL 的源；
- 以店铺 + 日期 snapshot 作为 crawl skip 判断依据。

## 命令形态

Adapter smoke：

```bash
npm exec -- opencli --profile w2db43wa shein activity \
  --snapshotDate 2026-07-29 \
  --insertStartTime "2026-01-29 00:00:00" \
  --insertEndTime "2026-07-29 23:59:59" \
  --pageSize 100 \
  --limitActivities 5 \
  -f json
```

单店业务脚本：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --profile w2db43wa \
  --store 店3 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40" \
  --start-date 2026-07-29 \
  --end-date 2026-07-29 \
  --etl-source raw-api \
  --raw-db
```

生产三店：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store-config scripts/shein-activity-prod.json \
  --crawl-last-days 30 \
  --sheet-display-days 30 \
  --etl-source raw-api \
  --raw-db \
  --ensure-headers \
  --request-timeout 120 \
  --cli-timeout 3600
```

只补爬 raw DB：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store-config scripts/shein-activity-prod.json \
  --crawl-last-days 30 \
  --etl-source raw-api \
  --raw-db \
  --skip-sheet-write
```

## Adapter 设计

Command metadata：

- `site`: `shein`
- `name`: `activity`
- `strategy`: `Strategy.COOKIE`
- `browser`: `true`
- `navigateBefore`: `false`
- `defaultWindowMode`: `foreground`
- `defaultFormat`: `json`
- `domain`: `sso.geiwohuo.com`

参数：

| Argument | Meaning |
|---|---|
| `snapshotDate` | raw DB snapshot 日期，`YYYY-MM-DD` 或 `YYYYMMDD`；不传默认昨天。 |
| `insertStartTime` | 活动列表查询创建时间下界；不传用捕获 body，其次默认 snapshotDate 往前 6 个月 00:00:00。 |
| `insertEndTime` | 活动列表查询创建时间上界；不传用捕获 body，其次默认 snapshotDate 23:59:59。 |
| `typeId` | 活动类型；不传用捕获 body，其次 `31`。 |
| `system` | 不传用捕获 body，其次 `mrs`。 |
| `timeZone` | 不传用捕获 body，其次浏览器时区，再其次 `Asia/Shanghai`。 |
| `pageSize` | 列表和详情分页大小；不传用捕获 body，其次 `100`。 |
| `limitActivities` | 最多处理多少个活动，用于 smoke。 |
| `limitRows` | 最多返回多少个详情商品/SKU row，用于 smoke。 |
| `maxListPages` | 活动列表最大页数。 |
| `maxDetailPages` | 每个活动详情最大页数。 |
| `detailConcurrency` | 详情阶段 activity/page 请求并发；默认参考旧模板为 `5`，live benchmark 可下调。 |
| `requestDelayMinMs` / `requestDelayMaxMs` | 详情或列表分页延迟窗口；用于控制 SHEIN 风控风险。 |
| `requestTimeout` | 单次捕获/请求 timeout 秒，默认 `60`。 |
| `retryAttempts` | 页面 API 重试次数，默认 `3`。 |
| `retryDelayMs` | 重试基础间隔毫秒，默认 `1000`。 |
| `timeout` | 整个 opencli 命令 timeout 秒，默认 `3600`。 |

活动列表流程：

1. 打开 `https://sso.geiwohuo.com/#/mars/tools/list`。
2. 确认 `location.href` 仍在 `https://sso.geiwohuo.com` 下，否则抛 `CommandExecutionError`。
3. 安装 fetch/XHR capture harness，匹配 `/mrs-api-prefix/promotion/obm/query_obm_activity_list`。
4. 尝试点击页面查询按钮；如果找不到按钮，则 reload route 等待 endpoint。
5. 提取首个成功 capture：request body、可复放 headers、response JSON。
6. 构造 list request body，保留页面筛选条件，覆盖 `insert_start_time`、`insert_end_time`、`page_num`、`page_size`、`type_id`、`system`、`time_zone`。
7. 通过 `page.fetchJson` 分页，直到空页、短页、total count、`maxListPages` 或 `limitActivities`。

详情流程：

1. 从列表 rows 提取并去重 `activity_id`。
2. 对每个 activity id 使用 detail route 语义：

```text
/#/mrs/tools/activity/obm-time-limit-info/<activity_id>
```

3. 调用候选详情 API：

```text
POST /mrs-api-prefix/promotion/simple_platform/query_goods_detail
```

4. request body：

```json
{
  "activity_id": "<activity_id>",
  "page_num": 1,
  "page_size": 100
}
```

5. headers 保留 SHEIN 业务/风控 headers，丢弃 browser-managed 或敏感 headers：`accept-encoding`、`connection`、`content-length`、`cookie`、`host`、`origin`、`referer`、`user-agent`、`priority`、`sec-*`、`proxy-*`。详情 API 若需要 `origin-url`、`x-bbl-route`、`x-req-zone-id`、`x-req-sso-zone-id`，由 adapter 按当前 activity route 构造。
6. 分页直到空页、短页、total count、`maxDetailPages` 或 `limitRows`。

输出 rows 以活动商品详情为主：每个 detail goods/SKU row 生成一行，并携带对应列表 raw row；如果活动列表有活动但详情为空，生成 `record_type=activity_list_only` 的 raw snapshot 行，并在 ETL 中保留为空商品字段的业务行，以对齐 legacy play-be 活动产物。

输出 columns 建议：

```text
record_type, snapshot_date, store, profile,
request_url, list_request_url, detail_request_url,
queried_insert_start_time, queried_insert_end_time, queried_page_size,
queried_type_id, queried_time_zone, queried_system,
activity_total_count, activity_total_pages, activity_page_num,
detail_total_count, detail_total_pages, detail_page_num,
activity_id, activity_name, activity_status, activity_type_id,
activity_type_name, site, country, creator, created_at, updated_at,
start_time, end_time, terminate_time, state, store_code, supplier_id,
source_store_name, tool_name, raw_activity_json,
goods_id, skc, image_url, sku_supplier_no, attend_num_sum, stock_num,
ivt_num, inventory_num, goods_product_act_price, goods_max_product_act_price,
goods_is_effective, goods_failed_reason, goods_state, goods_is_del,
goods_currency, goods_supply_price_new, goods_supply_price,
goods_us_supply_price, goods_eur_supply_price, goods_uk_supply_price,
goods_mxn_supply_price, is_sale_attribute, pricing_type, product_tag,
sku_count, sku, sku_currency, sku_supply_price_new, sku_product_act_price,
sku_max_product_act_price, sku_supply_price, sku_us_supply_price,
sku_eur_supply_price, sku_uk_supply_price, sku_mxn_supply_price,
sku_main_attr_names, sku_sale_attr_names, sku_attr_info_list_json,
goods_country_attr_info_list_json, sku_info_list_json, raw_detail_json,
raw_json
```

字段说明：

- `record_type` 取 `activity_detail` 或 `activity_list_only`。
- `snapshot_date` 是本次店铺/日期 raw snapshot 的 `YYYY-MM-DD`，用于 DB key 和日志，不写业务 Sheet。
- `raw_activity_json` 保存活动列表原始 row。
- `raw_detail_json` 保存详情 goods/SKU 原始 row。
- `raw_json` 可保存 `{ activity, detail }` 合并对象，便于 raw worksheet 落库。
- 业务 Sheet 不写任何 JSON blob 字段。

待 live 确认：

- 活动列表 response rows 的最终路径：旧 template 支持多种 `info.data` / `payload.info.data` / `result` 形态，adapter helper 需要按 live response 固定优先级。
- 活动详情 rows 是 goods-level 还是 sku-level；如果 sku-level 会导致同一活动/SKC 多行，业务 ETL 应先按 `activity_id + skc` 选择代表行，优先保留有 `sku_supplier_no`、`image_url` 的行。
- `terminate_time` 是否存在于列表 API；play-be 只用 alias 读取 `terminateTime`、`stopTime`、`closeTime`、`cancelTime`、`abortTime` 等字段。

## 业务脚本设计

脚本参数应复用每日流量的命名和行为：

| Argument | Meaning |
|---|---|
| `--start-date` / `--end-date` | crawl window。逐日检查 raw DB 和补爬。 |
| `--crawl-last-days N` | crawl/check 最近 N 天，不能和 `--start-date` 同用。 |
| `--sheet-display-days N` | display window。只控制最终从 raw DB 读取哪些 snapshot 并写业务 Sheet。 |
| `--raw-read-days N` | 覆盖最终 raw DB read window。 |
| `--store` | 写入 `店铺` 的业务名称。 |
| `--profile` | Browser Bridge profile。一个店一个 profile。 |
| `--sheet-url` | 目标 Maybe Sheet URL，必须可从 gid 解析 worksheet；配置文件可给默认 URL。 |
| `--worksheet-name` | 可选 override；当命令行 `--sheet-url` 带 gid 时，优先用 gid 解析。 |
| `--store-config` | 顺序执行多店配置。 |
| `--store-key` | 过滤配置中的店。 |
| `--raw-db` | 启用 raw worksheet 写入和 MongoDB save。 |
| `--etl-source fresh|raw-api` | 推荐生产使用 `raw-api`。 |
| `--skip-existing-days` / `--no-skip-existing-days` | 默认启用；只依据 raw DB snapshot。 |
| `--skip-sheet-write` | 只补爬/补 DB，不读写业务 Sheet；必须同时启用 `--raw-db`，避免只爬不保存。 |
| `--ensure-headers` | 写入前确保 legacy header。 |
| `--clear-worksheet-data` | 可选清空数据行但保留 header；生产默认 false。 |
| `--dry-run` | 拉取/ETL 汇总但不写 Sheet、不 save raw DB。 |

日期窗口语义：

- crawl window 用于逐日、逐店查 raw DB 和补爬；
- display window 用于读取 raw DB snapshot、ETL、写业务 Sheet；
- 两者必须分离。例如 `--crawl-last-days 60 --sheet-display-days 30` 表示检查 60 天 DB 缺口，但只用最近 30 天 raw snapshot 重算当前展示 Sheet。
- 活动 Sheet 本身没有 `日期` 列；display window 的日期是 raw snapshot `data_date`，不是活动开始时间或结束时间过滤器。
- 显式历史 crawl window 的 raw DB planning read 会把 `last_n_days` 扩展到覆盖最早请求日期到昨天，再过滤回请求日期，避免补历史两天时只读“最近两天”。

核心流程：

1. load env files。
2. 解析 store config；没有 config 时处理单个 `--store + --profile`。
3. 建 MaybeAI client，解析 `--sheet-url` document id 和 gid。
4. 对每个 store/profile：
   - 解析 crawl window 日期列表；
   - 读取 raw DB snapshot days；
   - 每一天独立判断 `store + date` 是否已有 snapshot；
   - 有 snapshot 则 skip；
   - 无 snapshot 则调用 `opencli shein activity --snapshotDate <day> -f json`；
   - 当天爬完立即写 raw worksheet 并调用 MongoDB save；
5. 如果 `--skip-sheet-write`，输出 summary 后结束，不读取或写入业务 Sheet。
6. 从 display window 的 raw DB 读取三店 raw rows。
7. ETL 成 legacy 11 列，按唯一键去重。
8. 三店合并写入同一个目标 worksheet。
9. 写后按实际写入 row range 验证可见记录。

## DB Key 策略

Raw save 一天一次，成功爬完当天立刻保存。即使当天 SHEIN 返回 0 行，也要保存空 snapshot，使后续 rerun 可 skip。

建议 raw type：

```text
shein_activity
```

建议日志 key：

```text
shein_activity:<store>:<profile>:<YYYY-MM-DD>
```

MongoDB save payload：

```json
{
  "app": "function_call",
  "tool_id": "excel__save_table_worksheet_to_mongodb",
  "tool_name": "save_table_worksheet_to_mongodb",
  "tool_args": {
    "data_date": "YYYY-MM-DD",
    "uri": "<raw-db-uri>",
    "worksheet_name": "<store>活动数据"
  }
}
```

Skip key：

```text
店铺 + snapshot_date
```

去重 key：

- raw 层：`store + snapshot_date + activity_id + skc + sku_supplier_no`；
- Sheet 层：`店铺 + 活动名称 + 活动开始时间 + 活动商品skc + 活动商品供方货号`；
- 若 live response 能稳定提供 `activity_id`，业务脚本内部应优先用 `activity_id + skc + sku_supplier_no` 去重，再映射成 11 列。

raw-api 写表策略：

- crawl planning 读取 crawl window 对应 raw DB snapshot days，缺失 store/day 才爬。
- display 阶段读取 `--sheet-display-days` 对应 raw DB snapshots 后 ETL。
- 当前店铺旧业务行由 display raw snapshots 重新生成并替换。
- 若当前店 display window ETL 为 0 行，也要写回目标 Sheet：清掉当前店旧业务行，保留其他店铺行。
- 其他店铺在同一目标 worksheet 里的业务行会保留，三店顺序执行后得到合并表。
- raw staging worksheet 每行写入 `raw_db_type` 和 `raw_key`，key 格式为 `shein_activity:<store>:<profile>:<YYYY-MM-DD>`；MongoDB save payload 同步传入该 key。
- 成功但无活动商品详情的日期写 `record_type=empty_snapshot` 到 raw staging worksheet，再调用 MongoDB save tool，避免下次重复爬同一天。

## Sheet ETL

目标 header：

```text
店铺,活动名称,活动规格,活动商品图片,活动商品skc,活动商品供方货号,
活动时间,活动开始时间,活动结束时间,活动终止时间,状态
```

映射规则：

| Sheet Field | Rule |
|---|---|
| `店铺` | 脚本 `--store`。 |
| `活动名称` | `activity_name` / `act_name` / `prom_name` / `name`。 |
| `活动规格` | `activity_type_id` / `type_id` 映射：`31=限时折扣`、`1=店铺活动`、`2=平台大促`、`9=多买多折`、`21=新人专享`；无法映射则保留源值。 |
| `活动商品图片` | 详情 `image_url`，fallback 列表 `image_url/img_url`。 |
| `活动商品skc` | 详情 `skc`，fallback 列表 `skc/goods_skc/product_skc`。 |
| `活动商品供方货号` | 详情 `sku_supplier_no`。 |
| `活动时间` | `<活动开始时间> ~ <活动结束时间>`，任一为空时仍保留可见部分。 |
| `活动开始时间` | 列表 `start_time/startTime/activity_start_time/activityStartTime`。 |
| `活动结束时间` | 列表 `end_time/endTime/activity_end_time/activityEndTime`。 |
| `活动终止时间` | `terminateTime/terminatedTime/stopTime/closeTime/cancelTime/abortTime` alias。 |
| `状态` | `state/status` 映射：`3=开启`、`4=已结束`、`6=已终止`；无法映射则保留源值。 |

业务 Sheet 中不写 `activity_id`、查询参数、库存、价格、SKU 属性、raw JSON。这些都留在 raw DB。

## MaybeAI API 使用

复用每日流量脚本的 client 结构：

- token 环境变量：`MAYBEAI_API_TOKEN`、`MAYBEAI_AUTH_TOKEN` 或 `MAYBEAI_API_KEY`；
- `POST /api/v1/excel/list_worksheets`：用 `--sheet-url` 的 gid 解析 worksheet name；
- `POST /api/v1/excel_v2/worksheet/dimensions`：读取目标表 used row count；
- `read_sheet` 或 range read helper：按 `A1:K10001`、`A10002:K20001` 分块读取目标 Sheet，用于 merge/write 保留，不用于 skip；
- `POST /api/v1/excel/update_data_keep_headers`：写业务 Sheet，`start_row=2`，保留 header；
- `POST /api/v1/tool/function_call` + `excel__save_table_worksheet_to_mongodb`：保存每个 raw snapshot；
- `POST /api/v1/tool/function_call` + `excel__read_recent_worksheet_snapshots`：按 raw workbook/worksheet/display window 读取 snapshot。

不得使用目标业务 Sheet 判断爬虫 skip。目标 Sheet 只参与 header、merge、write、verification。

## 生产配置

`scripts/shein-activity-prod.json` 建议：

```json
{
  "defaults": {
    "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40",
    "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/6a6b38cac5b0a12620ef6c91",
    "worksheet_name": "活动数据",
    "sheet_display_days": 30
  },
  "stores": [
    {"key": "store1", "store": "店1", "profile": "jegkb2wv", "raw_db_worksheet_name": "店1活动数据"},
    {"key": "store2", "store": "店2", "profile": "m3cjm28a", "raw_db_worksheet_name": "店2活动数据"},
    {"key": "store3", "store": "店3", "profile": "w2db43wa", "raw_db_worksheet_name": "店3活动数据"}
  ]
}
```

`raw_db_uri` 需要实施前由生产环境确认，不能在代码中硬编码未知私有 workbook。

## 错误、重试和日志

Adapter 错误：

- 日期格式错误：`CommandExecutionError`；
- 未登录或跳转到登录页：错误信息包含 login/session 关键词，便于脚本触发 login；
- capture timeout：包含 endpoint pattern 和 current URL；
- API `code != 0`：包含 code/msg；
- 分页重复失败：包含 activity id、page num、最后错误；
- activity list 无 row：返回空数组，不视为 adapter 失败。

脚本错误：

- 缺 MaybeAI token、非法 Sheet URL、gid 无法解析：爬虫前失败；
- `whoami` 失败：按每日流量逻辑尝试 `opencli shein login`；
- retryable CLI 失败：整天重试，成功后才 save DB；
- raw DB save 失败：当天视为失败，不允许标记 skip；
- Sheet write 或 verification 失败：退出非 0；
- 某店失败是否继续后续店：建议默认 fail-fast，后续可加 `--continue-on-store-error`。

日志：

- 日志目录默认 `artifacts/shein-activity/logs`；
- 每个店/日期输出 fetch、skip、raw-save、ETL、write、verify summary；
- 不打印 cookie、authorization、password、完整 raw JSON；
- 可打印 row count、activity count、detail row count、snapshot key。

## Verification 策略

Unit：

- adapter helper 测试：date、header sanitize、list body、detail body、payload extraction、flatten、pagination stop、state/type mapping；
- script helper 测试：date window、store config、raw snapshot skip、raw save payload、ETL mapping、dedupe、display window raw read、skip-sheet-write。

Live：

- `opencli shein whoami -f json` 通过；
- adapter `--limitActivities 1 --limitRows 5` 返回 JSON array；
- dry run 不调用 MaybeAI write；
- raw DB mode 对一个店/日期保存 snapshot；
- rerun 同一天从 raw DB skip，不调用 opencli；
- display window 读取 raw DB 后三店合并写同一 worksheet；
- 写后用 row range 读取验证，而不是 `filter_tokens`。

## 实施步骤

1. 新增 `clis/shein/activity.js` helper 和 unit tests。
2. 用 live profile 验证活动列表 endpoint、headers、response path。
3. 实现详情 endpoint 分页和 raw flatten。
4. 新增 `scripts/sync-shein-activity-to-sheet.py` 的纯 helper 和 tests。
5. 实现 raw DB 逐日 save、raw-api read、crawl/display window 分离。
6. 实现 Sheet header、merge、write、range verification。
7. 新增 `scripts/shein-activity-prod.json`，填入三店 profile。
8. 更新 `docs/adapters/browser/shein.md`。
9. 按 benchmark 文档跑 unit、dry-run、安全 Sheet live E2E。

## 非目标

- 不修改 play-be。
- 不提交 credentials、token、webhook。
- 不落本地 JSON 文件。
- 不用目标业务 Sheet 判断 skip。
- 不在 adapter 中写 DB 或 Sheet。
- 不并发使用同一个 SHEIN profile；三店可以顺序跑，后续如要并发必须确保每店独立 profile。
