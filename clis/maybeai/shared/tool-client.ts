import { CliError } from '@jackwener/opencli/errors';
import { firstString, readWorkflowOptions, type WorkflowOptions } from './options.js';

const DEFAULT_SCRIPT_TIMEOUT_MS = 300_000;
const DEFAULT_TOOL_TIMEOUT_MS = 900_000;
const DEFAULT_FASTEST_API_URL = 'https://api.fastest.ai';

export interface ToolClientOptions extends WorkflowOptions {
  fastestApiUrl: string;
  organizationId?: string;
  app: string;
}

export interface MCPContentItem {
  type: string;
  text?: string;
  url?: string;
  data?: unknown;
  mimeType?: string;
}

export interface MCPRawResponse {
  content?: MCPContentItem[];
  isError?: boolean;
}

export interface MCPToolResult {
  content?: MCPContentItem[];
  structuredContent?: Record<string, unknown> | null;
  isError?: boolean;
  error?: string | null;
  success?: boolean;
  message?: string;
  result?: Record<string, unknown> | null;
  raw_response?: MCPRawResponse | null;
}

export interface ScriptShot {
  shot_id: string;
  timestamp?: { in_point?: number; out_point?: number };
  sequence?: string;
  narrative_context?: string;
  duration_sec?: number;
  visual_prompt?: {
    subject?: string;
    environment?: string;
    action?: string;
    camera_movement?: string;
    lighting?: string;
    physics_simulation?: string;
    angle?: string;
  };
  technical_specs?: {
    aspect_ratio?: string;
    fps?: number;
    seed?: number;
    consistency_anchor?: string;
  };
  audio_prompt?: string;
  video_url?: string;
}

export interface ScriptResult {
  script: string;
  main_image_prompt: string;
  shots: ScriptShot[];
}

export function readToolClientOptions(kwargs: Record<string, unknown>, app: string): ToolClientOptions {
  const workflowOptions = readWorkflowOptions(kwargs);
  const fastestApiUrl = firstString(kwargs['fastest-api-url'], process.env.MAYBEAI_FASTEST_API_URL, process.env.FASTEST_API_URL, process.env.NEXT_PUBLIC_FASTEST_API_URL) ?? DEFAULT_FASTEST_API_URL;
  const organizationId = firstString(kwargs['organization-id'], process.env.MAYBEAI_ORGANIZATION_ID, process.env.ORGANIZATION_ID);
  return {
    ...workflowOptions,
    fastestApiUrl: fastestApiUrl.replace(/\/+$/, ''),
    organizationId,
    app,
  };
}

export class ToolClient {
  constructor(private readonly options: ToolClientOptions) {}

