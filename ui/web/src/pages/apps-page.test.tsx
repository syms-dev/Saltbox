import { describe, expect, it } from 'vitest';

import type { App } from '../api/types';
import { matchesApp } from './apps-page';

function app(overrides: Partial<App>): App {
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
    when: [],
    ...overrides,
  };
}

describe('matchesApp', () => {
  const sonarr = app({ categories: ['Media Management'], installed: true });
  const tdarr = app({ repo: 'sandbox', role: 'tdarr', summary: 'Transcoding', title: 'Tdarr' });

  it('matches title, role, summary and category text case-insensitively', () => {
    expect(matchesApp(sonarr, 'SONARR', 'all', '')).toBe(true);
    expect(matchesApp(sonarr, 'series', 'all', '')).toBe(true);
    expect(matchesApp(sonarr, 'media management', 'all', '')).toBe(true);
    expect(matchesApp(sonarr, 'radarr', 'all', '')).toBe(false);
  });

  it('applies the installed and repository filters', () => {
    expect(matchesApp(sonarr, '', 'installed', '')).toBe(true);
    expect(matchesApp(tdarr, '', 'installed', '')).toBe(false);
    expect(matchesApp(tdarr, '', 'sandbox', '')).toBe(true);
    expect(matchesApp(tdarr, '', 'saltbox', '')).toBe(false);
  });

  it('narrows by category', () => {
    expect(matchesApp(sonarr, '', 'all', 'Media Management')).toBe(true);
    expect(matchesApp(tdarr, '', 'all', 'Media Management')).toBe(false);
  });
});

describe('defaultSource', () => {
  it('drops the key from the source line', async () => {
    const { defaultSource } = await import('./app-page');
    expect(defaultSource({ name: 'sonarr_role_web_port', raw: 'sonarr_role_web_port: "8989"', value: '8989' })).toBe(
      '"8989"',
    );
    expect(defaultSource({ name: 'x', raw: '', value: ['a'] })).toBe('["a"]');
  });
});
