import { cli, Strategy } from '@jackwener/opencli/registry';
import { INPUT_ARGS, WORKFLOW_ARGS, readJsonObjectInput } from '../maybeai/shared/options.js';
import { executeStage } from './engine.js';

const TOOL_CHAIN_ARGS = [
  { name: 'fastest-api-url', help: 'Fastest API URL for video script generation; defaults to MAYBEAI_FASTEST_API_URL or https://api.fastest.ai' },
  { name: 'organization-id', help: 'Optional organization id for Playground tool billing' },
  { name: 'generate-audio', help: 'Generate audio in shot videos when supported' },
  { name: 'shot-ids', help: 'Optional comma-separated shot ids to generate or rerun, e.g. S01_tracking_shot,S03_medium_full_shot' },
];

function applyRuntimeArgAliases(input: Record<string, unknown>, kwargs: Record<string, unknown>) {
  if (kwargs['generate-audio'] === undefined && typeof input.generate_audio === 'boolean') {
    kwargs['generate-audio'] = input.generate_audio;
  }
  if (input.shot_ids === undefined && typeof kwargs['shot-ids'] === 'string' && kwargs['shot-ids'].trim()) {
    input.shot_ids = kwargs['shot-ids'].split(',').map(item => item.trim()).filter(Boolean);
  }
}

cli({
  site: 'maybeai-video-app',
  name: 'stage',
  description: 'Run a single shell-aligned video-remake stage: script, main-image, shot-image, shot-video, or concat',
  strategy: Strategy.PUBLIC,
  browser: false,
  defaultFormat: 'json',
  args: [
    { name: 'app', positional: true, required: true, help: 'MaybeAI video app id; stage mode currently supports video-remake' },
    { name: 'stage', positional: true, required: true, help: 'Stage name: script, main-image, shot-image, shot-video, concat' },
    ...INPUT_ARGS,
    { name: 'task-id', help: 'Optional workflow task id for tracing or stage reruns' },
    { name: 'debug', help: 'Include stage debug details' },
    ...WORKFLOW_ARGS,
    ...TOOL_CHAIN_ARGS,
  ],
  func: async (_page, kwargs) => {
    const input = readJsonObjectInput(kwargs);
    applyRuntimeArgAliases(input, kwargs);
    return executeStage(String(kwargs.app), String(kwargs.stage), input, kwargs, !!kwargs.debug);
  },
});
