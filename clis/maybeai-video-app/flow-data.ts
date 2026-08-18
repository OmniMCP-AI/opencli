export interface FlowFieldDefinition {
  key: string;
  type: string;
  required?: boolean;
  multiple?: boolean;
  options?: string[];
  note?: string;
}

export interface FlowStepDefinition {
  key: string;
  label: string;
  trigger: string;
  input: FlowFieldDefinition[];
  output: Array<{
    key: string;
    type: string;
    note?: string;
  }>;
  userActions?: string[];
  note?: string;
}

export interface FrontendFlowDefinition {
  formSteps: Array<{
    key: string;
    label: string;
    fields: FlowFieldDefinition[];
    note?: string;
  }>;
  runtimeSteps: FlowStepDefinition[];
  autoRunSequence: string[];
  retryMapping: Record<string, string>;
  opencliMapping: {
    command: string;
    inputAliases: Array<{
      shellField: string;
      opencliField: string;
      note?: string;
    }>;
    unsupportedInteractiveActions: string[];
  };
}

const VIDEO_MODEL_OPTIONS = [
  'fal-ai/kling-video/v3/pro/image-to-video',
  'fal-ai/kling-video/o1/reference-to-video',
  'fal-ai/kling-video/o1/standard/reference-to-video',
  'fal-ai/kling-video/o3/pro/reference-to-video',
  'fal-ai/kling-video/o3/standard/image-to-video',
  'bytedance/seedance-2.0/fast/image-to-video',
  'bytedance/seedance-2.0/fast/reference-to-video',
  'bytedance/seedance-2.0/image-to-video',
  'bytedance/seedance-2.0/reference-to-video',
] as const;

const ASPECT_RATIOS = ['9:16', '16:9', '4:3', '3:4', '1:1'] as const;
const CREATIVE_DURATIONS = ['5', '10', '15', '20', '25', '30'] as const;

