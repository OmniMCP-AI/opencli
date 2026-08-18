import { describe, expect, it } from 'vitest';
import { buildReviewSummary } from './review.js';

describe('maybeai-video-app review', () => {
  it('summarizes shot-video items with task_id and video_url', () => {
    const summary = buildReviewSummary({
      stage: 'shot-video',
      selected_shot_ids: ['S01_tracking_shot'],
      items: [
        {
          task_id: 'task-1',
          shot_id: 'S01_tracking_shot',
          sequence: 'Tracking shot',
          prompt: 'custom prompt',
          video_url: 'https://example.com/shot.mp4',
        },
      ],
    });

    expect(summary).toEqual({
      selected_shot_ids: ['S01_tracking_shot'],
      items: [
        {
          task_id: 'task-1',
          shot_id: 'S01_tracking_shot',
          sequence: 'Tracking shot',
          prompt: 'custom prompt',
          video_url: 'https://example.com/shot.mp4',
        },
      ],
    });
  });
});
