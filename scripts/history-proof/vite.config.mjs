// Test boundary only: render the real app and substitute only external APIs.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mergeConfig } from 'vite';
import appConfig from '../../apps/desktop/vite.config.ts';

export default async (env) => mergeConfig(await appConfig(env), {
  plugins: [{
    name: 'history-proof',
    enforce: 'pre',
    load(id) {
      if (process.env.HISTORY_BASELINE_FILE && id.replaceAll('\\', '/').endsWith('/components/editor/QueryHistory.vue')) {
        return readFileSync(resolve(process.env.HISTORY_BASELINE_FILE), 'utf8');
      }
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        if (!pathname.startsWith('/api/')) return next();
        const responses = {
          '/api/auth/check': { required: false, authenticated: true, setup_required: false },
          '/api/migration/status': { needsMigration: false, state: 'not_required' },
          '/api/history/search': { entries: [], total: 0, next_cursor: null },
          '/api/history/options': [],
        };
        res.setHeader('Content-Type', 'application/json');
        res.statusCode = Object.hasOwn(responses, pathname) ? 200 : 503;
        res.end(JSON.stringify(responses[pathname] ?? { error: 'Unavailable in layout-only fixture' }));
      });
    },
  }],
  server: { host: '127.0.0.1', strictPort: true },
});
