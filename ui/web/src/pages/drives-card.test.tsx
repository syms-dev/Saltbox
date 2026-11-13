import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Drive, DriveHealth } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { DrivesCard, attributeLine, driveAttention, formatDriveSize, formatPowerOn, verdict } from './drives-card';

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

const REALLOCATED = {
  critical: true,
  description: 'Count of reallocated sectors.',
  failed_scrutiny: true,
  failed_smart: false,
  failure_rate: 0.1423,
  id: '5',
  name: 'Reallocated Sectors Count',
  reason: 'Observed Failure Rate for Critical Attribute is greater than 10%',
  value: 24,
};
const CRC = {
  ...REALLOCATED,
  critical: false,
  failed_scrutiny: false,
  failed_smart: true,
  failure_rate: null,
  id: '199',
  name: 'UltraDMA CRC Error Count',
  value: 3,
};

const FAILING = drive({
  failed_smart: true,
  failing: [REALLOCATED, CRC],
  healthy: false,
  id: 'wwn-b',
  key: 'drive:wwn-b:smart:199,5',
  name: '/dev/sdb',
});

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
    expect(item?.detail).toContain(
      'ST8000VN004 · 8.0 TB. Reallocated Sectors Count is 24, UltraDMA CRC Error Count is 3.',
    );
    // Dismissed: still failing, no longer raised.
    expect(driveAttention({ drives: [{ ...FAILING, dismissed: true }], error: '', installed: true })).toEqual([]);
  });

  it('says in plain words why an attribute counts as failing', () => {
    expect(attributeLine(REALLOCATED)).toBe(
      'Reallocated Sectors Count is 24: drives with this value fail about 14% of the time',
    );
    expect(attributeLine(CRC)).toBe('UltraDMA CRC Error Count is 3: past the limit the drive’s maker set');
    expect(attributeLine({ ...REALLOCATED, failure_rate: null, value: null })).toBe(
      'Reallocated Sectors Count: Observed Failure Rate for Critical Attribute is greater than 10%',
    );
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
    // The drives themselves, not the attributes listed inside a failing one.
    const rows = [...within(card).getByRole('list', { name: 'Drives' }).children];
    const [failing, unread] = rows;
    expect(failing).toHaveTextContent('/dev/sdb');
    expect(failing).toHaveTextContent('Failing its own SMART check');
    expect(failing).toHaveTextContent('34 °C');
    expect(failing).toHaveTextContent('3.0 years');
    expect(failing).toHaveTextContent('Reallocated Sectors Count is 24');
    expect(failing).toHaveTextContent('critical');
    expect(unread).toHaveTextContent('Healthy');
    expect(unread).toHaveTextContent('not yet');
    expect(within(unread as HTMLElement).queryByRole('button', { name: 'Dismiss' })).toBeNull();
  });

  it('dismisses a failing drive on the server and offers to show it again', async () => {
    let dismissed = false;
    const api = stubApi({
      'POST /dismissals': () => {
        dismissed = true;
        return { dismissed: true };
      },
      '/apps': [],
      '/drives': () => ({ drives: [{ ...FAILING, dismissed }], error: '', installed: true }),
    });
    renderAt(<DrivesCard />);
    const card = await screen.findByRole('region', { name: 'Drive health' });
    fireEvent.click(await within(card).findByRole('button', { name: 'Dismiss' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/dismissals',
        expect.objectContaining({ body: JSON.stringify({ key: 'drive:wwn-b:smart:199,5', label: '/dev/sdb' }) }),
      ),
    );
    expect(await within(card).findByRole('button', { name: 'Show on Home again' })).toBeInTheDocument();
    expect(card).toHaveTextContent('1 of 1 drive is failing (dismissed)');
    expect(within(card).queryByRole('alert')).toBeNull();
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
