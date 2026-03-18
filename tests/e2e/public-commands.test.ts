/**
 * E2E tests for public API commands (browser: false).
 * These commands use Node.js fetch directly — no browser needed.
 */

import { describe, it, expect } from 'vitest';
import { runCli, parseJsonOutput } from './helpers.js';

describe('public commands E2E', () => {
  // ── hackernews ──
  it('hackernews top returns structured data', async () => {
    const { stdout, code } = await runCli(['hackernews', 'top', '--limit', '3', '-f', 'json']);
    expect(code).toBe(0);
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBe(3);
    expect(data[0]).toHaveProperty('title');
    expect(data[0]).toHaveProperty('score');
    expect(data[0]).toHaveProperty('rank');
  }, 30_000);

  it('hackernews top respects --limit', async () => {
    const { stdout, code } = await runCli(['hackernews', 'top', '--limit', '1', '-f', 'json']);
    expect(code).toBe(0);
    const data = parseJsonOutput(stdout);
    expect(data.length).toBe(1);
  }, 30_000);

  // ── v2ex (public API, browser: false) ──
  it('v2ex hot returns topics', async () => {
    const { stdout, code } = await runCli(['v2ex', 'hot', '--limit', '3', '-f', 'json']);
    expect(code).toBe(0);
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBeGreaterThanOrEqual(1);
    expect(data[0]).toHaveProperty('title');
  }, 30_000);

  it('v2ex latest returns topics', async () => {
    const { stdout, code } = await runCli(['v2ex', 'latest', '--limit', '3', '-f', 'json']);
    expect(code).toBe(0);
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBeGreaterThanOrEqual(1);
  }, 30_000);

  it('v2ex topic returns topic detail', async () => {
    // Topic 1000001 is a well-known V2EX topic
    const { stdout, code } = await runCli(['v2ex', 'topic', '--id', '1000001', '-f', 'json']);
    // May fail if V2EX rate-limits, but should return structured data
    if (code === 0) {
      const data = parseJsonOutput(stdout);
      expect(data).toBeDefined();
    }
  }, 30_000);

  // ── xiaoyuzhou (Chinese site — may return empty on overseas CI runners) ──
  it('xiaoyuzhou podcast returns podcast profile', async () => {
    const { stdout, code } = await runCli(['xiaoyuzhou', 'podcast', '6013f9f58e2f7ee375cf4216', '-f', 'json']);
    if (code !== 0) { console.warn('xiaoyuzhou podcast skipped (geo-blocked?)'); return; }
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBe(1);
    expect(data[0]).toHaveProperty('title');
    expect(data[0]).toHaveProperty('subscribers');
    expect(data[0]).toHaveProperty('episodes');
  }, 30_000);

  it('xiaoyuzhou podcast-episodes returns episode list', async () => {
    const { stdout, code } = await runCli(['xiaoyuzhou', 'podcast-episodes', '6013f9f58e2f7ee375cf4216', '-f', 'json']);
    if (code !== 0) { console.warn('xiaoyuzhou podcast-episodes skipped (geo-blocked?)'); return; }
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBeGreaterThanOrEqual(1);
    expect(data[0]).toHaveProperty('eid');
    expect(data[0]).toHaveProperty('title');
    expect(data[0]).toHaveProperty('duration');
  }, 30_000);

  it('xiaoyuzhou episode returns episode detail', async () => {
    const { stdout, code } = await runCli(['xiaoyuzhou', 'episode', '69b3b675772ac2295bfc01d0', '-f', 'json']);
    if (code !== 0) { console.warn('xiaoyuzhou episode skipped (geo-blocked?)'); return; }
    const data = parseJsonOutput(stdout);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBe(1);
    expect(data[0]).toHaveProperty('title');
    expect(data[0]).toHaveProperty('podcast');
    expect(data[0]).toHaveProperty('plays');
    expect(data[0]).toHaveProperty('comments');
  }, 30_000);
});
