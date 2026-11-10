import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import type { App } from './api/types';
import { FeedbackProvider } from './components/feedback';

/** An installed-or-not app with sensible defaults for tests. */
export function makeApp(overrides: Partial<App> = {}): App {
  return {
    app_links: [],
    categories: [],
    containers: [],
    default_instances: [],
    docs_url: '',
    install_tag: null,
    installed: false,
    instances: [],
    link: '',
    main_tags: [],
    repo: 'saltbox',
    role: 'sonarr',
    sb_tag: 'sonarr',
    section: 'apps',
    selector: null,
    summary: 'TV series manager',
    supports_instances: true,
    tags: ['sonarr'],
    title: 'Sonarr',
    update_available: false,
    urls: [],
    when: [],
    ...overrides,
  };
}

export function respond(data: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' }, status }),
  );
}

type Routes = Record<string, unknown>;

/** Stub fetch with a table of path → body (or a function of the request); unknown paths get {}. */
export function stubApi(routes: Routes): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = url.replace(/^\/api/, '').split('?')[0] ?? '';
    const key = `${init?.method ?? 'GET'} ${path}`;
    const entry = key in routes ? routes[key] : routes[path];
    const body = typeof entry === 'function' ? (entry as (init?: RequestInit) => unknown)(init) : entry;
    return respond(body ?? {});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Render a page at `path` with the providers the app uses, plus a stand-in job page. */
export function renderAt(element: React.ReactNode, path = '/', pattern = '*'): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <FeedbackProvider>
          <Routes>
            <Route element={<p>job page</p>} path="/activity/:id" />
            <Route element={element} path={pattern} />
          </Routes>
        </FeedbackProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
