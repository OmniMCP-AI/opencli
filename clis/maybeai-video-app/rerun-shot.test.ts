import { describe, expect, it } from 'vitest';
import { buildRerunShotInput, normalizeRerunStage } from './rerun-shot.js';

describe('maybeai-video-app rerun-shot', () => {
  it('builds shot-video rerun input with prompt and task id overrides', () => {
    const nextInput = buildRerunShotInput({
      items: [{ shot: { shot_id: 'S01_tracking_shot' }, image_url: 'https://example.com/image.jpg' }],
    }, 'shot-video', 'S01_tracking_shot', {
      prompt: 'override prompt',
      'task-id': 'task-1',
    });

    expect(nextInput).toEqual({
      items: [{ shot: { shot_id: 'S01_tracking_shot' }, image_url: 'https://example.com/image.jpg' }],
      shot_ids: ['S01_tracking_shot'],
      shot_video_prompt_overrides: {
        S01_tracking_shot: 'override prompt',
      },
      shot_video_task_ids: {
        S01_tracking_shot: 'task-1',
      },
    });
  });

  it('normalizes allowed rerun stages', () => {
    expect(normalizeRerunStage('shot-image')).toBe('shot-image');
    expect(normalizeRerunStage('shot-video')).toBe('shot-video');
  });
});
