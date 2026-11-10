import { describe, expect, it } from 'vitest';

import { versionLine } from './shell';

const META = { layout: {}, version: '0.1.0', web: true };

describe('versionLine', () => {
  it('shows the branch and commit', () => {
    expect(versionLine({ ...META, saltbox: { branch: 'main', commit: 'abc1234', remote: null } })).toBe(
      'ui 0.1.0 · main@abc1234',
    );
  });

  it('leaves git out when the daemon could not read it, instead of showing ?@?', () => {
    expect(versionLine({ ...META, saltbox: { branch: null, commit: null, remote: null } })).toBe('ui 0.1.0');
  });
});
