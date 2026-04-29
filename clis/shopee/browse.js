import { cli, Strategy } from '@jackwener/opencli/registry';
import { CommandExecutionError } from '@jackwener/opencli/errors';
import { simulateHumanBehavior, waitRandomDuration } from './shared.js';
import {
  DEFAULT_BROWSE_STEPS,
  DEFAULT_DURATION_MIN,
  DEFAULT_INSPECT_LIMIT,
  DEFAULT_SEARCH_TERMS,
  buildBrowseInspectScript,
  buildSeedSearchUrls,
  clampInt,
  normalizeBrowseInspectPayload,
  normalizeDwellRange,
  normalizeShopeeBrowseUrl,
  parseSearchTerms,
  pickBrowseCandidate,
} from './browse-shared.js';

const SHOPEE_BROWSE_TIMEOUT_SECONDS = 15 * 60;

function isActionLogEnabled(args) {
  if (args?.['action-log'] === true) return true;
  const raw = String(process.env.OPENCLI_ACTION_LOG ?? '').trim().toLowerCase();
  return raw === '1' || raw === 'true' || raw === 'yes' || raw === 'on';
}

function emitBrowseActionLog(enabled, action, fields = {}) {
  if (!enabled) return;
  const parts = [`action:${action}`];
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null || value === '') continue;
    const normalized = String(value).replace(/\s+/g, ' ').trim();
    if (!normalized) continue;
    parts.push(`${key}:${normalized}`);
  }
  process.stderr.write(`${parts.join(' ')}\n`);
}

async function inspectCurrentPage(page, currentUrl, inspectLimit) {
  const payload = await page.evaluate(buildBrowseInspectScript(inspectLimit));
  return normalizeBrowseInspectPayload(payload, currentUrl, inspectLimit);
}

function chooseNextTarget(payload, visitedUrls, seedQueue, allowSeedFallback = false) {
  const chosen = pickBrowseCandidate(payload, visitedUrls);
  if (chosen) return chosen;
  if (!allowSeedFallback || !['browse', 'search'].includes(payload?.pageType || '')) return null;
  while (seedQueue.length > 0) {
    const seed = seedQueue.shift();
    if (seed?.href && !visitedUrls.has(seed.href)) return seed;
  }
  return null;
}

