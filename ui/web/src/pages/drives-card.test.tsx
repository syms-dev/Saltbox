import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Drive, DriveHealth } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { DrivesCard, driveAttention, formatDriveSize, formatPowerOn, verdict } from './drives-card';

function drive(overrides: Partial<Drive> = {}): Drive {
  return {
    capacity: 8_001_563_222_016,
    checked_at: new Date().toISOString(),
    failed_scrutiny: false,
    failed_smart: false,
    healthy: true,
    id: 'wwn-a',
    kind: 'HDD',
    label: '',
    model: 'ST8000VN004',
    name: '/dev/sda',
    power_on_hours: 26_298,
    serial: 'WKD0',
    temperature: 34,
    ...overrides,
  };
}

const FAILING = drive({ failed_smart: true, healthy: false, id: 'wwn-b', name: '/dev/sdb' });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('drive helpers', () => {
  it('formats sizes as drives are sold, and age in the unit that fits', () => {
    expect(formatDriveSize(8_001_563_222_016)).toBe('8.0 TB');
    expect(formatDriveSize(500_107_862_016)).toBe('500 GB');
    expect(formatDriveSize(0)).toBe('');
    expect(formatPowerOn(26_298)).toBe('3.0 years');
    expect(formatPowerOn(1080)).toBe('45 days');
    expect(formatPowerOn(1)).toBe('1 hour');
  });

  it('says which check a drive fails', () => {
    expect(verdict(drive())).toBe('Healthy');
    expect(verdict(FAILING)).toBe('Failing its own SMART check');
    expect(verdict(drive({ failed_scrutiny: true, healthy: false }))).toBe('Failing Scrutiny’s thresholds');
    expect(verdict(drive({ failed_scrutiny: true, failed_smart: true, healthy: false }))).toContain('and Scrutiny’s');
  });

  it('raises failing drives as urgent, and nothing for healthy ones or without Scrutiny', () => {
    expect(driveAttention(undefined)).toEqual([]);
    expect(driveAttention({ drives: [drive()], error: '', installed: true })).toEqual([]);
    const [item] = driveAttention({ drives: [FAILING, drive()], error: '', installed: true });
    expect(item).toMatchObject({
      actions: [{ kind: 'link', label: 'Drive health', to: '/system#drives' }],
      id: 'drive:wwn-b',
      title: 'Drive /dev/sdb is failing its health check',
      tone: 'danger',
    });
    expect(item?.detail).toContain('ST8000VN004 · 8.0 TB. Failing its own SMART check.');
  });
});

describe('DrivesCard', () => {
  function show(health: DriveHealth): void {
    stubApi({ '/apps': [], '/drives': health });
    renderAt(<DrivesCard />);
  }

  it('shows each drive with its verdict, temperature and age', async () => {
    show({
      drives: [FAILING, drive({ checked_at: null, power_on_hours: null, temperature: null })],
      error: '',
      installed: true,
    });
    const card = await screen.findByRole('region', { name: 'Drive health' });
    expect(within(card).getByRole('alert')).toHaveTextContent('1 of 2 drives is failing');
    const [failing, unread] = within(card).getAllByRole('listitem');
    expect(failing).toHaveTextContent('/dev/sdb');
    expect(failing).toHaveTextContent('Failing its own SMART check');
    expect(failing).toHaveTextContent('34 °C');
    expect(failing).toHaveTextContent('3.0 years');
    expect(unread).toHaveTextContent('Healthy');
    expect(unread).toHaveTextContent('not yet');
  });

  it('says all is well in one line when it is', async () => {
    show({ drives: [drive(), drive({ id: 'wwn-c', name: '/dev/sdc' })], error: '', installed: true });
    const card = await screen.findByRole('region', { name: 'Drive health' });
    expect(card).toHaveTextContent('All 2 drives are healthy');
    expect(within(card).queryByRole('alert')).toBeNull();
  });

  it('says why there is nothing to show when Scrutiny does not answer', async () => {
    show({ drives: [], error: 'scrutiny: Bad Gateway', installed: true });
    expect(await screen.findByRole('region', { name: 'Drive health' })).toHaveTextContent(
      'Scrutiny did not answer: scrutiny: Bad Gateway',
    );
  });

  it('is not there at all without Scrutiny', async () => {
    const api = stubApi({ '/apps': [], '/drives': { drives: [], error: '', installed: false } });
    renderAt(<DrivesCard />);
    await vi.waitFor(() => expect(api).toHaveBeenCalledWith('/api/drives', expect.anything()));
    expect(screen.queryByRole('region', { name: 'Drive health' })).toBeNull();
  });
});
