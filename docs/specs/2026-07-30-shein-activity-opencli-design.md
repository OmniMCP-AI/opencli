# SHEIN 活动数据 OpenCLI 同步 Spec

## 目标

为 SHEIN「活动数据」新增一套 opencli + 业务脚本独立同步能力，替代 play-be `POST /api/v1/excel/shein_activity_analysis_data` 当前依赖的 Browser Scraper task。最终交付形态应和现有「每日流量」一致：OpenCLI 负责在已登录 SHEIN GSP 浏览器会话中抓取源站 raw 数据，业务脚本负责逐日 raw DB 快照、ETL、三店合并和 MaybeAI Sheet 写入。

本轮不修改 play-be。外部调度可以直接运行业务脚本完成抓取、保存 raw DB、ETL 和写表。

## 非目标

- 不改 play-be 路由、请求模型、认证逻辑或旧 Browser Scraper task。
- 不把 raw JSON 文件落地到本地；raw 数据只通过业务脚本保存进 DB。
- 不用目标业务 Sheet 判断是否需要爬取。
- 不在 OpenCLI adapter 中写 MaybeAI Sheet 或调用 MaybeAI DB API。
- 不实现同一 Chrome/OpenCLI profile 多店铺复用。
- 不把「每日流量」字段、表头或端点照搬到活动数据；每日流量只作为流程边界参考。

## 现状和参考线索

已读取并参考：

- `docs/specs/2026-07-29-shein-daily-traffic-opencli-design.md`
- `docs/design/shein-daily-traffic-opencli.md`
- `docs/design/shein-daily-traffic-benchmark.md`
- `docs/adapters/browser/shein.md`
- `clis/shein/daily-traffic.js`
- `scripts/sync-shein-daily-traffic-to-sheet.py`

每日流量的可复用边界：

- OpenCLI adapter 只处理 SHEIN 页面会话、接口捕获、分页复放和 raw-shaped JSON 输出。
- Python 业务脚本处理 `whoami/login` 预检、OpenCLI 子进程重试、raw DB 保存、raw DB 读回、ETL、merge 和 `update_data_keep_headers` 写表。
- 是否爬取由 raw DB `店铺 + 日期` 快照决定，不由目标业务 Sheet 行决定。
- `--crawl-last-days`/crawl window 只控制 raw DB 查缺补缺；业务 Sheet 每次只导出本次窗口最新一天。
- `--skip-sheet-write` 支持只爬取和保存 raw DB，不写业务 Sheet。

仓库及相邻目录 `rg "shein_activity_analysis_data|activity_analysis"` 命中关键线索：

- play-be 源码：`/Users/duke/projects/maybeai-uni/fastestai-playground/src/fastestai_playground/excel/router/api.py`
  - 路由：`POST /api/v1/excel/shein_activity_analysis_data`
  - 当前旧 task：
    - `extractActivityListByAPIFromShein`
    - `extractActivityGoodDetailByAPIFromShein`
    - `extractMarketingToolByAPIFromShein` 存在常量，但当前主流程未写入最终 11 列。
  - 页面：
    - 活动列表：`https://sso.geiwohuo.com/#/mars/tools/list`
    - 活动商品详情：`https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/1`
  - 默认目标表：`https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40`
  - 默认店铺名：`普通店铺`
  - 目标表头范围：`A1:K1`
- play-be 请求模型：`SheinActivityAnalysisDataRequest`
  - `target_url`
  - `user`
  - `password`
  - `store_name`
  - `clear_worksheet_data`
  - `mock_mode`
  - `mock_activity_list_sheet_url`
  - `mock_activity_good_detail_sheet_url`
  - `mock_marketing_sheet_url`
- Browser Scraper 模板：
  - `/Users/duke/projects/maybeai-uni/app-factory/apps/plugin/templates/extractActivityListByAPIFromShein/action_code.js`
  - `/Users/duke/projects/maybeai-uni/app-factory/apps/plugin/templates/extractActivityGoodDetailByAPIFromShein/action_code.js`
