import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ContainerStats } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { ResourcesCard, sortContainers } from './system-sections';

function stats(name: string, cpu: number, memory: number): ContainerStats {
  return { cpu_percent: cpu, memory, memory_limit: 16e9, memory_percent: 1, name, pids: 10 };
}

const CONTAINERS = [
  stats('plex', 31.5, 1500e6),
  stats('sonarr', 2, 300e6),
  stats('autoheal', 0.1, 20e6),
  stats('radarr', 2, 900e6),
  ...Array.from({ length: 7 }, (_, i) => stats(`extra${i}`, 0.5, 50e6)),
];

afterEach(() => {
  vi.unstubAllGlobals();
});

function names(): string[] {
  const table = screen.getByRole('table', { name: 'Container resource use' });
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0]?.textContent ?? '');
}

describe('sortContainers', () => {
  it('orders by the column asked for and breaks ties by name', () => {
    const order = (key: 'cpu' | 'memory' | 'name', descending: boolean): string[] =>
      sortContainers(CONTAINERS.slice(0, 4), { descending, key }).map((c) => c.name);
    expect(order('cpu', true)).toEqual(['plex', 'radarr', 'sonarr', 'autoheal']);
    expect(order('memory', true)).toEqual(['plex', 'radarr', 'sonarr', 'autoheal']);
    expect(order('memory', false)).toEqual(['autoheal', 'sonarr', 'radarr', 'plex']);
    expect(order('name', false)).toEqual(['autoheal', 'plex', 'radarr', 'sonarr']);
  });
});

describe('ResourcesCard', () => {
  it('sorts by the heading pressed and can show every container', async () => {
    stubApi({
      '/apps': [],
      '/resources': {
        containers: CONTAINERS,
        error: '',
        host: { cores: 8, load: [1, 1, 1], load_percent: 12, memory_percent: 40, memory_total: 16e9, memory_used: 6e9 },
      },
    });
    renderAt(<ResourcesCard />);
    expect(await screen.findByRole('columnheader', { name: 'CPU' })).toHaveAttribute('aria-sort', 'descending');
    expect(names().slice(0, 3)).toEqual(['plex', 'radarr', 'sonarr']);
    expect(names()).toHaveLength(8);

    fireEvent.click(screen.getByRole('button', { name: 'Container' }));
    expect(screen.getByRole('columnheader', { name: 'Container' })).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getByRole('columnheader', { name: 'CPU' })).toHaveAttribute('aria-sort', 'none');
    expect(names()[0]).toBe('autoheal');
    fireEvent.click(screen.getByRole('button', { name: 'Container' }));
    expect(names()[0]).toBe('sonarr');

    fireEvent.click(screen.getByRole('button', { name: 'Memory' }));
    expect(names().slice(0, 2)).toEqual(['plex', 'radarr']);
    fireEvent.click(screen.getByRole('button', { name: 'Show all 11 containers' }));
    expect(names()).toHaveLength(11);
    expect(names().at(-1)).toBe('autoheal');
    fireEvent.click(screen.getByRole('button', { name: 'Show the first 8' }));
    expect(names()).toHaveLength(8);
  });
});
