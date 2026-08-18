import * as fs from 'node:fs';
import { CliError } from '@jackwener/opencli/errors';
import { cli, Strategy } from '@jackwener/opencli/registry';
import { getApp } from './catalog.js';
import { INPUT_ARGS, readJsonObjectInput } from '../maybeai/shared/options.js';

cli({
  site: 'maybeai-video-app',
  name: 'review',
  description: 'Review script, shot-image, shot-video, or concat outputs and list the key shot/task/url fields',
  strategy: Strategy.PUBLIC,
  browser: false,
  defaultFormat: 'json',
  args: [
    { name: 'app', positional: true, required: true, help: 'MaybeAI video app id, e.g. video-remake' },
    ...INPUT_ARGS,
    { name: 'raw-file', help: 'Optional raw output file; first JSON object will be extracted automatically' },
  ],
  func: async (_page, kwargs) => {
    const app = getApp(String(kwargs.app));
    const payload = readReviewPayload(kwargs);
    const stage = typeof payload.stage === 'string' ? payload.stage : 'unknown';

    return {
      app: app.id,
      title: app.title,
      stage,
      task_id: typeof payload.task_id === 'string' ? payload.task_id : null,
      summary: buildReviewSummary(payload),
    };
  },
});

function readReviewPayload(kwargs: Record<string, unknown>) {
  if (typeof kwargs['raw-file'] === 'string' && kwargs['raw-file'].trim()) {
    const raw = fs.readFileSync(kwargs['raw-file'], 'utf8');
    return extractFirstJsonObject(raw);
  }
  return readJsonObjectInput(kwargs);
}

function extractFirstJsonObject(text: string) {
  const start = text.indexOf('{');
  if (start < 0) throw new CliError('ARGUMENT', 'No JSON object found in raw output');
  let inString = false;
  let escaped = false;
  let depth = 0;
  let end = -1;
  for (let index = start; index < text.length; index += 1) {
    const ch = text[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === '{') {
      depth += 1;
      continue;
    }
    if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        end = index + 1;
        break;
      }
    }
  }
  if (end < 0) throw new CliError('ARGUMENT', 'Incomplete JSON object in raw output');
  return JSON.parse(text.slice(start, end)) as Record<string, unknown>;
}

export function buildReviewSummary(payload: Record<string, unknown>) {
  const stage = typeof payload.stage === 'string' ? payload.stage : 'unknown';
  switch (stage) {
    case 'script':
      return {
        shots_count: Array.isArray(payload.shots) ? payload.shots.length : payload.shots_count,
        shots: Array.isArray(payload.shot_summaries)
          ? payload.shot_summaries
          : Array.isArray(payload.shots)
            ? payload.shots.map(shot => ({
                shot_id: typeof shot === 'object' && shot && !Array.isArray(shot) ? (shot as Record<string, unknown>).shot_id : null,
                sequence: typeof shot === 'object' && shot && !Array.isArray(shot) ? (shot as Record<string, unknown>).sequence : null,
                duration_sec: typeof shot === 'object' && shot && !Array.isArray(shot) ? (shot as Record<string, unknown>).duration_sec : null,
              }))
            : [],
      };
    case 'main-image':
      return {
        task_id: payload.task_id,
        main_image_prompt: payload.main_image_prompt,
        image_url: payload.image_url ?? payload.main_image,
      };
    case 'shot-image':
      return {
        selected_shot_ids: payload.selected_shot_ids ?? [],
        items: Array.isArray(payload.items)
          ? payload.items.map(item => mapItemSummary(item, 'image_url'))
          : [],
      };
    case 'shot-video':
      return {
        selected_shot_ids: payload.selected_shot_ids ?? [],
        items: Array.isArray(payload.items)
          ? payload.items.map(item => mapItemSummary(item, 'video_url'))
          : [],
      };
    case 'concat':
      return {
        task_id: payload.task_id,
        final_video: payload.final_video ?? payload.video_url,
        video_urls: payload.video_urls ?? [],
      };
    default:
      return payload;
  }
}

function mapItemSummary(item: unknown, assetKey: 'image_url' | 'video_url') {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
  const row = item as Record<string, unknown>;
  return {
    task_id: row.task_id ?? null,
    shot_id: row.shot_id ?? null,
    sequence: row.sequence ?? null,
    prompt: row.prompt ?? null,
    [assetKey]: row[assetKey] ?? null,
  };
}
