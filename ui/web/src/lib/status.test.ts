import { describe, expect, it } from 'vitest';

import type { ContainerState } from '../api/types';
import { appHealth, containerHealth, hostOf, needsAttention } from './status';

type Probe = { health: string | null; status: string };
const c = (status: string, health: string | null = null): Probe => ({ health, status });

describe('status', () => {
  it('describes a container in plain words', () => {
    expect(containerHealth(c('running', 'healthy'))).toEqual({ label: 'Running', tone: 'ok' });
    expect(containerHealth(c('running'))).toEqual({ label: 'Running', tone: 'ok' });
    expect(containerHealth(c('running', 'unhealthy'))).toEqual({ label: 'Unhealthy', tone: 'danger' });
    expect(containerHealth(c('running', 'starting')).tone).toBe('warn');
    expect(containerHealth(c('exited'))).toEqual({ label: 'Stopped', tone: 'muted' });
  });

  it('takes the worst container for an app', () => {
    const app = (...containers: Probe[]): { containers: ContainerState[] } => ({
      containers: containers.map((x, i) => ({
        ...x,
        image: '',
        name: `c${i}`,
        update: 'current' as const,
        update_detail: '',
        urls: [],
      })),
    });
    expect(appHealth(app(c('running'), c('running', 'unhealthy'))).label).toBe('Unhealthy');
    expect(appHealth(app(c('running'), c('exited'))).label).toBe('Partly stopped');
    expect(appHealth(app()).label).toBe('Not running');
    expect(needsAttention(app(c('exited')))).toBe(true);
    expect(needsAttention(app(c('running')))).toBe(false);
    expect(needsAttention(app())).toBe(false);
  });

  it('shows hosts without the scheme', () => {
    expect(hostOf('https://sonarr.example.com/')).toBe('sonarr.example.com');
    expect(hostOf('not a url')).toBe('not a url');
  });
});
