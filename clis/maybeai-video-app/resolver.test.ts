import { describe, expect, it } from 'vitest';
import { resolveVideoAppInput } from './resolver.js';

describe('maybeai-video-app resolver', () => {
  it('defaults video-remake duration to 5 seconds', () => {
    const resolved = resolveVideoAppInput('video-remake', {
      product: 'https://example.com/product.png',
      reference_video: 'https://example.com/reference.mp4',
    });

    expect(resolved.input.duration).toBe(5);
    expect(resolved.appliedDefaults.duration).toBe(5);
  });

  it('defaults image-to-video duration to 5 seconds', () => {
    const resolved = resolveVideoAppInput('image-to-video', {
      image: 'https://example.com/image.png',
      prompt: 'slow push-in',
    });

    expect(resolved.input.duration).toBe(5);
    expect(resolved.appliedDefaults.duration).toBe(5);
  });

  it('normalizes shell fuse-videos form aliases for video-remake', () => {
    const resolved = resolveVideoAppInput('video-remake', {
      productImage: ['https://example.com/product.png'],
      referenceImage: ['https://example.com/model.png'],
      referenceVideo: ['https://example.com/reference.mp4'],
      userDescription: 'keep the pacing',
      aspectRatio: '9:16',
      llmModel: 'fal-ai/kling-video/v3/pro/image-to-video',
      generateAudio: true,
    });

    expect(resolved.input.product).toBe('https://example.com/product.png');
    expect(resolved.input.person).toBe('https://example.com/model.png');
    expect(resolved.input.reference_video).toBe('https://example.com/reference.mp4');
    expect(resolved.input.prompt).toBe('keep the pacing');
    expect(resolved.input.ratio).toBe('9:16');
    expect(resolved.input.engine).toBe('fal-ai/kling-video/v3/pro/image-to-video');
    expect(resolved.input.generate_audio).toBe(true);
  });
});
