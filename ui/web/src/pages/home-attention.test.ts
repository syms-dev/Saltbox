import { describe, expect, it } from 'vitest';

import type { Overview } from '../api/types';
import { makeApp } from '../test-utils';
import { attentionItems } from './home-attention';

const GIB = 1024 ** 3;

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    config_issues: {},
    containers: { available: true, running: 3, stopped: [], total: 3, unhealthy: [] },
    host: {
      disks: [{ free: 50 * GIB, path: '/', percent: 50, total: 100 * GIB, used: 50 * GIB }],
      mounts: [],
      reboot_required: false,
      units: [],
    },
    install: { configs_present: true, installed: true, roles_with_facts: [] },
    jobs: { busy: false, current: null, lock: null, recent: [] },
    services: [],
    updates: { checked_at: null, pending: [], running: false },
    ...overrides,
  };
}

const sonarr = makeApp({
  containers: [
    {
      health: 'unhealthy',
      image: 'x',
      name: 'sonarr',
      status: 'running',
      update: 'update',
      update_detail: '',
      urls: [],
    },
  ],
  installed: true,
  update_available: true,
});

describe('attentionItems', () => {
  it('is empty on a healthy server', () => {
    expect(attentionItems(overview())).toEqual([]);
  });

  it('offers a restart and the logs for an unhealthy app, by its name', () => {
    const [item] = attentionItems(
      overview({ containers: { available: true, running: 3, stopped: [], total: 3, unhealthy: ['sonarr'] } }),
      [sonarr],
    );
    expect(item?.title).toBe('Sonarr is unhealthy');
    expect(item?.actions.map((a) => a.kind)).toEqual(['restart', 'logs']);
    expect(item?.actions[1]).toMatchObject({ to: '/apps/saltbox/sonarr?tab=logs' });
  });

  it('puts problems before updates and offers the fix for each', () => {
    const items = attentionItems(
      overview({
        config_issues: { accounts: [{ level: 'error', message: 'required', path: 'user.email' }] },
        containers: { available: true, running: 2, stopped: ['plex'], total: 3, unhealthy: [] },
        host: {
          disks: [{ free: 2 * GIB, path: '/', percent: 98, total: 100 * GIB, used: 98 * GIB }],
          mounts: [],
          reboot_required: true,
          units: [],
        },
        updates: { checked_at: 1, pending: ['sonarr'], running: false, saltbox: ['saltbox'] },
      }),
      [sonarr],
    );
    expect(items.map((i) => i.id)).toEqual([
      'stopped:plex',
      'config:accounts',
      'disk:/',
      'updates',
      'saltbox',
      'reboot',
    ]);
    expect(items.find((i) => i.id === 'config:accounts')?.detail).toBe('user.email: required');
    expect(items.find((i) => i.id === 'updates')?.actions[0]?.kind).toBe('update');
    expect(items.find((i) => i.id === 'saltbox')?.actions[0]?.kind).toBe('sbUpdate');
    expect(items.find((i) => i.id === 'disk:/')?.tone).toBe('danger');
  });

  it('folds errors in several config files into one item', () => {
    const issue = [{ level: 'error' as const, message: 'missing', path: '' }];
    const items = attentionItems(overview({ config_issues: { a: issue, b: issue, c: issue } }));
    expect(items).toHaveLength(1);
    expect(items[0]?.title).toBe('3 config errors in 3 files');
    expect(items[0]?.detail).toBe('a.yml, b.yml, c.yml');
  });

  it('links a failed last job and offers to run it again', () => {
    const items = attentionItems(
      overview({
        jobs: {
          busy: false,
          current: null,
          lock: null,
          recent: [
            {
              command: ['/usr/local/bin/sb', 'install', 'autoheal'],
              command_line: '/usr/local/bin/sb install autoheal',
              finished_at: null,
              id: 'abc',
              kind: 'install',
              log_path: null,
              returncode: 2,
              started_at: null,
              status: 'failed',
              tags: ['autoheal'],
            },
          ],
        },
      }),
    );
    expect(items[0]?.title).toBe('The last job failed: sb install autoheal');
    expect(items[0]?.actions.map((a) => a.kind)).toEqual(['link', 'retry']);
  });

  it('says when Docker is out of reach', () => {
    const [item] = attentionItems(
      overview({ containers: { available: false, running: 0, stopped: [], total: 0, unhealthy: [] } }),
    );
    expect(item?.title).toBe('Docker is not reachable');
  });
});
