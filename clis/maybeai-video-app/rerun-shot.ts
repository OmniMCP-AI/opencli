import { CliError } from '@jackwener/opencli/errors';
import { cli, Strategy } from '@jackwener/opencli/registry';
import { INPUT_ARGS, WORKFLOW_ARGS, readJsonObjectInput } from '../maybeai/shared/options.js';
import { executeStage } from './engine.js';

const TOOL_CHAIN_ARGS = [
  { name: 'fastest-api-url', help: 'Fastest API URL for video script generation; defaults to MAYBEAI_FASTEST_API_URL or https://api.fastest.ai' },
  { name: 'organization-id', help: 'Optional organization id for Playground tool billing' },
  { name: 'generate-audio', help: 'Generate audio in shot videos when supported' },
];

cli({
  site: 'maybeai-video-app',
  name: 'rerun-shot',
  description: 'Rerun one shot for shot-image or shot-video with optional prompt override and dedicated task_id',
  strategy: Strategy.PUBLIC,
  browser: false,
  defaultFormat: 'json',
  args: [
    { name: 'app', positional: true, required: true, help: 'MaybeAI video app id; currently rerun-shot is for video-remake' },
    { name: 'stage', positional: true, required: true, help: 'Stage name: shot-image or shot-video' },
    ...INPUT_ARGS,
    { name: 'shot-id', required: true, help: 'Single shot id to rerun, e.g. S01_tracking_shot' },
    { name: 'prompt', help: 'Optional prompt override for the selected shot' },
    { name: 'task-id', help: 'Optional dedicated task id for the selected shot rerun' },
    { name: 'debug', help: 'Include stage debug details' },
    ...WORKFLOW_ARGS,
    ...TOOL_CHAIN_ARGS,
  ],
  func: async (_page, kwargs) => {
    const stage = normalizeRerunStage(String(kwargs.stage));
    const shotId = String(kwargs['shot-id']);
    const input = buildRerunShotInput(readJsonObjectInput(kwargs), stage, shotId, kwargs);
    if (kwargs['generate-audio'] === undefined && typeof input.generate_audio === 'boolean') {
      kwargs['generate-audio'] = input.generate_audio;
    }
    return executeStage(String(kwargs.app), stage, input, kwargs, !!kwargs.debug);
  },
});

export type RerunStage = 'shot-image' | 'shot-video';

export function normalizeRerunStage(stage: string): RerunStage {
  const normalized = stage.trim().toLowerCase();
  if (normalized === 'shot-image' || normalized === 'shot-video') return normalized;
  throw new CliError('ARGUMENT', `Unsupported rerun-shot stage: ${stage}`, 'Supported stages: shot-image, shot-video');
}

export function buildRerunShotInput(
  input: Record<string, unknown>,
  stage: RerunStage,
  shotId: string,
  kwargs: Record<string, unknown>,
) {
  const nextInput: Record<string, unknown> = {
    ...input,
    shot_ids: [shotId],
  };
  const prompt = typeof kwargs.prompt === 'string' && kwargs.prompt.trim() ? kwargs.prompt.trim() : null;
  const taskId = typeof kwargs['task-id'] === 'string' && kwargs['task-id'].trim() ? kwargs['task-id'].trim() : null;

  if (stage === 'shot-image') {
    if (prompt) {
      nextInput.shot_image_prompt_overrides = {
        ...readRecord(input.shot_image_prompt_overrides),
        [shotId]: prompt,
      };
    }
    if (taskId) {
      nextInput.shot_image_task_ids = {
        ...readRecord(input.shot_image_task_ids),
        [shotId]: taskId,
      };
    }
    return nextInput;
  }

  if (prompt) {
    nextInput.shot_video_prompt_overrides = {
      ...readRecord(input.shot_video_prompt_overrides),
      [shotId]: prompt,
    };
  }
  if (taskId) {
    nextInput.shot_video_task_ids = {
      ...readRecord(input.shot_video_task_ids),
      [shotId]: taskId,
    };
  }
  return nextInput;
}

function readRecord(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}
