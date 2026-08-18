import { CliError } from '@jackwener/opencli/errors';
import { getApp } from './catalog.js';
import { resolveVideoAppInput } from './resolver.js';
import { getWorkflowProfile } from './workflow-profiles.js';
import { readWorkflowOptions } from '../maybeai/shared/options.js';
import { extractGeneratedVideos, filterWorkflowVariables, WorkflowClient } from '../maybeai/shared/workflow-client.js';
import { parseMCPImageUrl, parseMCPVideoUrl, readToolClientOptions, type MCPToolResult, type ScriptResult, type ScriptShot, ToolClient } from '../maybeai/shared/tool-client.js';

const IMAGE_TOOL_ID = 'maybe_image_generation__generate_image_from_images';
const IMAGE_CLARITY_UPSCALE_TOOL_ID = 'maybe_image_generation__generate_image_clarity_upscale';
const VIDEO_TOOL_ID = 'maybe_text2video_generation__generate_video_from_reference_image';
const CONCAT_VIDEO_TOOL_ID = 'audio_toolkit__concat_videos';
const MIN_VIDEO_REFERENCE_IMAGE_SIDE_PX = 400;
const VIDEO_REFERENCE_UPSCALE_FACTOR = 3;
const VIDEO_REFERENCE_UPSCALE_MODEL = 'fal-ai/seedvr/upscale/image';
const SUPPORTED_VIDEO_DURATIONS = [5, 10, 15, 20, 25, 30] as const;
const VIDEO_REMAKE_APP_ID = 'video-remake';

export type VideoRemakeStage = 'script' | 'main-image' | 'shot-image' | 'shot-video' | 'concat';

interface VideoRemakeStageContext {
  app: ReturnType<typeof getApp>;
  input: Record<string, unknown>;
  client: ToolClient;
  taskId: string;
  ratio: string;
  duration: number;
  productImages: string[];
  referenceImages: string[];
  referenceVideos: string[];
  generateAudio: boolean;
  engine: string;
}

interface VideoRemakeScriptStageResult {
  app: string;
  title: string;
  mode: 'tool-chain-stage';
  stage: 'script';
  task_id: string;
  script_result: ScriptResult;
  script: string;
  main_image_prompt: string;
  shots_count: number;
  shot_ids: string[];
  shot_summaries: Array<{
    shot_id: string;
    sequence?: string;
    duration_sec?: number;
  }>;
  shots: ScriptShot[];
  resolvedInput: Record<string, unknown>;
  debug?: Record<string, unknown>;
}

interface VideoRemakeMainImageStageResult {
  app: string;
  title: string;
  mode: 'tool-chain-stage';
  stage: 'main-image';
  task_id: string;
  main_image_prompt: string;
  main_image: string;
  image_url: string;
  resolvedInput: Record<string, unknown>;
  debug?: Record<string, unknown>;
}

interface VideoRemakeShotImageStageItem {
  task_id: string;
  shot_id: string;
  sequence?: string;
  shot: ScriptShot;
  prompt: string;
  image_url: string;
  source_reference?: string;
  raw?: MCPToolResult;
}

interface VideoRemakeShotImageStageResult {
  app: string;
  title: string;
  mode: 'tool-chain-stage';
  stage: 'shot-image';
  task_id: string;
  main_image_prompt: string;
  main_image?: string;
  selected_shot_ids: string[];
  items: VideoRemakeShotImageStageItem[];
  resolvedInput: Record<string, unknown>;
  debug?: Record<string, unknown>;
}

interface VideoRemakeShotVideoStageItem {
  task_id: string;
  shot_id: string;
  sequence?: string;
  shot: ScriptShot;
  prompt: string;
  image_url: string;
  prepared_image_url: string;
  requested_duration: number;
  video_url: string;
  raw?: MCPToolResult;
}

interface VideoRemakeShotVideoStageResult {
  app: string;
  title: string;
  mode: 'tool-chain-stage';
  stage: 'shot-video';
  task_id: string;
  main_image?: string;
  selected_shot_ids: string[];
  items: VideoRemakeShotVideoStageItem[];
  resolvedInput: Record<string, unknown>;
  debug?: Record<string, unknown>;
}

interface VideoRemakeConcatStageResult {
  app: string;
  title: string;
  mode: 'tool-chain-stage';
  stage: 'concat';
  task_id: string;
  video_url: string;
  final_video: string;
  video_urls: string[];
  resolvedInput: Record<string, unknown>;
  debug?: Record<string, unknown>;
}

export async function executeGenerate(appId: string, input: Record<string, unknown>, kwargs: Record<string, unknown>, debug = false) {
  const app = getApp(appId);
  const workflow = getWorkflowProfile(appId);
  const resolved = resolveVideoAppInput(appId, input);
  if (workflow.mode === 'tool-chain') {
    return executeVideoRemakeToolChain(appId, resolved.input, kwargs, debug);
  }
  const client = new WorkflowClient(readWorkflowOptions(kwargs));
  let debugData: Record<string, unknown> = {};
  let rawResults: unknown[];
  let storyboardRows: Record<string, unknown>[] = [];
  let clipRows: Record<string, unknown>[] = [];

  if (workflow.mode === 'direct') {
    ({ rawResults, debugData } = await runDirectWorkflow(client, app, workflow, resolved.variables, typeof kwargs['task-id'] === 'string' ? kwargs['task-id'] : undefined, debug));
  } else if (workflow.mode === 'three-step') {
    ({ rawResults, storyboardRows, clipRows, debugData } = await runThreeStepWorkflow(client, app, workflow, resolved, typeof kwargs['task-id'] === 'string' ? kwargs['task-id'] : undefined, debug));
  } else {
    throw new CliError('ARGUMENT', 'Unsupported workflow mode');
  }

  const videos = extractGeneratedVideos(rawResults, app.output.backendFields);
  const result: Record<string, unknown> = {
    app: app.id,
    title: app.title,
    mode: workflow.mode,
    videos,
    resolvedInput: resolved.input,
    modelProfile: resolved.modelProfile,
    warnings: resolved.warnings,
  };
  if (storyboardRows.length > 0) result.storyboard = storyboardRows;
  if (clipRows.length > 0) result.clips = clipRows;
  if (debug) {
    result.debug = {
      workflow,
      resolvedVariables: resolved.variables,
      outputFields: app.output.backendFields,
      ...debugData,
    };
  }
  if (videos.length === 0 && !debug) {
    throw new CliError('WORKFLOW_RUN', 'Workflow completed but no generated video URL was found', JSON.stringify(rawResults).slice(0, 1000));
  }
  if (videos.length === 0) result.warning = 'Workflow completed but no generated video URL was found';
  return result;
}

