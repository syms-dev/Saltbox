import { describe, expect, it } from 'vitest';

import { formatRelative } from './format';

describe('formatRelative', () => {
  const now = Date.parse('2026-11-10T12:00:00Z');
  it('says just now, minutes and hours ago', () => {
    expect(formatRelative('2026-11-10T11:59:50Z', now)).toBe('just now');
    expect(formatRelative('2026-11-10T11:55:00Z', now)).toMatch(/5 minutes ago/);
    expect(formatRelative(now / 1000 - 7200, now)).toMatch(/2 hours ago/);
    expect(formatRelative(null, now)).toBe('');
  });
});
