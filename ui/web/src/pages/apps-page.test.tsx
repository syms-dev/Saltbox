import { describe, expect, it } from 'vitest';

import { makeApp } from '../test-utils';
import { inGroup, matchesText, subcategory } from './apps-page';

describe('catalog filters', () => {
  const sonarr = makeApp({ categories: ['Content Acquisition Apps > Collection Manager'], installed: true });
  const tdarr = makeApp({
    categories: ['Accessories > File Processing'],
    repo: 'sandbox',
    role: 'tdarr',
    summary: 'Transcoding',
    title: 'Tdarr',
  });

  it('matches every word against title, role, summary and categories', () => {
    expect(matchesText(sonarr, 'SONARR')).toBe(true);
    expect(matchesText(sonarr, 'tv manager')).toBe(true);
    expect(matchesText(sonarr, 'collection')).toBe(true);
    expect(matchesText(sonarr, 'tv radarr')).toBe(false);
    expect(matchesText(sonarr, '  ')).toBe(true);
  });

  it('groups by the top category and offers popular picks', () => {
    expect(inGroup(sonarr, 'Content Acquisition Apps')).toBe(true);
    expect(inGroup(tdarr, 'Content Acquisition Apps')).toBe(false);
    expect(inGroup(sonarr, 'popular')).toBe(true);
    expect(inGroup(tdarr, 'popular')).toBe(false);
    expect(inGroup(tdarr, '')).toBe(true);
  });

  it('names the kind of app from the category path', () => {
    expect(subcategory(tdarr)).toBe('File Processing');
    expect(subcategory(makeApp())).toBe('');
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