async function executeVideoRemakeToolChain(appId: string, input: Record<string, unknown>, kwargs: Record<string, unknown>, debug: boolean) {
  const context = createVideoRemakeStageContext(appId, input, kwargs);
  const { app, taskId } = context;
  const stepTaskIds = {
    run: taskId,
    script: taskId,
    main_image: taskId,
    shot_images: taskId,
    shot_videos: taskId,
    concat: taskId,
  };
  const debugData: Record<string, unknown> = {
    taskIds: stepTaskIds,
  };

  const scriptStage = await runVideoRemakeScriptStage(context, input, debug);
  const mainImageStage = await runVideoRemakeMainImageStage(context, {
    ...input,
    main_image_prompt: scriptStage.main_image_prompt,
  }, debug);
  const shotImageStage = await runVideoRemakeShotImageStage(context, {
    ...input,
    main_image_prompt: scriptStage.main_image_prompt,
    main_image: mainImageStage.main_image,
    shots: scriptStage.shots,
  }, debug);
  const shotVideoStage = await runVideoRemakeShotVideoStage(context, {
    ...input,
    main_image: mainImageStage.main_image,
    items: shotImageStage.items,
  }, debug);
  const concatStage = await runVideoRemakeConcatStage(context, {
    ...input,
    video_urls: shotVideoStage.items.map(item => item.video_url),
  }, debug);

  const result: Record<string, unknown> = {
    app: app.id,
    title: app.title,
    mode: 'tool-chain',
    task_id: taskId,
    task_ids: stepTaskIds,
    video_url: concatStage.video_url,
    final_video: concatStage.final_video,
    videos: [{ type: 'video', url: concatStage.video_url, raw: { shotVideos: concatStage.video_urls } }],
    mainImage: mainImageStage.main_image,
    script: scriptStage.script,
    shots: shotVideoStage.items.map(item => ({
      task_id: item.task_id,
      shot_id: item.shot_id,
      sequence: item.sequence,
      duration_sec: item.shot.duration_sec,
      prompt: item.prompt,
      requested_duration: item.requested_duration,
      image_url: item.image_url,
      prepared_image_url: item.prepared_image_url,
      video_url: item.video_url,
      source_reference: item.shot.technical_specs?.consistency_anchor,
      shot: item.shot,
    })),
    resolvedInput: input,
    warnings: [],
  };
  if (debug) {
    debugData.script = scriptStage.debug;
    debugData.mainImage = mainImageStage.debug;
    debugData.shots = {
      images: shotImageStage.debug,
      videos: shotVideoStage.debug,
    };
    debugData.concat = concatStage.debug;
    result.debug = debugData;
  }
  return result;
}

export async function executeStage(appId: string, stage: string, input: Record<string, unknown>, kwargs: Record<string, unknown>, debug = false) {
  if (appId !== VIDEO_REMAKE_APP_ID) {
    throw new CliError('ARGUMENT', `Stage execution is currently supported only for ${VIDEO_REMAKE_APP_ID}`, `Received app: ${appId}`);
  }
  const normalizedStage = normalizeVideoRemakeStage(stage);
  return executeVideoRemakeStage(normalizedStage, input, kwargs, debug);
}

export function resolveRequestedShotIds(rawInput: Record<string, unknown>, kwargs: Record<string, unknown>) {
  const direct = readOptionalStageStrings(rawInput, ['shot_ids', 'shotIds']);
  if (direct.length > 0) return uniqueShotIds(direct);
  const rawKwarg = typeof kwargs['shot-ids'] === 'string' ? kwargs['shot-ids'] : '';
  if (!rawKwarg.trim()) return [];
  return uniqueShotIds(rawKwarg.split(',').map(item => item.trim()).filter(Boolean));
}

function resolvePromptOverrideMap(rawInput: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = rawInput[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return Object.fromEntries(
        Object.entries(value as Record<string, unknown>)
          .filter(([, mapValue]) => typeof mapValue === 'string' && mapValue.trim())
          .map(([mapKey, mapValue]) => [mapKey, String(mapValue).trim()]),
      ) as Record<string, string>;
    }
  }
  return {} as Record<string, string>;
}

export function pickVideoRemakeResolvableInput(rawInput: Record<string, unknown>) {
  const allowed = [
    'reference_video',
    'product',
    'person',
    'market',
    'platform',
    'category',
    'duration',
    'ratio',
    'prompt',
    'engine',
    'generate_audio',
    'model',
    'llmModel',
    'userDescription',
    'aspectRatio',
    'generateAudio',
    'productImage',
    'product_image',
    'product_images',
    'productImages',
    'products',
    'referenceImage',
    'reference_image',
    'reference_images',
    'referenceImages',
    'referenceVideo',
    'reference_video_url',
    'reference_videos',
    'referenceVideos',
  ] as const;
  return Object.fromEntries(
    Object.entries(rawInput).filter(([key]) => allowed.includes(key as typeof allowed[number])),
  );
}

async function executeVideoRemakeStage(stage: VideoRemakeStage, input: Record<string, unknown>, kwargs: Record<string, unknown>, debug: boolean) {
  const context = createVideoRemakeStageContext(VIDEO_REMAKE_APP_ID, input, kwargs);
  switch (stage) {
    case 'script':
      return runVideoRemakeScriptStage(context, input, debug);
    case 'main-image':
      return runVideoRemakeMainImageStage(context, input, debug);
    case 'shot-image':
      return runVideoRemakeShotImageStage(context, input, debug);
    case 'shot-video':
      return runVideoRemakeShotVideoStage(context, input, debug);
    case 'concat':
      return runVideoRemakeConcatStage(context, input, debug);
  }
}

function createVideoRemakeStageContext(appId: string, rawInput: Record<string, unknown>, kwargs: Record<string, unknown>): VideoRemakeStageContext {
  const app = getApp(appId);
  const resolved = resolveVideoAppInput(appId, pickVideoRemakeResolvableInput(rawInput));
  const taskId = resolveStageTaskId(rawInput, kwargs);
  const input = resolved.input;

  return {
    app,
    input,
    client: new ToolClient(readToolClientOptions(kwargs, 'video-analysis-and-replication')),
    taskId,
    ratio: String(input.ratio ?? '9:16'),
    duration: resolveToolChainDuration(input.duration),
    productImages: [String(input.product ?? '')].filter(Boolean),
    referenceImages: typeof input.person === 'string' && input.person ? [input.person] : [],
    referenceVideos: [String(input.reference_video ?? '')].filter(Boolean),
    generateAudio: resolveStageGenerateAudio(rawInput, kwargs),
    engine: typeof input.engine === 'string' && input.engine ? input.engine : String(input.engine ?? ''),
  };
}

async function runVideoRemakeScriptStage(
  context: VideoRemakeStageContext,
  rawInput: Record<string, unknown>,
  debug: boolean,
): Promise<VideoRemakeScriptStageResult> {
  if (context.referenceVideos.length !== 1) {
    throw new CliError('ARGUMENT', 'video-remake script stage requires exactly one reference_video', 'Pass one reference_video in input JSON.');
  }

  const userInput = buildScriptGenerationUserInput(String(context.input.prompt ?? ''), context.ratio, context.referenceImages.length > 0, 'copy');
  const script = await context.client.generateVideoScript({
    taskId: context.taskId,
    productImages: context.productImages,
    referenceImages: context.referenceImages,
    referenceVideos: context.referenceVideos,
    userInput,
    seconds: context.duration,
    mode: 'copy',
  });
  if (script.shots.length === 0) {
    throw new CliError('WORKFLOW_RUN', 'Video script API returned no shots', JSON.stringify(script).slice(0, 1000));
  }

  return {
    app: context.app.id,
    title: context.app.title,
    mode: 'tool-chain-stage',
    stage: 'script',
    task_id: context.taskId,
    script_result: script,
    script: script.script,
    main_image_prompt: script.main_image_prompt,
    shots_count: script.shots.length,
    shot_ids: script.shots.map(shot => shot.shot_id),
    shot_summaries: script.shots.map(shot => ({
      shot_id: shot.shot_id,
      sequence: shot.sequence,
      duration_sec: shot.duration_sec,
    })),
    shots: script.shots,
    resolvedInput: context.input,
    ...(debug
      ? {
          debug: {
            request: {
              endpoint: '/v1/tool/video/generate',
              task_id: context.taskId,
              product_images: context.referenceImages.length > 0 ? [...context.productImages, ...context.referenceImages] : context.productImages,
              reference_videos: context.referenceVideos,
              seconds: context.duration,
              mode: 'copy',
              user_input: userInput,
            },
            response: script,
          },
        }
      : {}),
  };
}

