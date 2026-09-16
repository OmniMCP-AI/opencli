# SHEIN 每日流量任务部署与 08:00 定时运行说明

本文记录当前生产任务的部署结构、首次安装方法、`launchd` 配置以及每天 08:00 的执行流程。

## 1. 任务组成

| 组件 | 当前路径 | 作用 |
|---|---|---|
| 同步脚本 | `scripts/sync-shein-daily-traffic-to-sheet.py` | 登录预检、读取原始快照、抓取 SHEIN、ETL 和写入 MaybeAI Base 表 |
| 店铺配置 | `scripts/shein-daily-traffic-prod.json` | 店铺、Browser Bridge profile 和原始表配置 |
| 公式重算脚本 | `scripts/recalculate_shein_daily_traffic_formulas.py` | 按固定顺序重算 7 个下游工作表 |
| launchd 配置 | `/Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist` | 每天 08:00 启动 wrapper |
| launchd wrapper | `/Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh` | 串行执行三个店铺，再执行公式重算 |
| 凭证目录 | `/Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets` | MaybeAI token 和 SHEIN 登录凭证 |
| 汇总日志 | `/Users/youqiantu/.openclaw/shein-aftersales-sync/logs/daily-traffic.log` | launchd stdout/stderr |
| 每日归档日志 | `artifacts/shein-daily-traffic/logs/YYYY-MM-DD.log` | 每次脚本运行的当天日志 |

当前 plist 和 wrapper 位于仓库外，迁移机器时必须单独复制；凭证不能提交到 Git。

## 2. 部署前置条件

- macOS 用户会话可运行 `launchd` LaunchAgent。
- Node.js >= 21.0.0。
- Python 3。
- Chrome 或 Chromium 已安装并保持目标 SHEIN 账号登录。
- Chrome 对应 profile 已安装并连接 OpenCLI Browser Bridge。
- 三个店铺各使用一个稳定的 Browser Bridge profile。
- 已准备 MaybeAI token 和 SHEIN 用户名/密码。
- 当前任务依赖的 MaybeAI Base 表和原始数据表已存在且账号有读写权限。

检查 OpenCLI 和 Browser Bridge：

```bash
node --version
python3 --version
opencli --version
opencli doctor
opencli profile list
```

如果 profile 还没有稳定别名，可先执行：

```bash
opencli profile rename <contextId> profile1
opencli profile rename <contextId> profile2
opencli profile rename <contextId> profile3
```

生产配置当前使用的 profile 是：

| 店铺 | 配置 key | profile | 原始 worksheet |
|---|---|---|---|
| 店1 | `store1` | `jegkb2wv` | `店1每日流量` |
| 店2 | `store2` | `m3cjm28a` | `店2每日流量` |
| 店3 | `store3` | `w2db43wa` | `店3每日流量` |

如果迁移到新机器，应在 `scripts/shein-daily-traffic-prod.json` 中替换为新机器上的 profile id 或别名。

## 3. 安装项目

从源码部署：

```bash
cd /Users/youqiantu/project/opencli
npm install
npm run build
npm link
```

确认 wrapper 依赖的命令可用：

```bash
cd /Users/youqiantu/project/opencli
npm exec -- opencli --profile jegkb2wv shein whoami -f json
```

如果使用已发布版本，也可以安装 OpenCLI：

```bash
npm install -g @jackwener/opencli
```

但定时任务仍需要仓库中的 Python 同步脚本、生产配置和外部 wrapper/plist。

## 4. 配置凭证

为每个店铺准备一个权限为 `600` 的 env 文件：

```text
/Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets/sync-shein-store1.env
/Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets/sync-shein-store2.env
/Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets/sync-shein.env
```

文件内容格式如下，真实值不要写入文档或提交仓库：

```dotenv
MAYBEAI_API_TOKEN=<MaybeAI token>
SHEIN_USERNAME=<SHEIN username>
SHEIN_PASSWORD=<SHEIN password>
```

创建目录并设置权限：

```bash
mkdir -p /Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets
chmod 700 /Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets
chmod 600 /Users/youqiantu/.openclaw/shein-aftersales-sync/.secrets/*.env
```

脚本也支持 `MAYBEAI_AUTH_TOKEN` 或 `MAYBEAI_API_KEY`，但生产文件当前使用 `MAYBEAI_API_TOKEN`。

## 5. 安装 launchd 任务

先准备运行目录：

```bash
mkdir -p /Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers
mkdir -p /Users/youqiantu/.openclaw/shein-aftersales-sync/logs
mkdir -p /Users/youqiantu/project/opencli/artifacts/shein-daily-traffic/logs
```

将生产 wrapper 放到以下位置，并确保可执行：

```bash
chmod 755 /Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh
```

wrapper 必须调用以下仓库文件：

```text
/Users/youqiantu/project/opencli/scripts/sync-shein-daily-traffic-to-sheet.py
/Users/youqiantu/project/opencli/scripts/recalculate_shein_daily_traffic_formulas.py
/Users/youqiantu/project/opencli/scripts/shein-daily-traffic-prod.json
```

plist 的关键配置如下：