- 可疑源站接口：
  - 活动列表：`POST https://sso.geiwohuo.com/mrs-api-prefix/promotion/obm/query_obm_activity_list`
  - 活动商品详情：`POST https://sso.geiwohuo.com/mrs-api-prefix/promotion/simple_platform/query_goods_detail`
- ref-crawler 调度脚本：`/Users/duke/projects/ref-crawler/src/spiders/youqiantu/activity_list.py`
  - 当前逐店调用 play-be API。
  - 旧 prod 三个 job 用 `store_name=店1/店2/店3`，其中店1清表、店2/店3追加；新 opencli 业务脚本不应复用这种“店1清表”语义，应统一 merge 写入。

## 数据流

推荐整体流程：

1. 业务脚本解析 store config、crawl window、目标 Sheet URL、raw DB 配置。
2. 对每个店铺按顺序处理；一个店铺只使用一个 Chrome/OpenCLI profile。
3. 对 crawl window 内每一天，先读 raw DB 快照索引，判断该 `店铺 + 日期` 是否已有 raw snapshot。
4. 已有 raw snapshot 的日期跳过 OpenCLI 爬取。
5. 缺失 raw snapshot 的日期调用 `opencli shein activity` 抓取活动列表和商品详情。
6. 每个缺失日期抓完后，立即把该店该日期的 raw 行写入 raw staging worksheet，并调用保存到 MongoDB 的 API；一天一次保存。
7. 写表阶段一次性读取本次窗口最新一天的 raw DB 快照。
8. 业务脚本把 raw activity list + raw detail rows 做 ETL，生成目标业务表头。
9. 三个店铺最终合并写入目标 Sheet；同一目标 URL 的 `gid` 决定写入 worksheet。
10. `--skip-sheet-write` 时跳过第 8 步之后的业务 Sheet merge/write，但仍执行缺失日期爬取和 raw DB 保存。

注意：play-be 旧活动接口没有日期参数；这里的 `日期` 是 raw DB 快照日期 `data_date`。若 SHEIN 活动列表接口无法按历史日期重建状态，补爬过去缺失日期只能得到当前可见活动数据，应在实现前确认并限制行为。

## OpenCLI CLI/API 需求

建议新增命令：

```bash
opencli --profile jegkb2wv shein activity \
  --snapshotDate 2026-07-30 \
  --insertStartTime "2026-01-30 00:00:00" \
  --insertEndTime "2026-07-30 23:59:59" \
  --pageSize 100 \
  -f json
```

命令职责：

- 打开 `https://sso.geiwohuo.com/#/mars/tools/list`。
- 验证当前页面仍在 `https://sso.geiwohuo.com` 域下；遇到登录页或权限页时抛出可被业务脚本识别的 auth/session 错误。
- 捕获活动列表接口 `/mrs-api-prefix/promotion/obm/query_obm_activity_list` 的首个成功请求，保留可复放 headers/body。
- 以捕获 body 为基础构建分页请求，允许 CLI 覆盖：
  - `insert_start_time`
  - `insert_end_time`
  - `type_id`
  - `system`
  - `time_zone`
  - `page_num`
  - `page_size`
- 活动列表分页输出每个 activity 的 raw-shaped 字段和 `raw_json`。
- 从活动列表提取唯一 `activity_id`/`prom_id`，用短横线或数组形式传入详情抓取阶段。
- 打开或构造 `/#/mrs/tools/activity/obm-time-limit-info/<activity_id>`，调用 `/mrs-api-prefix/promotion/simple_platform/query_goods_detail`。
- 详情阶段按 `activity_id + page_num/page_size` 分页，输出商品/SKU 级 raw-shaped 字段和 `raw_json`。
- 最终 JSON 输出以活动商品详情行为主：
  - `record_type=activity_detail`：每个 detail goods/SKU row 一行，并携带对应列表 raw row。
  - `record_type=activity_list_only`：活动列表有活动但详情为空时保留一行 raw snapshot，并进入业务 Sheet ETL，商品字段留空。

推荐通用参数：