async function runVideoRemakeMainImageStage(
  context: VideoRemakeStageContext,
  rawInput: Record<string, unknown>,
  debug: boolean,
): Promise<VideoRemakeMainImageStageResult> {
  const mainImagePrompt = resolveMainImagePrompt(rawInput);
  const toolArgs = {
    prompt: context.referenceImages.length > 0
      ? buildMainImagePromptWithModel(mainImagePrompt, context.ratio)
      : buildMainImagePromptWithoutModel(mainImagePrompt, context.ratio),
    image_urls: [...context.productImages, ...context.referenceImages],
    aspect_ratio: context.ratio,
  };
  const result = await context.client.callMcpTool(context.taskId, IMAGE_TOOL_ID, toolArgs);
  const mainImage = parseMCPImageUrl(result);

  return {
    app: context.app.id,
    title: context.app.title,
    mode: 'tool-chain-stage',
    stage: 'main-image',
    task_id: context.taskId,
    main_image_prompt: mainImagePrompt,
    main_image: mainImage,
    image_url: mainImage,
    resolvedInput: context.input,
    ...(debug
      ? {
          debug: {
            tool_id: IMAGE_TOOL_ID,
            tool_args: toolArgs,
            response: result,
          },
        }
      : {}),
  };
}

async function runVideoRemakeShotImageStage(
  context: VideoRemakeStageContext,
  rawInput: Record<string, unknown>,
  debug: boolean,
): Promise<VideoRemakeShotImageStageResult> {
  const mainImagePrompt = resolveMainImagePrompt(rawInput);
  const mainImage = readOptionalStageString(rawInput, ['main_image', 'mainImage']);
  const requestedShotIds = resolveRequestedShotIds(rawInput, {});
  const shots = filterScriptShotsByRequestedIds(collectStageShots(rawInput), requestedShotIds);
  const hasModelReference = context.referenceImages.length > 0;
  const baseReferenceImages = mainImage
    ? [...context.productImages, mainImage]
    : hasModelReference
      ? [...context.productImages, ...context.referenceImages]
      : context.productImages;

  const items: VideoRemakeShotImageStageItem[] = [];
  const debugItems: Array<Record<string, unknown>> = [];
  for (const shot of shots) {
    const hasStoryboardReference = isRemoteUrl(shot.technical_specs?.consistency_anchor);
    const shotTaskId = resolveShotTaskId(rawInput, shot.shot_id, 'shot-image');
    const prompt = resolveShotImagePrompt(rawInput, shot, mainImagePrompt, context.ratio, hasModelReference, hasStoryboardReference);
    const toolArgs = {
      prompt,
      image_urls: buildReferenceUrls(baseReferenceImages, shot.technical_specs?.consistency_anchor),
      aspect_ratio: context.ratio,
    };
    let result: MCPToolResult;
    try {
      result = await context.client.callMcpTool(shotTaskId, IMAGE_TOOL_ID, toolArgs);
    } catch (error) {
      throw enrichStageShotError(error, 'shot-image', shot.shot_id, shotTaskId);
    }
    const imageUrl = parseMCPImageUrl(result);
    items.push({
      task_id: shotTaskId,
      shot_id: shot.shot_id,
      sequence: shot.sequence,
      shot,
      prompt,
      image_url: imageUrl,
      source_reference: shot.technical_specs?.consistency_anchor,
      ...(debug ? { raw: result } : {}),
    });
    if (debug) debugItems.push({ shot_id: shot.shot_id, task_id: shotTaskId, tool_id: IMAGE_TOOL_ID, tool_args: toolArgs, response: result });
  }

  return {
    app: context.app.id,
    title: context.app.title,
    mode: 'tool-chain-stage',
    stage: 'shot-image',
    task_id: context.taskId,
    main_image_prompt: mainImagePrompt,
    ...(mainImage ? { main_image: mainImage } : {}),
    selected_shot_ids: items.map(item => item.shot_id),
    items,
    resolvedInput: context.input,
    ...(debug ? { debug: { items: debugItems } } : {}),
    ...(items.length === 1
      ? {
          item_task_id: items[0]!.task_id,
          shot_id: items[0]!.shot_id,
          shot: items[0]!.shot,
          prompt: items[0]!.prompt,
          image_url: items[0]!.image_url,
        }
      : {}),
  };
}

async function runVideoRemakeShotVideoStage(
  context: VideoRemakeStageContext,
  rawInput: Record<string, unknown>,
  debug: boolean,
): Promise<VideoRemakeShotVideoStageResult> {
  const mainImage = readOptionalStageString(rawInput, ['main_image', 'mainImage']);
  const requestedShotIds = resolveRequestedShotIds(rawInput, {});
  const items = filterShotVideoStageItemsByRequestedIds(collectShotVideoStageItems(rawInput), requestedShotIds);
  const stageItems: VideoRemakeShotVideoStageItem[] = [];
  const debugItems: Array<Record<string, unknown>> = [];

  for (const item of items) {
    const shotTaskId = resolveShotVideoItemTaskId(item, rawInput);
    const prompt = resolveShotVideoPrompt(rawInput, item.shot, item, context.ratio);
    const preparedImageUrl = await prepareVideoReferenceImageUrl(context.client, shotTaskId, item.image_url);
    const toolArgs = {
      model: context.engine,
      prompt,
      image_urls: [preparedImageUrl],
      aspect_ratio: context.ratio,
      duration: context.duration,
      generate_audio: context.generateAudio,
      elements: buildVideoElements(context.productImages, mainImage ?? ''),
    };
    let result: MCPToolResult;
    try {
      result = await context.client.callMcpTool(shotTaskId, VIDEO_TOOL_ID, toolArgs);
    } catch (error) {
      throw enrichStageShotError(error, 'shot-video', item.shot.shot_id, shotTaskId);
    }
    const videoUrl = parseMCPVideoUrl(result);
    stageItems.push({
      task_id: shotTaskId,
      shot_id: item.shot.shot_id,
      sequence: item.shot.sequence,
      shot: item.shot,
      prompt,
      image_url: item.image_url,
      prepared_image_url: preparedImageUrl,
      requested_duration: context.duration,
      video_url: videoUrl,
      ...(debug ? { raw: result } : {}),
    });
    if (debug) debugItems.push({ shot_id: item.shot.shot_id, task_id: shotTaskId, tool_id: VIDEO_TOOL_ID, tool_args: toolArgs, response: result });
  }

  return {
    app: context.app.id,
    title: context.app.title,
    mode: 'tool-chain-stage',
    stage: 'shot-video',
    task_id: context.taskId,
    ...(mainImage ? { main_image: mainImage } : {}),
    selected_shot_ids: stageItems.map(item => item.shot_id),
    items: stageItems,
    resolvedInput: context.input,
    ...(debug ? { debug: { items: debugItems } } : {}),
    ...(stageItems.length === 1
      ? {
          item_task_id: stageItems[0]!.task_id,
          shot_id: stageItems[0]!.shot_id,
          shot: stageItems[0]!.shot,
          prompt: stageItems[0]!.prompt,
          image_url: stageItems[0]!.image_url,
          prepared_image_url: stageItems[0]!.prepared_image_url,
          requested_duration: stageItems[0]!.requested_duration,
          video_url: stageItems[0]!.video_url,
        }
      : {}),
  };
}

