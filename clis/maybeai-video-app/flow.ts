import { cli, Strategy } from '@jackwener/opencli/registry';
import { getApp } from './catalog.js';
import { getShellFrontendFlow } from './flow-data.js';

cli({
  site: 'maybeai-video-app',
  name: 'flow',
  description: 'Describe shell-aligned frontend steps, user actions, stage inputs, and outputs for a MaybeAI video app',
  strategy: Strategy.PUBLIC,
  browser: false,
  defaultFormat: 'json',
  args: [
    { name: 'app', positional: true, required: true, help: 'MaybeAI video app id, e.g. video-remake' },
  ],
  func: async (_page, kwargs) => {
    const app = getApp(String(kwargs.app));
    const frontendFlow = getShellFrontendFlow(app.id);
    return {
      app: app.id,
      title: app.title,
      summary: app.summary,
      sourceRef: app.sourceRef,
      frontendFlow,
      note: frontendFlow
        ? 'frontendFlow is derived from shell fuse-videos UI and hook orchestration.'
        : 'No shell-specific frontend flow is registered for this app.',
    };
  },
});
