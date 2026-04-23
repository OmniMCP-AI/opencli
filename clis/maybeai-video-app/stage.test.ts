import { describe, expect, it } from 'vitest';
import { pickVideoRemakeResolvableInput, resolveRequestedShotIds } from './engine.js';

describe('maybeai-video-app stage helpers', () => {
  it('keeps only resolver-safe fields for video-remake stage input', () => {
    const picked = pickVideoRemakeResolvableInput({
      productImage: ['https://example.com/product.png'],
      referenceVideo: ['https://example.com/reference.mp4'],
      userDescription: 'keep pacing',
      aspectRatio: '1:1',
      llmModel: 'fal-ai/kling-video/v3/pro/image-to-video',
      generateAudio: true,
      main_image: 'https://example.com/main.png',
      shot: { shot_id: 'shot-1' },
      items: [{ shot: { shot_id: 'shot-1' }, image_url: 'https://example.com/shot.png' }],
    });

    expect(picked).toEqual({
      productImage: ['https://example.com/product.png'],
      referenceVideo: ['https://example.com/reference.mp4'],
      userDescription: 'keep pacing',
      aspectRatio: '1:1',
      llmModel: 'fal-ai/kling-video/v3/pro/image-to-video',
      generateAudio: true,
    });
  });

  it('parses shot ids from input payload or flags', () => {
    expect(resolveRequestedShotIds({
      shot_ids: ['S01_tracking_shot', 'S02_static_twirl', 'S01_tracking_shot'],
    }, {})).toEqual(['S01_tracking_shot', 'S02_static_twirl']);

    expect(resolveRequestedShotIds({}, {
      'shot-ids': ' S03_medium_full_shot, S05_joyful_movement ,S03_medium_full_shot ',
    })).toEqual(['S03_medium_full_shot', 'S05_joyful_movement']);
  });
});