async function runVideoRemakeConcatStage(
  context: VideoRemakeStageContext,
  rawInput: Record<string, unknown>,
  debug: boolean,
): Promise<VideoRemakeConcatStageResult> {
  const videoUrls = collectConcatVideoUrls(rawInput);
  if (videoUrls.length === 0) {
    throw new CliError('ARGUMENT', 'concat stage requires at least one video url', 'Pass video_urls or items[].video_url.');
  }

  let finalVideo = videoUrls[0]!;
  let result: MCPToolResult | undefined;
  if (videoUrls.length > 1) {
    const toolArgs = {
      video_urls: videoUrls,
      output_format: 'mp4',
      aspect_ratio: context.ratio,
      speed_preset: 'faster',
      quality_crf: 23,
    };
    result = await context.client.callMcpTool(context.taskId, CONCAT_VIDEO_TOOL_ID, toolArgs);
    finalVideo = parseMCPVideoUrl(result);
  }

  return {
    app: context.app.id,
    title: context.app.title,
    mode: 'tool-chain-stage',
    stage: 'concat',
    task_id: context.taskId,
    video_url: finalVideo,
    final_video: finalVideo,
    video_urls: videoUrls,
    resolvedInput: context.input,
    ...(debug
      ? {
          debug: {
            tool_id: videoUrls.length > 1 ? CONCAT_VIDEO_TOOL_ID : null,
            response: result ?? null,
          },
        }
      : {}),
  };
}

function normalizeVideoRemakeStage(stage: string): VideoRemakeStage {
  const normalized = stage.trim().toLowerCase().replace(/_/g, '-');
  switch (normalized) {
    case 'script':
    case 'main-image':
    case 'shot-image':
    case 'shot-video':
    case 'concat':
      return normalized;
    default:
      throw new CliError('ARGUMENT', `Unsupported video-remake stage: ${stage}`, 'Supported stages: script, main-image, shot-image, shot-video, concat');
  }
}

function resolveStageTaskId(rawInput: Record<string, unknown>, kwargs: Record<string, unknown>) {
  const explicitKwarg = typeof kwargs['task-id'] === 'string' && kwargs['task-id'].trim() ? kwargs['task-id'].trim() : null;
  if (explicitKwarg) return explicitKwarg;
  const rawTaskId = readOptionalStageString(rawInput, ['task_id', 'taskId']);
  return rawTaskId || crypto.randomUUID();
}

function resolveStageGenerateAudio(rawInput: Record<string, unknown>, kwargs: Record<string, unknown>) {
  if (typeof kwargs['generate-audio'] === 'boolean') return kwargs['generate-audio'];
  if (typeof rawInput.generate_audio === 'boolean') return rawInput.generate_audio;
  if (typeof rawInput.generateAudio === 'boolean') return rawInput.generateAudio;
  return false;
}

function resolveMainImagePrompt(rawInput: Record<string, unknown>) {
  const direct = readOptionalStageString(rawInput, ['main_image_prompt', 'mainImagePrompt']);
  if (direct) return direct;
  const scriptResult = readOptionalStageRecord(rawInput, ['script_result', 'scriptResult']);
  const fromScript = scriptResult ? readOptionalStageString(scriptResult, ['main_image_prompt', 'mainImagePrompt']) : null;
  if (fromScript) return fromScript;
  throw new CliError('ARGUMENT', 'Missing main_image_prompt for stage execution', 'Pass main_image_prompt or script_result.main_image_prompt in input JSON.');
}

function collectStageShots(rawInput: Record<string, unknown>) {
  const directShot = readOptionalStageRecord(rawInput, ['shot']);
  if (directShot) return [toScriptShot(directShot)];

  const directShots = readOptionalStageRecords(rawInput, ['shots']);
  if (directShots.length > 0) return directShots.map(toScriptShot);

  const scriptResult = readOptionalStageRecord(rawInput, ['script_result', 'scriptResult']);
  const nestedShots = scriptResult ? readOptionalStageRecords(scriptResult, ['shots']) : [];
  if (nestedShots.length > 0) return nestedShots.map(toScriptShot);

  throw new CliError('ARGUMENT', 'Missing shot data for stage execution', 'Pass shot, shots, or script_result.shots in input JSON.');
}

function filterScriptShotsByRequestedIds(shots: ScriptShot[], requestedShotIds: string[]) {
  if (requestedShotIds.length === 0) return shots;
  const selected = shots.filter(shot => requestedShotIds.includes(shot.shot_id));
  if (selected.length === 0) {
    throw new CliError('ARGUMENT', 'Requested shot_ids did not match any shots', `Requested: ${requestedShotIds.join(', ')}`);
  }
  ensureAllRequestedShotIdsMatched(requestedShotIds, selected.map(shot => shot.shot_id));
  return selected;
}

function collectShotVideoStageItems(rawInput: Record<string, unknown>) {
  const directItems = readOptionalStageRecords(rawInput, ['items', 'results']);
  if (directItems.length > 0) {
    return directItems.map(item => ({
      shot: toScriptShot(readRequiredStageRecord(item, ['shot'])),
      image_url: readRequiredStageString(item, ['image_url', 'imageUrl', 'url']),
      task_id: readOptionalStageString(item, ['task_id', 'taskId']) ?? undefined,
      prompt: readOptionalStageString(item, ['video_prompt', 'videoPrompt', 'prompt']) ?? undefined,
    }));
  }

  const directShot = readOptionalStageRecord(rawInput, ['shot']);
  const directImageUrl = readOptionalStageString(rawInput, ['image_url', 'imageUrl', 'url']);
  const directTaskId = readOptionalStageString(rawInput, ['task_id', 'taskId']);
  const directPrompt = readOptionalStageString(rawInput, ['video_prompt', 'videoPrompt', 'prompt']);
  if (directShot && directImageUrl) {
    return [{ shot: toScriptShot(directShot), image_url: directImageUrl, ...(directTaskId ? { task_id: directTaskId } : {}), ...(directPrompt ? { prompt: directPrompt } : {}) }];
  }

  const shots = readOptionalStageRecords(rawInput, ['shots']);
  const imageUrls = readOptionalStageStrings(rawInput, ['image_urls', 'imageUrls']);
  if (shots.length > 0 && imageUrls.length > 0) {
    if (shots.length !== imageUrls.length) {
      throw new CliError('ARGUMENT', 'shots and image_urls length mismatch', `Received shots=${shots.length}, image_urls=${imageUrls.length}`);
    }
    return shots.map((shot, index) => ({
      shot: toScriptShot(shot),
      image_url: imageUrls[index]!,
      task_id: readOptionalStageString(shot, ['task_id', 'taskId']) ?? undefined,
      prompt: readOptionalStageString(shot, ['video_prompt', 'videoPrompt', 'prompt']) ?? undefined,
    }));
  }

  throw new CliError('ARGUMENT', 'Missing shot-video stage items', 'Pass items[{shot,image_url}] or shot + image_url in input JSON.');
}

