import { describe, expect, it } from 'vitest';

import { type Command, rankCommands } from './command-palette';

const command = (label: string, keywords = ''): Command => ({
  group: 'g',
  icon: null,
  id: label,
  keywords,
  label,
  run: () => undefined,
});

describe('rankCommands', () => {
  const all = [command('Open Sonarr', 'sonarr'), command('Sonarr', 'tv'), command('Check for updates', 'refresh')];

  it('puts labels that start with the query first', () => {
    expect(rankCommands(all, 'son').map((c) => c.label)).toEqual(['Sonarr', 'Open Sonarr']);
  });

  it('matches keywords and needs every word', () => {
    expect(rankCommands(all, 'refresh').map((c) => c.label)).toEqual(['Check for updates']);
    expect(rankCommands(all, 'open tv')).toEqual([]);
  });

  it('keeps groups together', () => {
    const mixed = [
      { ...command('Sonarr'), group: 'Manage' },
      { ...command('Sonarqube'), group: 'Install' },
      { ...command('Sonarr settings'), group: 'Manage' },
    ];
    expect(rankCommands(mixed, 'sonar').map((c) => c.group)).toEqual(['Manage', 'Manage', 'Install']);
  });

  it('lists everything for an empty query, up to the limit', () => {
    expect(rankCommands(all, '', 2)).toHaveLength(2);
  });
});