```xml
<key>Label</key>
<string>com.openclaw.shein-daily-traffic-sync</string>

<key>ProgramArguments</key>
<array>
  <string>/bin/bash</string>
  <string>-lc</string>
  <string>/Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh</string>
</array>

<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key>
  <integer>8</integer>
  <key>Minute</key>
  <integer>0</integer>
</dict>

<key>RunAtLoad</key>
<false/>
<key>KeepAlive</key>
<false/>
```

完整 plist 当前位于：

```text
/Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist
```

检查 plist 后加载：

```bash
plutil -lint /Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist
launchctl bootstrap gui/$(id -u) \
  /Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist
```

如果任务已经加载，先卸载再重新加载：

```bash
launchctl bootout gui/$(id -u)/com.openclaw.shein-daily-traffic-sync 2>/dev/null || true
launchctl bootstrap gui/$(id -u) \
  /Users/youqiantu/Library/LaunchAgents/com.openclaw.shein-daily-traffic-sync.plist
```

## 6. 08:00 的执行链路

每天 08:00，`launchd` 执行：

```text
/bin/bash -lc /Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh
```

wrapper 使用 `set -euo pipefail`，按以下顺序执行：

1. 店1：加载 `sync-shein-store1.env`，使用 `store1`，并带 `--clear-worksheet-data`。
2. 店2：加载 `sync-shein-store2.env`，使用 `store2`。
3. 店3：加载 `sync-shein.env`，使用 `store3`。
4. 三店全部成功后，运行公式重算脚本。

每个店铺同步的关键参数：

```text
--store-config scripts/shein-daily-traffic-prod.json
--store-key store1|store2|store3
--sheet-url https://www.maybe.ai/docs/spreadsheets/d/69b91dd6bf42f58633fdc53b?gid=41
--crawl-last-days 30
--sheet-display-days 30
--etl-source raw-api
--request-timeout 120
--cli-timeout 3600
```

同步脚本默认取昨天的数据。`--crawl-last-days 30` 会检查最近 30 天的原始快照，只抓取原始表中缺失的日期；通常每天只抓取前一天。

单个店铺的主要阶段是：

```text
Step 1 解析 MaybeAI Base 目标并读取原始快照
Step 2 计算最近 30 天中需要抓取的日期
Step 3 调用 OpenCLI 抓取 SHEIN 流量，并保存原始快照
Step 4 确认原始数据保存完成
Step 5 ETL 映射
Step 6 替换当前店铺在 Base 表中的数据并校验
```

三店都完成后，公式脚本按顺序调用 MaybeAI 重算以下 7 个工作表：

```text
产品_SKU日事实表
产品_日趋势汇总表
产品_类目周期明细表
产品_生命周期周期汇总表
产品_预设周期汇总表
SKC区域运费当月
SKC当月点击加购率
```

## 7. 手动检查和补跑

查看任务状态：

```bash
launchctl print gui/$(id -u)/com.openclaw.shein-daily-traffic-sync
```

手动按生产入口补跑一次：

```bash
launchctl kickstart gui/$(id -u)/com.openclaw.shein-daily-traffic-sync
```

如果任务已在运行，先不要重复触发；确认状态为 `state = not running` 后再补跑。实时查看汇总日志：

```bash
tail -f /Users/youqiantu/.openclaw/shein-aftersales-sync/logs/daily-traffic.log
```

按日期查看归档日志：

```bash
tail -100 /Users/youqiantu/project/opencli/artifacts/shein-daily-traffic/logs/$(date +%Y-%m-%d).log
```

也可以直接运行 wrapper，但这会绕过 launchd，仍然会真实读写 SHEIN 和 MaybeAI：

```bash
/bin/bash /Users/youqiantu/.openclaw/shein-aftersales-sync/wrappers/run-daily-traffic.sh
```

## 8. 部署后验证

先运行无网络单元测试：

```bash
cd /Users/youqiantu/project/opencli
python3 scripts/sync-shein-daily-traffic-to-sheet.py --self-test
```

然后验证三个 profile 的登录状态：

```bash
npm exec -- opencli --profile jegkb2wv shein whoami -f json
npm exec -- opencli --profile m3cjm28a shein whoami -f json
npm exec -- opencli --profile w2db43wa shein whoami -f json
```

最后手动 kickstart，并确认日志依次出现：

```text
店1 Store completed
店2 Store completed
店3 Store completed
Step 7/7 completed: recalculated 7 worksheets in order.
```

任务完成时 `launchctl print` 应显示：

```text
state = not running
last exit code = 0
```

## 9. 失败行为和注意事项

- `launchd` 只负责按时启动，不负责业务重试和失败补跑。
- MaybeAI 的 429、500、502、503、504 会按脚本配置重试，默认 3 次、间隔 5 秒。
- SHEIN 抓取默认最多尝试 3 次，认证或网络失败时会尝试重新登录。
- wrapper 使用 `set -euo pipefail`；某个店铺失败会停止后续店铺和公式重算。
- 不要并行运行同一个 Browser Bridge profile 的多个 SHEIN 命令。
- 不要把 `.env`、token、密码或真实请求 payload 提交到仓库。
- 如果 08:00 失败，优先保留原始错误和时间戳，再使用 `launchctl kickstart` 补跑，不要直接删除日志。

相关稳定性问题见：[SHEIN 每日流量 08:00 定时任务不稳定](./issue-shein-daily-traffic-0800-instability.md)。