function filterShotVideoStageItemsByRequestedIds(
  items: Array<{ shot: ScriptShot; image_url: string; task_id?: string; prompt?: string }>,
  requestedShotIds: string[],
) {
  if (requestedShotIds.length === 0) return items;
  const selected = items.filter(item => requestedShotIds.includes(item.shot.shot_id));
  if (selected.length === 0) {
    throw new CliError('ARGUMENT', 'Requested shot_ids did not match any shot-video items', `Requested: ${requestedShotIds.join(', ')}`);
  }
  ensureAllRequestedShotIdsMatched(requestedShotIds, selected.map(item => item.shot.shot_id));
  return selected;
}

function collectConcatVideoUrls(rawInput: Record<string, unknown>) {
  const directUrls = readOptionalStageStrings(rawInput, ['video_urls', 'videoUrls', 'shot_videos', 'shotVideos']);
  if (directUrls.length > 0) return directUrls;

  const items = readOptionalStageRecords(rawInput, ['items', 'results']);
  const itemUrls = items.map(item => readOptionalStageString(item, ['video_url', 'videoUrl', 'url'])).filter((value): value is string => Boolean(value));
  if (itemUrls.length > 0) return itemUrls;

  const shots = readOptionalStageRecords(rawInput, ['shots']);
  const shotUrls = shots.map(shot => readOptionalStageString(shot, ['video_url', 'videoUrl'])).filter((value): value is string => Boolean(value));
  if (shotUrls.length > 0) return shotUrls;

  return [];
}

function toScriptShot(value: Record<string, unknown>) {
  return value as unknown as ScriptShot;
}

function readOptionalStageRecord(rawInput: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = rawInput[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  }
  return null;
}

function readRequiredStageRecord(rawInput: Record<string, unknown>, keys: string[]) {
  const record = readOptionalStageRecord(rawInput, keys);
  if (record) return record;
  throw new CliError('ARGUMENT', `Missing required object field: ${keys[0]}`, `Checked keys: ${keys.join(', ')}`);
}

function readOptionalStageRecords(rawInput: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = rawInput[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item));
    }
  }
  return [];
}

function readOptionalStageString(rawInput: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = rawInput[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function readRequiredStageString(rawInput: Record<string, unknown>, keys: string[]) {
  const value = readOptionalStageString(rawInput, keys);
  if (value) return value;
  throw new CliError('ARGUMENT', `Missing required string field: ${keys[0]}`, `Checked keys: ${keys.join(', ')}`);
}

function readOptionalStageStrings(rawInput: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = rawInput[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is string => typeof item === 'string' && !!item.trim()).map(item => item.trim());
    }
  }
  return [];
}

function uniqueShotIds(shotIds: string[]) {
  return [...new Set(shotIds.map(shotId => shotId.trim()).filter(Boolean))];
}

function ensureAllRequestedShotIdsMatched(requestedShotIds: string[], matchedShotIds: string[]) {
  const missing = requestedShotIds.filter(shotId => !matchedShotIds.includes(shotId));
  if (missing.length > 0) {
    throw new CliError('ARGUMENT', 'Some requested shot_ids were not found', `Missing: ${missing.join(', ')}`);
  }
}

async function runDirectWorkflow(
  client: WorkflowClient,
  app: ReturnType<typeof getApp>,
  workflow: ReturnType<typeof getWorkflowProfile>,
  variables: Array<{ name: string; default_value: unknown }>,
  taskId: string | undefined,
  debug: boolean,
) {
  let debugData: Record<string, unknown> = {};
  const effectiveTaskId = taskId || crypto.randomUUID();
  if (debug && workflow.mode === 'direct') {
    const workflowDetail = await client.fetchWorkflowDetail(workflow.artifactId);
    debugData = {
      taskIds: {
        workflow: effectiveTaskId,
      },
      request: {
        taskId: effectiveTaskId,
        artifactId: workflow.artifactId,
        workflowId: workflowDetail.id,
        variablesBeforeFilter: variables,
        variablesAfterFilter: filterWorkflowVariables(workflowDetail, variables),
        service: workflow.service,
      },
    };
  }
  if (workflow.mode !== 'direct') throw new CliError('ARGUMENT', `Expected direct workflow mode, got ${workflow.mode}`);
  const rawResults = await client.run({
    artifactId: workflow.artifactId,
    variables,
    appId: app.id,
    title: app.title,
    taskId: effectiveTaskId,
    service: workflow.service,
  });
  if (debug) debugData.rawResults = rawResults;
  return { rawResults, debugData };
}

async function runThreeStepWorkflow(
  client: WorkflowClient,
  app: ReturnType<typeof getApp>,
  workflow: ReturnType<typeof getWorkflowProfile>,
  resolved: ReturnType<typeof resolveVideoAppInput>,
  taskId: string | undefined,
  debug: boolean,
) {
  if (workflow.mode !== 'three-step') throw new CliError('ARGUMENT', `Expected three-step workflow mode, got ${workflow.mode}`);
  const storyboardTaskId = crypto.randomUUID();
  const clipTaskId = crypto.randomUUID();
  const finalTaskId = taskId || crypto.randomUUID();
  const debugData: Record<string, any> = {};
  debugData.taskIds = {
    storyboard: storyboardTaskId,
    clips: clipTaskId,
    concat: finalTaskId,
  };

  if (debug) {
    const storyboardDetail = await client.fetchWorkflowDetail(workflow.storyboardArtifactId);
    debugData.storyboardStep = {
      request: {
        taskId: storyboardTaskId,
        artifactId: workflow.storyboardArtifactId,
        workflowId: storyboardDetail.id,
        variablesBeforeFilter: resolved.variables,
        variablesAfterFilter: filterWorkflowVariables(storyboardDetail, resolved.variables),
        service: workflow.service,
      },
    };
  }

  const storyboardResults = await client.run({
    artifactId: workflow.storyboardArtifactId,
    variables: resolved.variables,
    appId: app.id,
    title: `${app.title} storyboard`,
    taskId: storyboardTaskId,
    service: workflow.service,
  });
  const storyboardRows = toRecordRows(storyboardResults);
  if (storyboardRows.length === 0) throw new CliError('WORKFLOW_RUN', 'Storyboard workflow returned no structured shot rows', JSON.stringify(storyboardResults).slice(0, 1000));

  const clipVariables = buildClipStepVariables(app.id, storyboardRows, resolved.input);
  if (debug) {
    const clipDetail = await client.fetchWorkflowDetail(workflow.clipArtifactId);
    debugData.storyboardStep.rawResults = storyboardRows;
    debugData.clipStep = {
      request: {
        taskId: clipTaskId,
        prevTaskId: storyboardTaskId,
        artifactId: workflow.clipArtifactId,
        workflowId: clipDetail.id,
        variablesBeforeFilter: clipVariables,
        variablesAfterFilter: filterWorkflowVariables(clipDetail, clipVariables),
        service: workflow.service,
      },
    };
  }

  const clipResults = await client.run({
    artifactId: workflow.clipArtifactId,
    variables: clipVariables,
    appId: app.id,
    title: `${app.title} clips`,
    taskId: clipTaskId,
    prevTaskId: storyboardTaskId,
    service: workflow.service,
  });
  const clipRows = toRecordRows(clipResults);
  if (clipRows.length === 0) throw new CliError('WORKFLOW_RUN', 'Clip workflow returned no structured video rows', JSON.stringify(clipResults).slice(0, 1000));

  const concatVariables = buildConcatStepVariables(app.id, clipRows);
  if (debug) {
    const concatDetail = await client.fetchWorkflowDetail(workflow.concatArtifactId);
    debugData.clipStep.rawResults = clipRows;
    debugData.concatStep = {
      request: {
        taskId: finalTaskId,
        prevTaskId: clipTaskId,
        artifactId: workflow.concatArtifactId,
        workflowId: concatDetail.id,
        variablesBeforeFilter: concatVariables,
        variablesAfterFilter: filterWorkflowVariables(concatDetail, concatVariables),
        service: workflow.service,
      },
    };
  }

  const rawResults = await client.run({
    artifactId: workflow.concatArtifactId,
    variables: concatVariables,
    appId: app.id,
    title: `${app.title} concat`,
    taskId: finalTaskId,
    prevTaskId: clipTaskId,
    service: workflow.service,
  });

  if (debug) debugData.concatStep.rawResults = rawResults;
  return { rawResults, storyboardRows, clipRows, debugData };
}