export function getShellFrontendFlow(appId: string): FrontendFlowDefinition | null {
  if (appId !== 'video-remake') return null;

  return {
    formSteps: [
      {
        key: 'product-image',
        label: '上传图片',
        fields: [
          { key: 'productImage', type: 'image[]', required: true, multiple: true, note: '最多 3 张，至少 1 张' },
        ],
      },
      {
        key: 'reference-image',
        label: '选择模特',
        fields: [
          { key: 'referenceImage', type: 'image[]', multiple: false, note: '可为空；shell UI 只取首张' },
        ],
      },
      {
        key: 'reference-video',
        label: '参考视频',
        fields: [
          { key: 'referenceVideo', type: 'video[]', required: true, note: 'copy 模式必须且只能有 1 个参考视频' },
        ],
      },
      {
        key: 'script-mode',
        label: '模式',
        fields: [
          { key: 'scriptMode', type: 'enum', options: ['copy', 'creative'], note: 'shell 默认页可切换；video-remake 在 opencli 当前对应 copy 链路' },
        ],
        note: '当且仅当参考视频数量为 1 时，shell 默认页允许切回 copy 模式。',
      },
      {
        key: 'requirements',
        label: '生成要求',
        fields: [
          { key: 'userDescription', type: 'text', note: '额外创意、镜头、转场要求' },
        ],
      },
      {
        key: 'aspect-ratio',
        label: '尺寸比例',
        fields: [
          { key: 'aspectRatio', type: 'enum', options: [...ASPECT_RATIOS] },
        ],
      },
      {
        key: 'duration',
        label: '视频时长',
        fields: [
          { key: 'duration', type: 'enum', options: [...CREATIVE_DURATIONS], note: 'shell copy 模式下锁定为 5 秒' },
        ],
      },
      {
        key: 'audio',
        label: '是否配音',
        fields: [
          { key: 'generateAudio', type: 'boolean', note: '用于分镜视频生成阶段' },
        ],
      },
      {
        key: 'model',
        label: '模型',
        fields: [
          { key: 'llmModel', type: 'enum', options: [...VIDEO_MODEL_OPTIONS], note: 'shell 仅内部用户可见；默认 v3/pro' },
        ],
      },
    ],
    runtimeSteps: [
      {
        key: 'script',
        label: '生成视频脚本与分镜',
        trigger: 'startGeneration',
        input: [
          { key: 'task_id', type: 'uuid', required: true },
          { key: 'product_images', type: 'string[]', required: true, note: '若存在模特图，会拼在 product_images 后面' },
          { key: 'reference_videos', type: 'string[]', required: true, note: 'copy 模式下仅 1 个' },
          { key: 'user_input', type: 'string', required: true, note: '由 userDescription + ratio + marker rules 拼装' },
          { key: 'seconds', type: 'number', required: true },
          { key: 'mode', type: 'enum', required: true, options: ['copy', 'creative'] },
        ],
        output: [
          { key: 'script', type: 'string' },
          { key: 'main_image_prompt', type: 'string' },
          { key: 'shots[]', type: 'shot[]', note: '包含 sequence/narrative_context/visual_prompt/technical_specs/audio_prompt' },
        ],
        userActions: [
          '编辑整段 script 文本',
          '逐镜头编辑 sequence / narrative_context / visual_prompt / audio_prompt',
          '中英互译脚本与分镜文案',
          '启用/禁用某个 shot',
        ],
      },
      {
        key: 'main-image',
        label: '生成主图',
        trigger: 'generateMainImage',
        input: [
          { key: 'prompt', type: 'string', required: true, note: '由 main_image_prompt + shell 主图规则拼装' },
          { key: 'image_urls', type: 'string[]', required: true, note: '商品图 + 可选模特图' },
          { key: 'aspect_ratio', type: 'string', required: true },
        ],
        output: [
          { key: 'mainImage', type: 'string', note: '主图 URL' },
          { key: 'mainImageHistory[]', type: 'string[]', note: '重生历史' },
        ],
        userActions: [
          '重生主图',
          '从素材库替换主图',
          '从历史记录回切主图',
        ],
      },
      {
        key: 'storyboard-images',
        label: '生成分镜图',
        trigger: 'generateImages / generateImagesBatch / regenerateShotImage',
        input: [
          { key: 'prompt', type: 'string', required: true, note: '逐镜头 prompt 或批量 storyboard-grid prompt' },
          { key: 'image_urls', type: 'string[]', required: true, note: '商品图 + 主图 + copy 模式下可带 consistency_anchor' },
          { key: 'aspect_ratio', type: 'string', required: true },
          { key: 'model', type: 'string', note: '批量模式会用 storyboard image model' },
        ],
        output: [
          { key: 'generatedImages[shot_id]', type: 'record<string,string>' },
          { key: 'shotImageStatus[shot_id]', type: 'record<string,status>' },
          { key: 'shotImageVariations[shot_id]', type: 'record<string,string[]>', note: '已有图重生时会生成 2x2 variation grid 后拆分' },
        ],
        userActions: [
          '单镜头重生',
          '批量生成或逐镜生成',
          '从 4 张变体中选一张',
          '从素材库替换分镜图',
          '从历史记录回切分镜图',
          '将分镜图加入素材库',
          '对某个 shot 使用原始 storyboard 图',
        ],
      },
      {
        key: 'storyboard-videos',
        label: '生成分镜视频',
        trigger: 'generateVideos / regenerateVideos / regenerateShotVideo',
        input: [
          { key: 'model', type: 'string', required: true },
          { key: 'prompt', type: 'string', required: true, note: '由 shot 文本拼装，并把 @product/@model 替换成 @Element1/@Element2' },
          { key: 'image_urls', type: 'string[]', required: true, note: '先做最小边 >= 400 的放大准备后只传 1 张 prepared image' },
          { key: 'aspect_ratio', type: 'string', required: true },
          { key: 'duration', type: 'number', required: true, note: 'shell 当前仍按 shot.duration_sec round；opencli 已固定受支持时长集合' },
          { key: 'generate_audio', type: 'boolean' },
          { key: 'elements', type: 'object[]', required: true, note: 'Element1=商品，Element2=主图/模特' },
        ],
        output: [
          { key: 'generatedVideos[shot_id]', type: 'record<string,string>' },
          { key: 'shotVideoStatus[shot_id]', type: 'record<string,status>' },
          { key: 'shotVideoHistory[shot_id]', type: 'record<string,string[]>' },
        ],
        userActions: [
          '单镜头重生视频',
          '批量重生全部 active shot 视频',
          '从素材库替换分镜视频',
          '从历史记录回切分镜视频',
          '将分镜视频加入素材库',
        ],
      },
      {
        key: 'compose',
        label: '合成视频',
        trigger: 'composeVideos',
        input: [
          { key: 'video_urls', type: 'string[]', required: true, note: '按 active shot 顺序拼接；若只有 1 段则直接透传' },
          { key: 'output_format', type: 'string', required: true },
          { key: 'aspect_ratio', type: 'string', required: true },
          { key: 'speed_preset', type: 'string', required: true },
          { key: 'quality_crf', type: 'number', required: true },
        ],
        output: [
          { key: 'composedVideo', type: 'string', note: '最终视频 URL；若全部 shot 使用原视频则直接返回 reference video' },
        ],
        userActions: [
          '执行合成',
          '保存结果到结果列表',
          '关闭时自动把生成过的分镜素材写入素材库',
        ],
      },
    ],
    autoRunSequence: [
      'script-ready -> generate-main-image',
      'main-image-ready -> generate-images or generate-images-batch',
      'images-ready -> generate-videos',
      'videos-ready -> compose-videos',
      'composedVideo done -> save-result',
    ],
    retryMapping: {
      script: '重新 startGeneration',
      'main-image': 'generateMainImage',
      'storyboard-images': 'generateImages',
      'storyboard-videos': 'regenerateVideos',
      compose: 'composeVideos',
    },
    opencliMapping: {
      command: 'opencli maybeai-video-app run|generate|payload|flow|stage',
      inputAliases: [
        { shellField: 'productImage[0]', opencliField: 'product / product-images', note: 'shell 多图会取首张作 canonical product' },
        { shellField: 'referenceImage[0]', opencliField: 'person / reference-images' },
        { shellField: 'referenceVideo[0]', opencliField: 'reference_video / reference-video' },
        { shellField: 'userDescription', opencliField: 'prompt' },
        { shellField: 'aspectRatio', opencliField: 'ratio' },
        { shellField: 'llmModel', opencliField: 'engine' },
        { shellField: 'generateAudio', opencliField: 'generate_audio / --generate-audio' },
      ],
      unsupportedInteractiveActions: [
        '当前 opencli 还不支持交互式编辑 script / shots',
        '当前 opencli 还不支持逐 shot 启停 active 状态',
        '当前 opencli 还不支持从素材库选择或回切历史版本',
        '当前 opencli 还不支持 UI 内的翻译与变体挑选交互；但现在支持阶段拆分执行、按 shot 选择执行，以及通过 JSON 覆盖生图/生视频 prompt',
      ],
    },
  };
}
