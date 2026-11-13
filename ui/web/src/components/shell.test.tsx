import { describe, expect, it } from 'vitest';

import { versionLines } from './shell';

const META = { layout: {}, version: '0.1.0', web: true };

describe('versionLines', () => {
  it('names this app and the Saltbox commit, without a branch everybody is on', () => {
    expect(versionLines({ ...META, saltbox: { branch: 'master', commit: 'abc1234def', remote: null } })).toEqual({
      saltbox: 'Saltbox abc1234',
      ui: 'Saltbox UI 0.1.0',
    });
  });

  it('adds the branch when it is not the default one', () => {
    const meta = { ...META, saltbox: { branch: 'claude/saltbox-gui-tui-bxul3c', commit: '82bb69e0', remote: null } };
    expect(versionLines(meta).saltbox).toBe('Saltbox 82bb69e · claude/saltbox-gui-tui-bxul3c');
    expect(versionLines({ ...META, saltbox: { branch: null, commit: '82bb69e0', remote: null } }).saltbox).toBe(
      'Saltbox 82bb69e · no branch',
    );
  });

  it('leaves git out when the daemon could not read it', () => {
    expect(versionLines({ ...META, saltbox: { branch: null, commit: null, remote: null } })).toEqual({
      saltbox: null,
      ui: 'Saltbox UI 0.1.0',
    });
  });
});