export function buildClipStepVariables(appId: string, storyboardRows: Record<string, unknown>[], input: Record<string, unknown>) {
  return [
    { name: 'variable:scalar:case', default_value: appId },
    { name: 'variable:dataframe:input_data', default_value: storyboardRows },
    { name: 'variable:scalar:aspect_ratio', default_value: input.ratio },
    { name: 'variable:scalar:duration', default_value: Math.max(1, Math.round(Number(input.duration ?? 5))) },
    { name: 'variable:scalar:llm_model', default_value: input.engine },
  ];
}

export function buildConcatStepVariables(appId: string, clipRows: Record<string, unknown>[]) {
  return [
    { name: 'variable:scalar:case', default_value: appId },
    { name: 'variable:dataframe:input_data', default_value: clipRows },
  ];
}

function toRecordRows(results: unknown[]) {
  return results.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item));
}

function buildScriptGenerationUserInput(userDescription: string, ratio: string, hasModelReference: boolean, scriptMode: 'copy' | 'creative') {
  const noModelModeSpecificInstruction = scriptMode === 'copy'
    ? '- In copy mode, if the reference video implies a person/model, keep that person/model in the shot design and only mark the product with @product.'
    : '- In creative mode, you may include a suitable model/person when the concept benefits from it, but do not tie that person to a specific provided identity.';
  const markerInstruction = hasModelReference
    ? `CRITICAL INSTRUCTION: You MUST embed the markers @model and @product directly into the text AS SUFFIXES attached to the model/person and product/garment references. The rest of the sentence must remain complete and grammatically correct.

Correct format examples:
- "A woman wearing the dress @product is walking @model" (model referenced with @model suffix, product with @product suffix)
- "The model @model showcases the hoodie @product"
- "Close-up of the handbag @product held by the model @model"

INCORRECT (do NOT do this): Just writing "@product..." without a complete sentence or replacing normal nouns with only the marker.

Rules:
- @model must be appended DIRECTLY after any mention of the model/person/mannequin (e.g., "she @model", "the model @model", "woman @model")
- @product must be appended DIRECTLY after any mention of the product/garment/clothing item (e.g., "hoodie @product", "dress @product", "the product @product")
- Keep the full sentence structure - do NOT simplify to just the marker
- The model is always the person wearing or showcasing the product`
    : `CRITICAL INSTRUCTION: No dedicated model reference images are provided.

Rules:
- Do NOT output @model anywhere.
- Only use the @product marker. Append @product DIRECTLY after any mention of the product/item/garment (e.g., "hoodie @product", "bag @product", "the product @product").
- You MAY still describe a person/model/mannequin in normal natural language when the concept or reference video requires one.
- There is no specific model identity to preserve from user input.
- main_image_prompt must describe a product-only white-background product main image, not a model-and-product image.
${noModelModeSpecificInstruction}
- Keep the full sentence structure - do NOT simplify to just the marker`;

  return `${userDescription}

${markerInstruction}

STORYBOARD BREVITY RULES:
- Keep all storyboard text concise and easy to scan in UI.
- Except for shots.sequence, each storyboard text field should be written as 1-2 complete sentences, not long paragraphs and not fragmented keyword lists.
- shots.sequence: keep it short as a compact shot title, around 2-6 words.
- shots.narrative_context: 1-2 concise complete sentences.
- shots.visual_prompt.subject: 1-2 concise complete sentences.
- shots.visual_prompt.environment: 1-2 concise complete sentences.
- shots.visual_prompt.action: 1-2 concise complete sentences.
- shots.visual_prompt.camera_movement: 1-2 concise complete sentences.
- shots.visual_prompt.lighting: 1-2 concise complete sentences.
- shots.visual_prompt.physics_simulation: 1-2 concise complete sentences.
- shots.audio_prompt: 1-2 concise complete sentences.
- Do not generate long explanations, repeated modifiers, bullet lists, or paragraph-style storyboard text.
- Keep each field to the minimum words needed to express the shot clearly while remaining natural and complete.

DOWNSTREAM INTEGRATION RULES:
- The raw user_input will only be provided at this script-generation step. It will NOT be appended again in downstream image or video prompts.
- You MUST fully absorb all valid user requirements into the returned script, main_image_prompt, and each shot field.
- Do not rely on later stages seeing the raw user_input.
- Do not copy the raw user_input as a trailing block or meta instruction. Rewrite it into clean production-ready script and shot content.

ASPECT RATIO RULES:
- All shots must be designed for aspect ratio ${ratio}.
- Set shots.technical_specs.aspect_ratio to exactly "${ratio}" for every shot.
- Keep framing, composition, and camera blocking suitable for ${ratio}.`;
}

function buildMainImagePromptWithModel(mainImagePrompt: string, ratio: string) {
  const basePrompt = mainImagePrompt
    || 'Show the model and product naturally in the same frame. If the product is wearable, have the model wear it naturally; otherwise, keep the model and product clearly visible as separate subjects.';

  return [
    basePrompt,
    '',
    'Product display rule: first determine whether the product is wearable, wearable on the body, or naturally carried by the model, such as clothing, pants, skirts, outerwear, shoes, hats, glasses, jewelry, or bags.',
    'Only when the product is naturally worn, carried, or displayed on the model should the model wear, carry, or use it on the body.',
    'For non-wearable products, do not force the product onto the model. Keep the full-body model and the product clearly visible in the same image, with the product fully visible as an independent subject.',
    'For non-wearable products, avoid elaborate gestures, dramatic poses, strong body movement, or action-driven styling. The person should stand in a simple, natural, front-facing pose so the full body is clearly visible.',
    'For non-wearable products, prioritize a straightforward catalog-style composition: front view of the full-body person, complete product visibility, clean spacing, and no distracting pose design.',
    'Place the product in a natural side-by-side, nearby, or lightly held presentation only if needed, but always keep the product complete, unobstructed, and easy to identify.',
    'Avoid impossible try-on or try-wear behavior for electronics, furniture, home goods, bottles, food, tools, appliances, and other non-wearable products.',
    '',
    'Composition requirement: this must be a full-body main image. The entire person must be visible from head to toe, including the head, torso, legs, ankles, feet, and shoes.',
    'Do not generate half-body, upper-body, bust, close-up, tight crop, cropped legs, cropped knees, cropped calves, cropped ankles, or any framing that cuts off body parts.',
    'Use full-body fashion shot / full-length portrait framing. The camera distance must be far enough to keep the entire person fully inside the frame.',
    'Full body is mandatory. Show the entire person from head to toe, with both feet fully visible in frame.',
    'Do not crop the head, shoulders, elbows, hands, hips, knees, calves, ankles, or feet.',
    'This full-body framing requirement overrides any conflicting close-up, half-body, portrait, or tight framing instruction in the base prompt.',
    '',
    'Background requirement: use a seamless pure white background only, with a clean white studio backdrop.',
    'Do not generate colored backgrounds, gradient backgrounds, environmental scenes, indoor sets, outdoor backgrounds, or any non-white background elements.',
    'Keep the background pure white only.',
    '',
    `Aspect ratio requirement: generate the final image in ${ratio}. Compose the full-body subject specifically for ${ratio} framing.`,
  ].join('\n');
}

