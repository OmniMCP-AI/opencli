# Issue: SHEIN 每日流量 08:00 定时任务不稳定

## 状态

- **Status:** Open
- **Severity:** High
- **Affected job:** `com.openclaw.shein-daily-traffic-sync`
- **Schedule:** 每天 08:00（Asia/Shanghai）
- **Observed window:** 2026-09-09 至 2026-09-15

## Summary

最近一周 7 次 08:00 定时任务中，只有 3 次完整成功；4 次未完整成功，其中 3 次整轮失败，1 次只完成部分店铺。

问题集中在 MaybeAI 外部接口连接不稳定。任务本身可以按时被 `launchd` 触发，但在读取原始 SHEIN 流量快照时，调用 MaybeAI `function_call` 接口出现 HTTP 503。由于 wrapper 使用串行执行和 `set -euo pipefail`，单个店铺失败会阻止后续店铺及公式重算。

## Recent evidence

| 日期 | 结果 | 失败或异常点 |
|---|---|---|
| 2026-09-09 | 整轮失败 | 店1读取原始快照时 `function_call` 返回 HTTP 503 |
| 2026-09-10 | 部分成功 | 店1、店2完成；店3读取原始快照时 HTTP 503 |
| 2026-09-11 | 完整成功 | MaybeAI 和 SHEIN 登录均发生重试，最终恢复 |
| 2026-09-12 | 整轮失败 | 店1读取原始快照时 `function_call` 返回 HTTP 503 |
| 2026-09-13 | 完整成功 | 有 MaybeAI 和 SHEIN 登录重试，最终恢复 |
| 2026-09-14 | 完整成功 | 有 MaybeAI、SHEIN 登录及写入重试，最终恢复 |
| 2026-09-15 | 08:00整轮失败；10:39手动成功 | 08:00 的 `function_call` 返回 HTTP 503；延后手动重跑成功 |

## Failing request

接口：

```text
POST https://a-play-be.maybeai.cn/api/v1/tool/function_call
```

请求头：

```text
Authorization: Bearer <MaybeAI token>
Content-Type: application/json
```

请求体：

```json
{
  "app": "function_call",
  "tool_id": "excel__read_recent_worksheet_snapshots",
  "tool_name": "read_recent_worksheet_snapshots",
  "tool_args": {
    "uri": "https://www.maybe.ai/docs/spreadsheets/d/6a6a2c410e55e966f026e1e5",
    "worksheet_name": "店1每日流量",
    "last_n_days": 60
  }
}
```

不同日期只改变 `worksheet_name`：`店1每日流量` 或 `店3每日流量`。没有日期范围、商品筛选或分页参数。

典型响应：

```text
HTTP 503
{"detail":"All connection attempts failed"}
```

2026-09-15 的最终响应为：

```text
HTTP 503
{"detail":"Server disconnected without sending a response."}
```

## Impact

- 任务不是漏触发，而是触发后在外部接口调用阶段失败。
- 失败发生在读取原始快照阶段，尚未开始当天 SHEIN 流量抓取。
- 任务按店铺串行执行，店1或店3失败会阻止后续流程。
- 失败时可能导致店铺数据未更新，且最后的 7 个工作表公式重算不会执行。
- 2026-09-15 延后到 10:39 手动重跑后，店1、店2、店3均成功，公式重算也完成，说明数据和凭据本身并非持续失效。

## Confirmed facts

1. `launchd` 配置的时间为每天 08:00，任务可以按时启动。
2. 最近一周的 503 均来自 MaybeAI `/api/v1/tool/function_call`。
3. MaybeAI 503 会在不同店铺、不同日期出现，不是固定某一个店铺参数导致。
4. 延迟重试或白天手动运行通常可以恢复。
5. SHEIN 登录状态偶尔需要刷新，但最近一周不是最终 503 的直接来源。

## Current retry behavior

- MaybeAI API 默认最多尝试 3 次，重试间隔 5 秒。
- 503 属于可重试状态，但当前重试窗口不足以覆盖早间服务或网络恢复时间。
- wrapper 未配置延迟补偿、定时补跑或失败告警。
- `set -euo pipefail` 使单店失败直接终止整轮任务。

## Suspected causes

- **Likely:** 08:00 附近本机网络、DNS、VPN 或系统唤醒后的连接尚未稳定。
- **Likely:** MaybeAI 后端在早间存在短时不可用或连接容量问题。
- **Possible:** `function_call` 读取最近 60 天数据的请求耗时较长，增加了服务端连接失败概率。
- **Not supported by recent evidence:** SHEIN 页面抓取本身是最近一周 503 的主要原因。

## Recommended fixes

1. 在 08:00 任务前增加网络/DNS/MaybeAI 健康检查，失败时延迟 5 到 15 分钟再启动业务流程。
2. 将 `function_call` 的重试改为指数退避，并增加总重试时长，而不只是固定 5 秒间隔。
3. 为任务增加失败后的自动补跑，例如 08:15、08:30、08:45，使用幂等逻辑避免重复写入。
4. 将每个店铺隔离执行并记录独立状态，单店失败不应阻止其他店铺和可安全执行的重算流程。
5. 评估是否能减少 60 天原始快照读取的单次请求规模，或改为分页/增量读取。
6. 增加告警，至少通知：任务启动失败、店铺失败、重算未执行、最终退出码非 0。
7. 继续记录请求耗时、MaybeAI 返回码、网络解析结果和重试序列，以区分本机网络问题与服务端问题。

## Acceptance criteria

- 连续观察至少 14 天，08:00 任务成功率达到 99% 或以上。
- MaybeAI 短暂 503 时，任务能自动延迟恢复，不需要人工 `launchctl kickstart`。
- 单个店铺失败不会静默阻止其他店铺；失败状态和补跑结果可追踪。
- 每次任务都能明确报告三店同步和公式重算是否完成。

## Evidence

- `/Users/youqiantu/.openclaw/shein-aftersales-sync/logs/daily-traffic.log`
- `docs/shein-daily-traffic-dns-failure-evidence.md`
- `docs/maybeai-daily-traffic-record-replace-timeout.md`
- `scripts/sync-shein-daily-traffic-to-sheet.py`
- `/Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist`
- `/Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh`