- `--snapshotDate <date>`：raw DB `data_date`，接受 `YYYY-MM-DD` 或 `YYYYMMDD`。缺省为昨天或业务脚本显式传入的 crawl day。
- `--insertStartTime <datetime>` / `--insertEndTime <datetime>`：活动列表源站查询窗口；默认沿用捕获 body，其次按旧 Browser Scraper 模板取 `snapshotDate` 往前 6 个月到 `snapshotDate 23:59:59`。
- `--activityIds <ids>`：可选，只抓指定活动详情；支持逗号、换行、JSON array 或旧 task 的 `1-2-3` 格式。
- `--typeId <n>`：默认沿用捕获 body，最后 fallback `31`。
- `--system <value>`：默认沿用捕获 body，最后 fallback `mrs`。
- `--timeZone <value>`：默认沿用捕获 body，最后 fallback `Asia/Shanghai`。
- `--pageSize <n>`：默认沿用捕获 body，最后 fallback `100`。
- `--limitActivities <n>`：限制活动列表处理数量，调试用。
- `--limitRows <n>`：限制最终详情商品/SKU 输出行数，调试用。
- `--maxListPages <n>`：限制活动列表分页页数，调试用。
- `--maxDetailPages <n>`：限制每个活动详情分页页数，调试用。
- `--detailConcurrency <n>`：详情阶段并发，默认参考旧模板为 `5`，可在 live benchmark 后调低。
- `--requestDelayMinMs <n>` / `--requestDelayMaxMs <n>`：分页/详情请求延迟窗口，默认参考旧模板的 0-500ms 或列表 500-1300ms 量级。
- `--requestTimeout <seconds>`、`--retryAttempts <n>`、`--retryDelayMs <ms>`、`--timeout <seconds>`：沿用每日流量风格。

header 复放策略：

- 使用 blocklist 去掉 `cookie`、`host`、`content-length`、`accept-encoding`、`connection`、`origin`、`referer`、`sec-*`、`:*`、`proxy-*` 等浏览器托管或不安全 headers。
- 详情接口需要保留或构造 `origin-url`、`x-bbl-route`、`x-req-zone-id`、`x-req-sso-zone-id`、`lan`、`x-lt-language` 等旧模板中出现的业务 headers；旧模板默认并发 5、请求延迟 0-500ms，opencli 实现需把并发和延迟做成可控参数并 live 验证 SHEIN 风控表现。

## 业务脚本参数

建议新增脚本：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store-config scripts/shein-activity-prod.json \
  --crawl-last-days 60 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/<doc-id>?gid=<gid>"
```

单店调试：

```bash
python3 scripts/sync-shein-activity-to-sheet.py \
  --store 店1 \
  --profile jegkb2wv \
  --crawl-last-days 7 \
  --sheet-url "https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40" \
  --dry-run