function buildMainImagePromptWithoutModel(mainImagePrompt: string, ratio: string) {
  const basePrompt = mainImagePrompt
    || 'Create a clean product-only main image on a seamless pure white background using only the supplied product reference images.';

  return [
    basePrompt,
    '',
    'Generate a product-only main image. Do not add any model, person, mannequin, hands, or body parts.',
    'Use a seamless pure white background only.',
    'The final image may contain one or multiple product views in a single composition, but every visible angle must come directly from the supplied product reference images.',
    'Do not invent new angles, backs, sides, interiors, bottoms, hidden parts, or structural details that are not visible in the provided references.',
    'If the references only show one angle, keep the output to that same supported angle only.',
    'If multiple supported angles are provided, you may arrange one or multiple of those provided angles in a clean catalog-style white-background composition.',
    'Keep product identity, silhouette, proportions, material, texture, color, print, logo, hardware, and construction faithful to the supplied references.',
    'Show the full product clearly and avoid cropping important parts.',
    'Do not add props, lifestyle scenery, packaging, text, watermarks, or decorative elements.',
    '',
    `Aspect ratio requirement: generate the final image in ${ratio}. Compose the product clearly for ${ratio} framing.`,
  ].join('\n');
}

function buildShotImagePrompt(shot: ScriptShot, mainImagePrompt: string, ratio: string, hasModelReference: boolean, hasStoryboardReference: boolean, scriptMode: 'copy' | 'creative') {
  const visual = shot.visual_prompt ?? {};
  const parts: string[] = [];

  if (mainImagePrompt) {
    if (hasModelReference) {
      parts.push('Main image identity reference:');
      parts.push(mainImagePrompt, '');
      parts.push('If a fused main image is provided in the references, treat it as the source of truth for the person, face, body shape, hair, outfit, and product appearance.');
      if (hasStoryboardReference) {
        parts.push('Any original storyboard reference image is only for shot composition, framing, pose, and camera intent. Do not keep the original person, clothing, or product from the storyboard reference.');
        parts.push('Other than replacing the person and product with the ones from the fused main image and product references, keep the original storyboard shot unchanged as much as possible.');
        parts.push('Preserve the original storyboard layout, camera angle, framing, pose, scene structure, background, lighting direction, and action intent unless the shot text explicitly requires a change.');
      } else {
        parts.push('No original storyboard reference image is provided.');
        parts.push('Compose framing, camera angle, environment, and action based on the shot text only.');
        parts.push('Keep person and product identity aligned with the fused main image and product references.');
      }
      parts.push('Do not copy or inherit the background, studio backdrop, plain wall, or scene layout from the fused main image.');
      parts.push('Use the fused main image only for identity and product replacement, not for environment replacement.', '');
    } else {
      parts.push('Product main image reference:');
      parts.push(mainImagePrompt, '');
      parts.push('If a product-only main image is provided in the references, treat it as the source of truth for product identity, shape, color, material, pattern, proportions, and supported viewing angles.');
      if (hasStoryboardReference) {
        parts.push('Any original storyboard reference image is only for shot composition, framing, camera intent, and scene structure. Do not keep the original product from the storyboard reference.');
        parts.push('Other than replacing the original product with the one from the product-only main image and product references, keep the original storyboard shot unchanged as much as possible.');
        parts.push('Preserve the original storyboard layout, camera angle, framing, scene structure, background, lighting direction, and action intent unless the shot text explicitly requires a change.');
        parts.push('If the original storyboard reference contains a person/model/mannequin, keep that same human subject and preserve their identity, face, body, pose, and styling as much as possible.');
        parts.push('Do not remove an existing person from the storyboard reference and do not replace that person with a new specified model identity.');
      } else {
        parts.push('No original storyboard reference image is provided.');
        parts.push('Compose framing, camera angle, environment, and action based on the shot text only.');
        parts.push('Keep product identity aligned with the product-only main image and product references.');
        if (scriptMode === 'creative') {
          parts.push('A suitable person/model may appear if the shot text calls for one, but there is no specific model identity to match.');
        } else {
          parts.push('If the shot text implies a person/model, you may keep a suitable human subject, but there is no specific model identity to match.');
        }
      }
      parts.push('Use the product-only main image only for product identity and supported angle grounding, not as a background or scene template.');
      parts.push('');
    }
  }

  parts.push(`Shot: ${shot.sequence ?? shot.shot_id}`);
  parts.push(shot.narrative_context ?? '');
  parts.push('');
  parts.push(`Subject: ${visual.subject ?? ''}`);
  parts.push(`Environment: ${visual.environment ?? ''}`);
  parts.push(`Action: ${visual.action ?? ''}`);
  parts.push(`Camera angle: ${visual.angle ?? ''}`);
  parts.push(`Camera movement: ${visual.camera_movement ?? ''}`);
  parts.push(`Lighting: ${visual.lighting ?? ''}`);
  parts.push(`Aspect ratio: ${ratio}`);
  parts.push(`Generate the final image specifically for ${ratio} framing. Keep composition, camera distance, and subject placement suitable for ${ratio}.`);
  if (!hasModelReference) {
    parts.push('Keep the product as the primary subject.');
    if (hasStoryboardReference) {
      parts.push('If the original storyboard reference already includes a person/model, keep that human subject and replace only the product.');
    } else if (scriptMode === 'creative') {
      parts.push('If the shot description benefits from a person/model, you may include one in natural language, but do not assume a specific provided identity.');
    }
    parts.push('Do not invent unsupported product angles, hidden sides, or structural details that are not grounded in the provided product references.');
  }
  if (visual.physics_simulation) parts.push(`Physics: ${visual.physics_simulation}`);

  return parts.filter(Boolean).join('\n');
}

function buildShotVideoPrompt(shot: ScriptShot, ratio: string) {
  const visual = shot.visual_prompt ?? {};
  return [
    `Shot: ${shot.sequence ?? shot.shot_id}`,
    shot.narrative_context,
    `Subject: ${visual.subject ?? ''}`,
    `Environment: ${visual.environment ?? ''}`,
    `Action: ${visual.action ?? ''}`,
    `Camera movement: ${visual.camera_movement ?? ''}`,
    `Camera angle: ${visual.angle ?? ''}`,
    `Lighting: ${visual.lighting ?? ''}`,
    `Aspect ratio: ${ratio}`,
    shot.audio_prompt ? `Audio mood: ${shot.audio_prompt}` : '',
  ].filter(Boolean).join('\n').replace(/@product/g, '@Element1').replace(/@model/g, '@Element2');
}

