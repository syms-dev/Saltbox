import { describe, expect, it } from 'vitest';

import type { MediaSnapshot } from '../api/types';
import { mediaAttention } from './home-media';

const vpn = (overrides: Partial<NonNullable<MediaSnapshot['vpn']>>): MediaSnapshot => ({
  checked_at: 1,
  vpn: {
    available: true,
    configured: true,
    container: 'gluetun',
    qbittorrent_protected: true,
    routed: ['qbittorrent'],
    running: true,
    ...overrides,
  } as NonNullable<MediaSnapshot['vpn']>,
});

describe('mediaAttention', () => {
  it('is quiet while the VPN is up and qBittorrent is behind it', () => {
    expect(mediaAttention(vpn({}))).toEqual([]);
    expect(mediaAttention(undefined)).toEqual([]);
    expect(mediaAttention({ checked_at: 1, vpn: { available: true, configured: false } })).toEqual([]);
  });

  it('offers to start a stopped VPN and names what is offline', () => {
    const [item] = mediaAttention(vpn({ running: false }));
    expect(item?.title).toBe('The VPN (Gluetun) is not running');
    expect(item?.detail).toContain('qbittorrent');
    expect(item?.actions[0]).toEqual({ container: 'gluetun', kind: 'start', label: 'Start' });
  });

  it('warns when qBittorrent leaves through the home connection', () => {
    const [item] = mediaAttention(vpn({ qbittorrent_protected: false }));
    expect(item?.tone).toBe('danger');
    expect(item?.title).toBe('qBittorrent is not behind the VPN');
  });
});
