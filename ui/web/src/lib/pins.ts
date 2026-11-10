import { useSyncExternalStore } from 'react';

/** Apps pinned to the top of the launcher, kept in this browser only. */
const KEY = 'saltbox-ui:pinned-apps';
const listeners = new Set<() => void>();
let cache: string[] | null = null;

function read(): string[] {
  if (cache !== null) return cache;
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? '[]');
    cache = Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(next: string[]): void {
  cache = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage blocked: pins last for this visit only
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePins(): { isPinned: (id: string) => boolean; pins: string[]; toggle: (id: string) => void } {
  const pins = useSyncExternalStore(subscribe, read, () => []);
  return {
    isPinned: (id) => pins.includes(id),
    pins,
    toggle: (id) => write(pins.includes(id) ? pins.filter((p) => p !== id) : [...pins, id]),
  };
}