function resolveShotImagePrompt(
  rawInput: Record<string, unknown>,
  shot: ScriptShot,
  mainImagePrompt: string,
  ratio: string,
  hasModelReference: boolean,
  hasStoryboardReference: boolean,
) {
  const overrideMap = resolvePromptOverrideMap(rawInput, ['shot_image_prompt_overrides', 'image_prompt_overrides']);
  const directPrompt = readOptionalStageString(shot as unknown as Record<string, unknown>, ['image_prompt', 'imagePrompt', 'prompt']);
  return overrideMap[shot.shot_id] || directPrompt || buildShotImagePrompt(shot, mainImagePrompt, ratio, hasModelReference, hasStoryboardReference, 'copy');
}

function resolveShotVideoPrompt(
  rawInput: Record<string, unknown>,
  shot: ScriptShot,
  item: { prompt?: string },
  ratio: string,
) {
  const overrideMap = resolvePromptOverrideMap(rawInput, ['shot_video_prompt_overrides', 'video_prompt_overrides']);
  return overrideMap[shot.shot_id] || item.prompt || readOptionalStageString(shot as unknown as Record<string, unknown>, ['video_prompt', 'videoPrompt']) || buildShotVideoPrompt(shot, ratio);
}

function buildVideoElements(productImages: string[], mainImage: string) {
  const extraProductImages = productImages.slice(1);
  return [
    {
      frontal_image_url: productImages[0] || '',
      reference_image_urls: extraProductImages.length > 0 ? extraProductImages : productImages[0] ? [productImages[0]] : [],
    },
    {
      frontal_image_url: mainImage || '',
      reference_image_urls: mainImage ? [mainImage] : [],
    },
  ];
}

function resolveShotTaskId(rawInput: Record<string, unknown>, shotId: string, mapField: 'shot-image' | 'shot-video') {
  const mapKeys = mapField === 'shot-image'
    ? ['shot_image_task_ids', 'shotImageTaskIds']
    : ['shot_video_task_ids', 'shotVideoTaskIds'];
  const taskIdMap = resolvePromptOverrideMap(rawInput, mapKeys);
  return taskIdMap[shotId] || crypto.randomUUID();
}

function resolveShotVideoItemTaskId(
  item: { shot: ScriptShot; task_id?: string },
  rawInput: Record<string, unknown>,
) {
  return item.task_id || resolveShotTaskId(rawInput, item.shot.shot_id, 'shot-video');
}

function enrichStageShotError(error: unknown, stage: 'shot-image' | 'shot-video', shotId: string, taskId: string) {
  const message = error instanceof Error ? error.message : String(error);
  return new CliError('WORKFLOW_RUN', `${stage} failed for shot ${shotId}`, `task_id=${taskId}; ${message}`);
}

function buildReferenceUrls(baseUrls: string[], storyboardReference?: string) {
  const urls = baseUrls.filter(isRemoteUrl);
  if (isRemoteUrl(storyboardReference)) urls.push(storyboardReference);
  return urls;
}

function resolveToolChainDuration(value: unknown) {
  const fallbackDuration = 5;
  if (value === undefined || value === null || value === '') return fallbackDuration;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) {
    throw new CliError('ARGUMENT', `Invalid duration: ${String(value)}`, `Supported durations: ${SUPPORTED_VIDEO_DURATIONS.join(', ')}`);
  }
  const normalized = Math.round(parsed);
  if (!SUPPORTED_VIDEO_DURATIONS.includes(normalized as typeof SUPPORTED_VIDEO_DURATIONS[number])) {
    throw new CliError('ARGUMENT', `Unsupported duration: ${normalized}`, `Supported durations: ${SUPPORTED_VIDEO_DURATIONS.join(', ')}`);
  }
  return normalized;
}

async function prepareVideoReferenceImageUrl(client: ToolClient, taskId: string, imageUrl: string) {
  const normalizedImageUrl = isRemoteUrl(imageUrl) ? imageUrl.trim() : '';
  if (!normalizedImageUrl) throw new CliError('ARGUMENT', 'Invalid storyboard image URL');

  try {
    const dimensions = await fetchRemoteImageDimensions(normalizedImageUrl);
    if (dimensions.width >= MIN_VIDEO_REFERENCE_IMAGE_SIDE_PX && dimensions.height >= MIN_VIDEO_REFERENCE_IMAGE_SIDE_PX) {
      return normalizedImageUrl;
    }
  } catch {}

  const result = await client.callMcpTool(taskId, IMAGE_CLARITY_UPSCALE_TOOL_ID, {
    image_url: normalizedImageUrl,
    aspect_ratio: 'auto',
    upscale_factor: VIDEO_REFERENCE_UPSCALE_FACTOR,
    model: VIDEO_REFERENCE_UPSCALE_MODEL,
  });
  return parseMCPImageUrl(result);
}

async function fetchRemoteImageDimensions(url: string) {
  const response = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  if (!response.ok) throw new Error(`Failed to load image: ${response.status}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  return parseImageDimensions(bytes);
}

function parseImageDimensions(bytes: Uint8Array) {
  const png = parsePngDimensions(bytes);
  if (png) return png;
  const jpeg = parseJpegDimensions(bytes);
  if (jpeg) return jpeg;
  const webp = parseWebpDimensions(bytes);
  if (webp) return webp;
  throw new Error('Unsupported image format');
}

function parsePngDimensions(bytes: Uint8Array) {
  if (bytes.length < 24) return null;
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (!signature.every((value, index) => bytes[index] === value)) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return {
    width: view.getUint32(16),
    height: view.getUint32(20),
  };
}

function parseJpegDimensions(bytes: Uint8Array) {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  let offset = 2;
  while (offset + 9 < bytes.length) {
    if (bytes[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = bytes[offset + 1];
    const length = (bytes[offset + 2] << 8) + bytes[offset + 3];
    if (length < 2 || offset + 2 + length > bytes.length) break;
    const isStartOfFrame = marker >= 0xc0 && marker <= 0xc3;
    if (isStartOfFrame) {
      return {
        height: (bytes[offset + 5] << 8) + bytes[offset + 6],
        width: (bytes[offset + 7] << 8) + bytes[offset + 8],
      };
    }
    offset += 2 + length;
  }
  return null;
}

function parseWebpDimensions(bytes: Uint8Array) {
  if (bytes.length < 30) return null;
  const riff = String.fromCharCode(...bytes.slice(0, 4));
  const webp = String.fromCharCode(...bytes.slice(8, 12));
  if (riff !== 'RIFF' || webp !== 'WEBP') return null;
  const chunk = String.fromCharCode(...bytes.slice(12, 16));
  if (chunk === 'VP8X' && bytes.length >= 30) {
    return {
      width: 1 + bytes[24] + (bytes[25] << 8) + (bytes[26] << 16),
      height: 1 + bytes[27] + (bytes[28] << 8) + (bytes[29] << 16),
    };
  }
  return null;
}

function isRemoteUrl(value: unknown): value is string {
  return typeof value === 'string' && /^https?:\/\//.test(value.trim());
}