```

必须支持参数：

- `--store <name>`：写入 `店铺` 的业务名。
- `--profile <id-or-alias>`：OpenCLI Browser Bridge profile。
- `--store-config <path>`：多店顺序执行配置。
- `--store-key <key>`：过滤 store config。
- `--sheet-url <url>`：目标 MaybeAI Sheet URL，必须可配置；URL 中 `gid` 决定写入 worksheet。
- `--worksheet-name <name>`：可选 worksheet override；当 `--sheet-url` 带 gid 时优先用 gid 解析。
- `--crawl-last-days <n>`：crawl window，逐日检查 raw DB。
- `--start-date <date>` / `--end-date <date>`：显式 crawl window。
- `--raw-read-days <n>`：覆盖最终 raw DB 读取窗口。
- `--skip-existing-days` / `--no-skip-existing-days`：默认 true；只看 raw DB。
- `--skip-sheet-write`：只爬取并保存 raw DB，不写目标 Sheet；必须同时启用 `--raw-db`，避免只爬不保存。
- `--dry-run`：允许跑 ETL summary/sample，不写 raw DB 和业务 Sheet。
- `--raw-db-uri`、`--raw-db-worksheet-name`、`--raw-db-worksheet-suffix`、`--raw-db-type`、`--raw-db-save-path`、`--raw-db-read-path`：沿用每日流量业务脚本模型。
- `--opencli-cmd`、`--request-timeout`、`--api-retry-attempts`、`--api-retry-delay-ms`、`--opencli-timeout`、`--attempts`、`--retry-delay-seconds`、`--login-on-retry`、`--preflight-login`、`--login-timeout`、`--login-wait-seconds`：沿用每日流量脚本。
- `--insert-start-time`、`--insert-end-time`、`--type-id`、`--system`、`--time-zone`、`--activity-ids`、`--page-size`、`--limit-activities`、`--limit-rows`、`--max-list-pages`、`--max-detail-pages`、`--detail-concurrency`、`--request-delay-min-ms`、`--request-delay-max-ms`：透传给 OpenCLI activity adapter。

生产 profile 配置必须支持：

```json
{
  "defaults": {
    "sheet_url": "https://www.maybe.ai/docs/spreadsheets/d/<target-doc>?gid=<activity-gid>",
    "raw_db_uri": "https://www.maybe.ai/docs/spreadsheets/d/6a6b38cac5b0a12620ef6c91",
    "worksheet_name": "活动数据ETL"
  },
  "stores": [
    {"key": "store1", "store": "店1", "profile": "jegkb2wv", "raw_db_worksheet_name": "店1活动数据"},
    {"key": "store2", "store": "店2", "profile": "m3cjm28a", "raw_db_worksheet_name": "店2活动数据"},
    {"key": "store3", "store": "店3", "profile": "w2db43wa", "raw_db_worksheet_name": "店3活动数据"}
  ]
}
```

## DB key 和保存策略

raw DB 是爬取完整性的唯一判断来源。

raw snapshot 判断 key：

```text
raw_db_type + store + data_date
```

建议日志 key：

```text
shein_activity:<store>:<profile>:<YYYY-MM-DD>
```

保存策略：

- crawl window 内逐日检查 raw DB。
- raw DB 已有 `store + data_date` 快照则 skip。
- raw DB 没有该日快照则运行 OpenCLI 爬取该日。
- 每天 OpenCLI 成功后立即保存 raw DB；不得等所有日期爬完再批量保存。
- 即使当天活动列表为空，也要保存空 raw snapshot，避免同一天反复爬取。
- raw staging worksheet 和 MongoDB save payload 都应包含 `raw_key=shein_activity:<store>:<profile>:<YYYY-MM-DD>` 与 `raw_db_type=shein_activity`。
- 空 raw snapshot 应在 raw staging worksheet 写入 `record_type=empty_snapshot`、`snapshot_date`、`store`、`profile`、`raw_key` 后再调用 MongoDB save tool。
- raw staging worksheet 表头应覆盖 activity list 和 detail 的 raw 字段，并至少包含：
  - `record_type`
  - `snapshot_date`
  - `store`
  - `profile`
  - `activity_id`
  - `raw_activity_json`
  - `raw_detail_json`
  - `raw_json`
- MongoDB 保存 payload 沿用每日流量模式：

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

读取策略：

- crawl planning 读取完整 crawl window 的 raw snapshot days。
- 对显式历史 crawl window，planning read 的 `last_n_days` 需要覆盖最早请求日期到昨天，再过滤回请求日期，不能只传请求天数。
- 写表前一次性读取本次 crawl/request 窗口最新一天的 raw DB 快照。
- 示例：`--crawl-last-days 60` 应先检查 60 天 raw DB 缺失日期，只爬缺失日期；写表时只读取最新一天 raw DB，ETL 后把 3 个店合并写入目标 Sheet。

## Sheet 写入策略

目标 Sheet：

- URL 必须通过 `--sheet-url` 配置。
- `gid` 决定 worksheet；不可硬编码 gid 40 到脚本行为里。
- 若命令行显式传入 `--sheet-url`，即使 store config 有默认 `worksheet_name`，也应按命令行 URL 的 `gid` 解析目标 worksheet。
- 可保留 play-be 默认 `https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=40` 作为示例，不作为生产强制值。

写入规则：

- 三个店铺读取各自最新一天 raw DB 后，ETL 合并写入同一个目标 worksheet。
- 使用 `update_data_keep_headers`，从第 2 行写入，保留表头。
- 支持 `--ensure-headers` 重写 header row。
- 支持 `--clear-worksheet-data`，但默认不应依赖“店1先清表、店2/店3追加”的旧调度语义。
- 默认按唯一键 merge，避免重复行。
- 由于 legacy 活动表没有日期列，`--etl-source raw-api` 写表时应刷新当前店铺业务行并保留其他店铺业务行；三店顺序执行后目标 worksheet 是三店合并结果。
- 当前店最新一天 ETL 为 0 行时也必须写回目标 Sheet，清除当前店旧行并保留其他店铺行。
- 推荐业务唯一键：

```text
店铺 + 活动名称 + 活动商品skc + 活动商品供方货号 + 活动开始时间 + 活动结束时间
```

若保留 raw detail 的 `activity_id`，更稳定的内部 merge key 应使用：

```text
店铺 + activity_id + 活动商品skc + sku
```

最终写入前按 `店铺`、`活动开始时间`、`活动名称`、`活动商品skc` 排序。具体升降序可按业务表习惯确认；默认建议最新活动开始时间优先。

`--skip-sheet-write`：

- 仍读取 raw DB 做 skip 计划。
- 仍对缺失日期执行 OpenCLI 爬取。
- 仍在每个成功日期后保存 raw DB。
- 不读取目标业务 Sheet、不 merge、不写表、不做 Sheet 写后校验。

## ETL 表头和字段待确认项

play-be 当前最终业务表头为 11 列：

```text
店铺,活动名称,活动规格,活动商品图片,活动商品skc,活动商品供方货号,活动时间,活动开始时间,活动结束时间,活动终止时间,状态
```

play-be 当前映射线索：

- `店铺`：请求 `store_name` 或组织配置 `activity_analysis_store_name` 或默认 `普通店铺`。
- `活动名称`：activity list/detail 中的 `activity_name`。
- `活动规格`：`type_id` 映射：
  - `31` -> `限时折扣`
  - `1` -> `店铺活动`
  - `2` -> `平台大促`
  - `9` -> `多买多折`
  - `21` -> `新人专享`
- `活动商品图片`：detail `image_url`。
- `活动商品skc`：detail `skc`。
- `活动商品供方货号`：detail `sku_supplier_no`。
- `活动时间`：由开始/结束时间格式化为 `start ~ end`。
- `活动开始时间`：`start_time/startTime/activity_start_time/begin_time`。
- `活动结束时间`：`end_time/endTime/activity_end_time/finish_time`。
- `活动终止时间`：`terminate_time/terminated_time/stop_time/close_time/cancel_time/abort_time` 等。
- `状态`：`state` 映射：
  - `3` -> `开启`
  - `4` -> `已结束`
  - `5` -> `已撤销`
  - `6` -> `已终止`

OpenCLI raw activity list 参考字段：

```text
request_url, queried_insert_start_time, queried_insert_end_time, queried_page_size,
queried_type_id, queried_time_zone, queried_system, total_count, total_pages,
page_num, activity_id, activity_name, activity_status, activity_type_id,
activity_type_name, site, country, creator, created_at, updated_at,
start_time, end_time, act_name, type_id, time_zone, main_site, store_code,
supplier_id, store_name, create_user, state, insert_time, create_error_code,
create_error_msg, ref_tools_id, main_product_range, tool_name,
last_operate_failed, is_tool_sale_attribute, activity_version, scene_type,
raw_json
```

OpenCLI raw activity good detail 参考字段：

```text
request_url, requested_activity_ids, activity_id, total_count, total_pages,
page_num, goods_id, skc, image_url, sku_supplier_no, attend_num_sum,
stock_num, ivt_num, inventory_num, goods_product_act_price,
goods_max_product_act_price, goods_is_effective, goods_failed_reason,
goods_state, goods_is_del, goods_currency, goods_supply_price_new,
goods_supply_price, goods_us_supply_price, goods_eur_supply_price,
goods_uk_supply_price, goods_mxn_supply_price, is_sale_attribute,
pricing_type, product_tag, insert_time, sku_count, sku, sku_currency,
sku_supply_price_new, sku_product_act_price, sku_max_product_act_price,
sku_supply_price, sku_us_supply_price, sku_eur_supply_price,
sku_uk_supply_price, sku_mxn_supply_price, sku_attr_info_list_json,
sku_main_attr_names, sku_sale_attr_names, goods_country_attr_info_list_json,
sku_info_list_json, raw_json
```

需要从 play-be API / 业务方确认：

- 最终目标 Sheet 是否仍只需要上述 11 列，还是要扩展商品/SKU 价格、库存、属性、活动 id、创建时间等字段。
- `活动商品skc` 一行应该是一活动一 SKC，还是一活动一 SKU；旧 detail task unique key 是 `activity_id + skc + sku`，play-be 最终 11 列会丢失 `sku`。
- `活动名称` 应优先使用 activity list 的 `activity_name`、`act_name` 还是 detail 里的名称字段。
- `活动规格` 是否只支持 `type_id=31/1/2/9/21`，其他 type 是否原样保留。
- `状态` 的 `state=3/4/5/6` 映射是否完整。
- `活动终止时间` 在 raw list 里未稳定出现时是否允许为空。
- 源站活动列表查询窗口是否应固定最近 6 个月，还是跟业务脚本的 crawl day 绑定。
- 缺失历史 `data_date` 时，是否允许用当前 SHEIN 活动状态补写过去 raw snapshot；若不允许，历史缺失日期应报错或只跳过。

## 验收标准

- 只新增/修改本 spec 中指定的后续实现文件；本轮 spec 任务只创建本文档。
- `opencli shein activity -f json` 在已登录 profile 下能返回 activity list 和 detail raw 行，且包含 `record_type`、`snapshot_date`、`activity_id`、`raw_json`。
- 业务脚本能用单店单 profile dry-run 输出 summary 和 sample ETL row。
- 业务脚本能按 store config 顺序处理 3 个店：
  - `store1/jegkb2wv`
  - `store2/m3cjm28a`
  - `store3/w2db43wa`
- 默认 skip 逻辑只看 raw DB `店铺 + 日期` 快照；目标业务 Sheet 行不能触发爬取 skip。
- crawl window 内逐日检查 raw DB，缺失日期逐日 OpenCLI 爬取并立即保存 raw DB。
- 支持 `--crawl-last-days 60`，爬取检查 60 天，写表只导出最新一天。
- 支持 `--sheet-url` 指定目标表，且 gid 正确决定 worksheet。
- 支持 `--skip-sheet-write` 只爬不写业务 Sheet。
- 目标 Sheet 写入使用 `update_data_keep_headers`，保留表头，从第 2 行写数据。
- 重跑同一 `店铺 + 日期` 时，如果 raw DB 已有快照，不启动 OpenCLI 爬虫并正常退出。
- 不产生本地 raw JSON 文件。
- 不引入硬编码 SHEIN 用户名、密码、Bearer token 或 webhook URL。

## 待确认问题

- 活动数据的业务“日期”到底是快照日期、活动创建日期、活动开始日期，还是源站查询窗口日期？
- 新业务脚本是否需要完全复刻旧 play-be 的“先活动列表、再商品详情”输出，还是要补上旧常量里存在但当前未使用的 marketing tool 数据？
- 生产目标 Sheet URL、raw DB URI、worksheet 名称是否已有固定值。
- 对历史缺失 raw snapshot 是否允许补爬当前状态，或必须只从已有 DB 快照 ETL。
- 活动列表接口默认沿用旧模板的最近 6 个月窗口；业务上是否需要改成 crawl day 当天仍需确认。
- 详情接口默认可参考旧模板并发 5；SHEIN 风控下是否需要降为串行、配置化延迟或 profile 级限流仍需 live benchmark 确认。
- 旧 ref-crawler 中店1清表、店2/店3追加的行为是否已废弃；本 spec 建议废弃，改为三店统一 merge。
