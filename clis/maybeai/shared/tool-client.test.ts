import { describe, expect, it } from 'vitest';
import { parseMCPImageUrl, parseMCPVideoUrl, type MCPToolResult } from './tool-client.js';

describe('tool-client MCP URL parsing', () => {
  it('reads direct video_url fields', () => {
    const result: MCPToolResult = {
      result: {
        video_url: 'https://cdn.example.com/output.mp4',
      },
    };
    expect(parseMCPVideoUrl(result)).toBe('https://cdn.example.com/output.mp4');
  });

  it('reads nested final video from fenced JSON text', () => {
    const result: MCPToolResult = {
      content: [
        {
          type: 'text',
          text: '```json\n{"generated_videos":[{"url":"https://cdn.example.com/final.mp4"}],"final_video":"https://cdn.example.com/final.mp4"}\n```',
        },
      ],
    };
    expect(parseMCPVideoUrl(result)).toBe('https://cdn.example.com/final.mp4');
  });

  it('prefers returned video over echoed input image urls', () => {
    const result: MCPToolResult = {
      result: {
        image_urls: [
          'https://statics.example.com/input/product.png',
          'https://statics.example.com/input/model.png',
        ],
        outputs: [
          {
            file: {
              url: 'https://statics.example.com/render/final-video.mp4',
            },
          },
        ],
      },
    };
    expect(parseMCPVideoUrl(result)).toBe('https://statics.example.com/render/final-video.mp4');
  });

  it('reads markdown video links from raw_response', () => {
    const result: MCPToolResult = {
      raw_response: {
        content: [
          {
            type: 'text',
            text: '[download](https://cdn.example.com/clip.webm)',
          },
        ],
      },
    };
    expect(parseMCPVideoUrl(result)).toBe('https://cdn.example.com/clip.webm');
  });

  it('reads nested image urls from parsed text payloads', () => {
    const result: MCPToolResult = {
      content: [
        {
          type: 'text',
          text: '{"output":{"image":{"url":"https://cdn.example.com/render.png"}}}',
        },
      ],
    };
    expect(parseMCPImageUrl(result)).toBe('https://cdn.example.com/render.png');
  });

  it('surfaces payload status errors instead of url fallback', () => {
    const result: MCPToolResult = {
      result: {
        status: 'error',
        message: 'Model rejected this request',
      },
    };
    expect(() => parseMCPVideoUrl(result)).toThrow('Model rejected this request');
  });
});