  async generateVideoScript(params: {
    taskId: string;
    productImages: string[];
    referenceImages: string[];
    referenceVideos: string[];
    userInput: string;
    seconds: number;
    mode: 'copy' | 'creative';
  }): Promise<ScriptResult> {
    const response = await fetch(`${this.options.fastestApiUrl}/v1/tool/video/generate`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({
        task_id: params.taskId,
        product_info: '',
        product_images: [...params.productImages, ...params.referenceImages],
        reference_images: [],
        user_input: params.userInput,
        seconds: params.seconds,
        reference_videos: params.referenceVideos,
        mode: params.mode,
      }),
      signal: AbortSignal.timeout(DEFAULT_SCRIPT_TIMEOUT_MS),
    });
    const json = await readJsonResponse(response, 'Video script generation failed');
    return {
      script: typeof json.script === 'string' ? json.script : '',
      main_image_prompt: typeof json.main_image_prompt === 'string' ? json.main_image_prompt : '',
      shots: Array.isArray(json.shots) ? json.shots as ScriptShot[] : [],
    };
  }

  async callMcpTool(taskId: string, toolId: string, toolArgs: Record<string, unknown>): Promise<MCPToolResult> {
    const body: Record<string, unknown> = {
      task_id: taskId,
      app: this.options.app,
      tool_id: toolId,
      tool_args: cleanToolArgs(toolArgs),
    };
    if (this.options.organizationId) body.organization_id = this.options.organizationId;

    const response = await fetch(`${this.options.baseUrl}/api/v1/tool/function_call`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(DEFAULT_TOOL_TIMEOUT_MS),
    });
    const result = await readJsonResponse(response, `MCP tool call failed: ${toolId}`) as MCPToolResult;
    const errorMessage = resolveMCPError(result, `MCP tool call failed: ${toolId}`);
    if (!response.ok || errorMessage) throw new CliError('WORKFLOW_RUN', errorMessage || `MCP tool call failed: ${toolId}`);
    return result;
  }

  private headers() {
    return {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.options.auth.token}`,
      'user-id': this.options.auth.userId,
    };
  }
}

export function parseMCPImageUrl(result: MCPToolResult): string {
  return parseMCPUrl(result, ['url', 'image_url', 'output_url', 'generated_url', 'result_url'], 'image', 'No image URL returned from MCP tool');
}

export function parseMCPVideoUrl(result: MCPToolResult): string {
  return parseMCPUrl(result, ['video_url', 'url', 'final_video', 'output_video', 'generated_video', 'video'], 'video', 'No video URL returned from MCP tool');
}

function parseMCPUrl(result: MCPToolResult, fieldNames: string[], assetType: 'image' | 'video', fallbackErrorMessage: string): string {
  const errorMessage = resolveMCPError(result, fallbackErrorMessage);
  if (errorMessage) throw new CliError('WORKFLOW_RUN', errorMessage);

  const candidates = collectUrlCandidates(result, fieldNames, assetType);
  const best = chooseBestCandidate(candidates, fieldNames, assetType);
  if (best) return best.url;
  throw new CliError('WORKFLOW_RUN', fallbackErrorMessage, JSON.stringify(result).slice(0, 1200));
}

function resolveMCPError(result: MCPToolResult, fallbackMessage: string): string | null {
  if (result.isError || result.raw_response?.isError) return result.error || result.message || fallbackMessage;
  if (result.success === false) return result.error || result.message || fallbackMessage;
  const payload = getMCPPayload(result);
  const payloadError = resolvePayloadError(payload, fallbackMessage);
  if (payloadError) return payloadError;
  if (payload?.success === false) {
    if (typeof payload.error === 'string' && payload.error) return payload.error;
    if (typeof payload.message === 'string' && payload.message) return payload.message;
    return fallbackMessage;
  }
  return null;
}

function getMCPPayload(result: MCPToolResult): Record<string, unknown> | null {
  if (result.result && typeof result.result === 'object') return result.result;
  if (result.structuredContent && typeof result.structuredContent === 'object') return result.structuredContent;
  for (const item of getMCPContentItems(result)) {
    if (!item.text) continue;
    const parsed = parseUnknownTextPayload(item.text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  }
  return null;
}

function getMCPContentItems(result: MCPToolResult): MCPContentItem[] {
  return [...(result.raw_response?.content ?? []), ...(result.content ?? [])];
}

function resolvePayloadError(payload: Record<string, unknown> | null, fallbackMessage: string) {
  if (!payload) return null;

  const status = typeof payload.status === 'string' ? payload.status.toLowerCase() : null;
  if (status === 'error' || status === 'failed' || status === 'failure') {
    return firstNonEmptyString(
      payload.error,
      payload.message,
      payload.reason,
      payload.detail,
      payload.details,
      payload.status_message,
      payload.output,
    ) ?? fallbackMessage;
  }

  return firstNonEmptyString(
    nestedPayloadValue(payload, ['error', 'message']),
    nestedPayloadValue(payload, ['error_message']),
    nestedPayloadValue(payload, ['error', 'detail']),
    nestedPayloadValue(payload, ['detail']),
  );
}

function collectUrlCandidates(value: unknown, fieldNames: string[], assetType: 'image' | 'video', path = '$', candidates: Array<{ url: string; path: string }> = []) {
  if (typeof value === 'string') {
    for (const url of extractUrlsFromText(value, assetType)) {
      candidates.push({ url, path });
    }
    const parsed = parseUnknownTextPayload(value);
    if (parsed !== null) collectUrlCandidates(parsed, fieldNames, assetType, `${path}.__parsed__`, candidates);
    return candidates;
  }

  if (!value || typeof value !== 'object') return candidates;

  if (Array.isArray(value)) {
    value.forEach((item, index) => collectUrlCandidates(item, fieldNames, assetType, `${path}[${index}]`, candidates));
    return candidates;
  }

  for (const [key, child] of Object.entries(value)) {
    const nextPath = `${path}.${key}`;
    if (typeof child === 'string') {
      for (const url of extractUrlsFromText(child, assetType)) {
        candidates.push({ url, path: nextPath });
      }
      if (fieldNames.includes(key) && isRemoteUrl(child)) candidates.push({ url: child, path: nextPath });
      const parsed = parseUnknownTextPayload(child);
      if (parsed !== null) collectUrlCandidates(parsed, fieldNames, assetType, `${nextPath}.__parsed__`, candidates);
      continue;
    }
    collectUrlCandidates(child, fieldNames, assetType, nextPath, candidates);
  }

  return candidates;
}

function chooseBestCandidate(candidates: Array<{ url: string; path: string }>, fieldNames: string[], assetType: 'image' | 'video') {
  let best: { url: string; path: string } | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;

  for (const candidate of dedupeCandidates(candidates)) {
    const score = scoreCandidate(candidate, fieldNames, assetType);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }

  return best;
}

function dedupeCandidates(candidates: Array<{ url: string; path: string }>) {
  const seen = new Set<string>();
  return candidates.filter(candidate => {
    const key = `${candidate.path}::${candidate.url}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function scoreCandidate(candidate: { url: string; path: string }, fieldNames: string[], assetType: 'image' | 'video') {
  const path = candidate.path.toLowerCase();
  const url = candidate.url.toLowerCase();
  let score = 0;

  if (fieldNames.some(field => path.endsWith(`.${field}`) || path.includes(`.${field}.`) || path.includes(`.${field}[`))) score += 80;
  if (assetType === 'video' && path.includes('video')) score += 35;
  if (assetType === 'image' && path.includes('image')) score += 35;
  if (/(^|\.)(output|result|generated|final|artifact|asset|media|file)(\.|$)/.test(path)) score += 25;
  if (assetType === 'video' && /\.(mp4|mov|webm|m4v|m3u8)(?:$|[?#])/.test(url)) score += 40;
  if (assetType === 'image' && /\.(png|jpe?g|webp|gif|bmp|heic)(?:$|[?#])/.test(url)) score += 40;
  if (/\/video[-_/]/.test(url) || /\/videos?\//.test(url)) score += assetType === 'video' ? 20 : 0;
  if (/\/image[-_/]/.test(url) || /\/images?\//.test(url) || /\/uploads\//.test(url)) score += assetType === 'image' ? 20 : 0;
  if (/\.(png|jpe?g|webp|gif|bmp|heic)(?:$|[?#])/.test(url) && assetType === 'video') score -= 60;
  if (/\.(mp4|mov|webm|m4v|m3u8)(?:$|[?#])/.test(url) && assetType === 'image') score -= 60;
  if (/(^|\.)(image_urls|reference_images|product_images|elements|reference_videos)(\.|$)/.test(path)) score -= 40;
  if (path.includes('.__parsed__')) score += 5;

  return score;
}

function extractUrlsFromText(text: string, assetType: 'image' | 'video') {
  const urls = new Set<string>();

  const trimmed = text.trim();
  if (isRemoteUrl(trimmed)) urls.add(trimmed);

  const markdownLinkRegex = /\[[^\]]*\]\((https?:\/\/[^)\s]+)\)/g;
  for (const match of trimmed.matchAll(markdownLinkRegex)) {
    if (match[1]) urls.add(match[1]);
  }

  const plainUrlRegex = /https?:\/\/[^\s)"'`<>]+/g;
  for (const match of trimmed.matchAll(plainUrlRegex)) {
    if (match[0] && looksLikeExpectedAssetUrl(match[0], assetType)) urls.add(match[0]);
  }

  return [...urls];
}

function looksLikeExpectedAssetUrl(url: string, assetType: 'image' | 'video') {
  const lower = url.toLowerCase();
  if (assetType === 'video') {
    return /\.(mp4|mov|webm|m4v|m3u8)(?:$|[?#])/.test(lower) || lower.includes('/video') || lower.includes('/videos/');
  }
  return /\.(png|jpe?g|webp|gif|bmp|heic)(?:$|[?#])/.test(lower) || lower.includes('/image') || lower.includes('/images/') || lower.includes('/uploads/');
}

function parseUnknownTextPayload(text: string): unknown | null {
  const raw = text.trim();
  if (!raw) return null;

  const direct = safeJsonParse(raw);
  if (direct !== null) return direct;

  const fenceMatch = raw.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenceMatch?.[1]) {
    const fenced = safeJsonParse(fenceMatch[1].trim());
    if (fenced !== null) return fenced;
  }

  const bracketStart = raw.search(/[{[]/);
  if (bracketStart >= 0) {
    const possibleJson = raw.slice(bracketStart);
    const parsed = safeJsonParse(possibleJson);
    if (parsed !== null) return parsed;
  }

  return null;
}

function safeJsonParse(text: string): unknown | null {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isRemoteUrl(value: string) {
  return /^https?:\/\//i.test(value.trim());
}

function nestedPayloadValue(payload: Record<string, unknown>, path: string[]) {
  let current: unknown = payload;
  for (const key of path) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function firstNonEmptyString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function cleanToolArgs(args: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(args).filter(([, value]) => value !== undefined && value !== null && value !== ''));
}

async function readJsonResponse(response: Response, message: string) {
  const text = await response.text();
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new CliError('WORKFLOW_RUN', `${message}: ${response.status}`, text.slice(0, 1000));
  }
  if (!response.ok) throw new CliError('WORKFLOW_RUN', `${message}: ${response.status}`, JSON.stringify(parsed).slice(0, 1000));
  return parsed;
}
