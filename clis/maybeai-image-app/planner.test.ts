import { describe, expect, it } from 'vitest';
import { buildImageAppPlan } from './planner.js';

describe('maybeai-image-app planner', () => {
  it('builds replica-listing-image structured input from dedicated flags', () => {
    const plan = buildImageAppPlan(['给这个商品做参考生套图'], {
      app: 'replica-listing-image',
      'product-images': 'https://example.com/front.jpg,https://example.com/side.jpg',
      'reference-template': 'https://example.com/template.jpg',
      'image-group-type': 'Listing',
      platform: 'Amazon',
      market: 'North America',
    });

    expect(plan.selectedApp).toBe('replica-listing-image');
    expect(plan.missingFields).toEqual([]);
    expect(plan.input).toMatchObject({
      template: 'https://example.com/template.jpg',
      image_group_type: 'Listing',
      platform: 'Amazon',
      market: 'North America',
    });
    expect(plan.input.product_images).toEqual([
      { image_type: 'front', url: 'https://example.com/front.jpg' },
      { image_type: 'side', url: 'https://example.com/side.jpg' },
    ]);
  });

  it('builds gen-reference structured inputs from product and reference flags', () => {
    const plan = buildImageAppPlan(['按参考图生成一张新图'], {
      app: 'gen-reference',
      'product-images': 'https://example.com/product-front.jpg,https://example.com/product-back.jpg',
      'reference-images': 'https://example.com/ref-color.jpg,https://example.com/ref-model.jpg,https://example.com/ref-scene.jpg',
      prompt: '保留卖点，参考模特与场景',
    });

    expect(plan.selectedApp).toBe('gen-reference');
    expect(plan.missingFields).toEqual([]);
    expect(plan.input.prompt).toBe('保留卖点，参考模特与场景');
    expect(plan.input.product_images).toEqual([
      { image_type: 'front_image', url: 'https://example.com/product-front.jpg' },
      { image_type: 'back_image', url: 'https://example.com/product-back.jpg' },
    ]);
    expect(plan.input.reference_images).toEqual([
      { image_type: 'reference_color_image', url: 'https://example.com/ref-color.jpg' },
      { image_type: 'reference_modle_image', url: 'https://example.com/ref-model.jpg' },
      { image_type: 'reference_scene_image', url: 'https://example.com/ref-scene.jpg' },
    ]);
  });

  it('detects reference-generation intent from natural language', () => {
    const plan = buildImageAppPlan(['用这张商品图参考生图'], {
      'product-images': 'https://example.com/product.jpg',
      'reference-images': 'https://example.com/ref.jpg',
    });

    expect(plan.selectedApp).toBe('gen-reference');
    expect(plan.candidates[0]?.app).toBe('gen-reference');
  });
});
