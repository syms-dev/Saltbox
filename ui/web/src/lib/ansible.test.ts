import { describe, expect, it } from 'vitest';

import { findFailure, lineKind } from './ansible';

const LOG = [
  '$ /usr/local/bin/sb install autoheal',
  'TASK [pre_tasks : Git | Lookup git safe directories] ***',
  'ok: [localhost]',
  'TASK [pre_tasks : Git | Set Saltbox repository as safe directory] ***',
  'fatal: [localhost]: FAILED! => {"changed": true, "msg": "The command exited with a non-zero return code.", "stderr": "fatal: $HOME not set"}',
  'PLAY RECAP ***',
].join('\n');

describe('findFailure', () => {
  it('names the failing task and its message', () => {
    expect(findFailure(LOG)).toEqual({
      line: 4,
      message: 'The command exited with a non-zero return code.',
      task: 'pre_tasks : Git | Set Saltbox repository as safe directory',
    });
  });

  it('falls back to sb errors outside a task', () => {
    const log = '$ sb install autoheal\n\n   ERROR\n\n  failed to update tags cache for /srv/git/saltbox\n';
    expect(findFailure(log)?.message).toBe('failed to update tags cache for /srv/git/saltbox');
  });

  it('finds nothing in a clean run', () => {
    expect(findFailure('TASK [x] ***\nok: [localhost]\nPLAY RECAP ***')).toBeNull();
  });
});

describe('lineKind', () => {
  it('classifies Ansible lines', () => {
    expect(lineKind('TASK [sonarr : Create Docker container] ***')).toBe('task');
    expect(lineKind('changed: [localhost]')).toBe('changed');
    expect(lineKind('fatal: [localhost]: FAILED! => {}')).toBe('error');
    expect(lineKind('[WARNING]: something')).toBe('warn');
    expect(lineKind('PLAY RECAP ***')).toBe('heading');
    expect(lineKind('plain text')).toBe('plain');
  });
});