export async function runBrowseSession(page, args, options = {}) {
  const nowFn = typeof options.nowFn === 'function' ? options.nowFn : () => Date.now();
  const mock = !!args.mock;
  const actionLog = isActionLogEnabled(args);
  const startUrl = normalizeShopeeBrowseUrl(args.url, { allowMock: mock });
  const steps = clampInt(args.steps, DEFAULT_BROWSE_STEPS, 1, 200);
  const durationMin = clampInt(args['duration-min'], DEFAULT_DURATION_MIN, 0, 180);
  const inspectLimit = clampInt(args['inspect-limit'], DEFAULT_INSPECT_LIMIT, 1, 50);
  const dwellRange = normalizeDwellRange(args['dwell-min-ms'], args['dwell-max-ms']);
  const searchTerms = parseSearchTerms(args['search-terms']);
  const seedQueue = buildSeedSearchUrls(startUrl, searchTerms);
  const allowSeedFallback = durationMin > 0;
  const visitedUrls = new Set();
  const rows = [];
  let currentUrl = startUrl;
  const deadlineAt = durationMin > 0 ? nowFn() + durationMin * 60 * 1000 : null;
  emitBrowseActionLog(actionLog, 'session_start', {
    url: startUrl,
    steps,
    duration_min: durationMin,
    inspect_limit: inspectLimit,
  });

  for (let step = 1; step <= steps; step += 1) {
    if (deadlineAt !== null && nowFn() >= deadlineAt) {
      emitBrowseActionLog(actionLog, 'session_stop', { reason: 'deadline_reached', step });
      break;
    }
    emitBrowseActionLog(actionLog, 'step_start', { step, url: currentUrl });
    emitBrowseActionLog(actionLog, 'navigate_start', { step, url: currentUrl });
    await page.goto(currentUrl, { waitUntil: 'load' });
    emitBrowseActionLog(actionLog, 'navigate_done', { step, url: currentUrl });
    if (typeof page.autoScroll === 'function') {
      emitBrowseActionLog(actionLog, 'autoscroll_start', { step });
      await page.autoScroll({ times: 1, delayMs: 700 }).catch(() => undefined);
      emitBrowseActionLog(actionLog, 'autoscroll_done', { step });
    }
    emitBrowseActionLog(actionLog, 'humanize_start', { step });
    await simulateHumanBehavior(page, {
      preWaitRangeMs: [160, 420],
      postWaitRangeMs: [120, 320],
      scrollRangePx: [120, 280],
    });
    emitBrowseActionLog(actionLog, 'humanize_done', { step });

    emitBrowseActionLog(actionLog, 'inspect_start', { step, limit: inspectLimit });
    const payload = await inspectCurrentPage(page, currentUrl, inspectLimit);
    if (payload.issue) {
      emitBrowseActionLog(actionLog, 'status', {
        value: 'not_ok',
        reason: payload.issue.code || 'page_issue',
      });
      emitBrowseActionLog(actionLog, 'inspect_error', {
        step,
        code: payload.issue.code,
        title: payload.issue.title,
      });
      const title = payload.issue.title || 'Shopee page reported a read error';
      const message = payload.issue.message || 'The current Shopee page returned a read error screen.';
      throw new CommandExecutionError(title, message);
    }
    emitBrowseActionLog(actionLog, 'inspect_done', {
      step,
      page_type: payload.pageType,
      candidates: payload.candidateCount,
    });
    emitBrowseActionLog(actionLog, 'status', { value: 'ok' });
    visitedUrls.add(payload.url);
    const chosen = chooseNextTarget(payload, visitedUrls, seedQueue, allowSeedFallback);
    emitBrowseActionLog(actionLog, 'select_done', {
      step,
      page_type: payload.pageType,
      selected_kind: chosen?.kind || 'none',
      selected_url: chosen?.href || '',
    });
    let dwellSeconds = 0;
    if (chosen) {
      emitBrowseActionLog(actionLog, 'dwell_start', { step });
      dwellSeconds = await waitRandomDuration(page, dwellRange);
      emitBrowseActionLog(actionLog, 'dwell_done', { step, seconds: dwellSeconds });
    }

    rows.push({
      step,
      page_type: payload.pageType,
      title: payload.title,
      visited_url: payload.url,
      candidate_count: payload.candidateCount,
      selected_kind: chosen?.kind || '',
      selected_url: chosen?.href || '',
      dwell_seconds: dwellSeconds,
    });

    if (!chosen) {
      emitBrowseActionLog(actionLog, 'session_stop', { reason: 'no_candidate', step });
      break;
    }
    if (deadlineAt !== null && nowFn() >= deadlineAt) {
      emitBrowseActionLog(actionLog, 'session_stop', { reason: 'deadline_reached', step });
      break;
    }
    currentUrl = chosen.href;
  }

  emitBrowseActionLog(actionLog, 'session_done', { rows: rows.length });
  return rows;
}

cli({
  site: 'shopee',
  name: 'browse',
  workspace: 'browser:shopee-browse-{pid}',
  description: 'Read-only Shopee browse rehearsal across search, product, and shop pages',
  domain: 'shopee.sg',
  strategy: Strategy.COOKIE,
  navigateBefore: false,
  timeoutSeconds: SHOPEE_BROWSE_TIMEOUT_SECONDS,
  args: [
    {
      name: 'url',
      positional: true,
      required: true,
      help: 'Starting Shopee page URL (search, product, or shop)',
    },
    {
      name: 'steps',
      type: 'int',
      default: DEFAULT_BROWSE_STEPS,
      help: 'Maximum navigation steps (default 3, max 200)',
    },
    {
      name: 'duration-min',
      type: 'int',
      default: DEFAULT_DURATION_MIN,
      help: 'Optional time budget in minutes for read-only browsing (default 0 = disabled)',
    },
    {
      name: 'inspect-limit',
      type: 'int',
      default: DEFAULT_INSPECT_LIMIT,
      help: 'Maximum candidate links to inspect per page (default 20, max 50)',
    },
    {
      name: 'dwell-min-ms',
      type: 'int',
      default: 3500,
      help: 'Minimum dwell time before the next hop in milliseconds (default 3500)',
    },
    {
      name: 'dwell-max-ms',
      type: 'int',
      default: 6500,
      help: 'Maximum dwell time before the next hop in milliseconds (default 6500)',
    },
    {
      name: 'search-terms',
      default: DEFAULT_SEARCH_TERMS.join(','),
      help: 'Comma-separated public search keywords used as fallback seeds, e.g. shoes,shirt',
    },
    {
      name: 'mock',
      type: 'bool',
      default: false,
      help: 'Allow localhost or .test hosts for local mock-site verification',
    },
    {
      name: 'action-log',
      type: 'bool',
      default: false,
      help: 'Emit one action log line per browse step to stderr',
    },
  ],
  columns: ['step', 'page_type', 'title', 'visited_url', 'candidate_count', 'selected_kind', 'selected_url', 'dwell_seconds'],
  func: runBrowseSession,
});

export const __test__ = {
  chooseNextTarget,
  inspectCurrentPage,
  runBrowseSession,
};
