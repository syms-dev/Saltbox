const UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB'] as const;
const KIBI = 1024;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const MS_PER_SECOND = 1000;

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= KIBI && unit < UNITS.length - 1) {
    value /= KIBI;
    unit += 1;
  }
  const digits = unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[unit] ?? 'B'}`;
}

export function formatWhen(iso: string | null): string {
  if (iso === null) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export function formatDuration(start: string | null, end: string | null): string {
  if (start === null) return '';
  const from = new Date(start).getTime();
  const to = end === null ? Date.now() : new Date(end).getTime();
  const seconds = Math.max(0, Math.round((to - from) / MS_PER_SECOND));
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours > 0) return `${hours}h ${minutes % MINUTES_PER_HOUR}m`;
  if (minutes > 0) return `${minutes}m ${seconds % SECONDS_PER_MINUTE}s`;
  return `${seconds}s`;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const RELATIVE_STEPS: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, 'second'],
  [60, 'minute'],
  [24, 'hour'],
  [7, 'day'],
  [4.35, 'week'],
  [12, 'month'],
  [Number.POSITIVE_INFINITY, 'year'],
];

/** "5 minutes ago", "in 2 hours"; accepts an ISO string or epoch seconds. */
export function formatRelative(when: string | number | null, now: number = Date.now()): string {
  if (when === null) return '';
  const time = typeof when === 'number' ? when * MS_PER_SECOND : new Date(when).getTime();
  if (Number.isNaN(time)) return String(when);
  let value = (time - now) / MS_PER_SECOND;
  if (Math.abs(value) < 45) return 'just now';
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  for (const [size, unit] of RELATIVE_STEPS) {
    if (Math.abs(value) < size) return format.format(Math.round(value), unit);
    value /= size;
  }
  return format.format(Math.round(value), 'year');
}

/** "3 days, 4 hours" from seconds; the two largest units. */
export function formatUptime(seconds: number | null): string {
  if (seconds === null) return '';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const part = (n: number, unit: string): string => `${n} ${unit}${n === 1 ? '' : 's'}`;
  if (days > 0) return `${part(days, 'day')}, ${part(hours, 'hour')}`;
  if (hours > 0) return `${part(hours, 'hour')}, ${part(minutes, 'minute')}`;
  return part(minutes, 'minute');
}

/** "12.0 MiB/s" from bytes per second; an em dash for nothing. */
export function formatSpeed(bytesPerSecond: number): string {
  if (bytesPerSecond <= 0) return '—';
  return `${formatBytes(bytesPerSecond)}/s`;
}

/** "Today", "Tomorrow", or "Thu 12 Nov" for a date. */
export function formatDay(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const day = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(date) - day(now)) / 86_400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', weekday: 'short' });
}
