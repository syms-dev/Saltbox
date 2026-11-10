import type { App, ContainerState } from '../api/types';

export type Tone = 'danger' | 'muted' | 'ok' | 'warn';

export type Health = { label: string; tone: Tone };

/** How one container is doing, in words a person scanning a list understands. */
export function containerHealth(container: Pick<ContainerState, 'health' | 'status'>): Health {
  if (container.status !== 'running') {
    return container.status === 'restarting'
      ? { label: 'Restarting', tone: 'warn' }
      : { label: 'Stopped', tone: 'muted' };
  }
  if (container.health === 'unhealthy') return { label: 'Unhealthy', tone: 'danger' };
  if (container.health === 'starting') return { label: 'Starting', tone: 'warn' };
  return { label: 'Running', tone: 'ok' };
}

const RANK: Record<Tone, number> = { danger: 3, muted: 1, ok: 0, warn: 2 };

/** The worst state across an app's containers; an app with none is "Not running". */
export function appHealth(app: Pick<App, 'containers'>): Health {
  if (app.containers.length === 0) return { label: 'Not running', tone: 'muted' };
  const states = app.containers.map(containerHealth);
  const worst = states.reduce((a, b) => (RANK[b.tone] > RANK[a.tone] ? b : a));
  if (worst.tone === 'muted' && states.some((s) => s.tone === 'ok')) return { label: 'Partly stopped', tone: 'warn' };
  return worst;
}

export function needsAttention(app: Pick<App, 'containers'>): boolean {
  const tone = appHealth(app).tone;
  return tone === 'danger' || tone === 'warn' || (tone === 'muted' && app.containers.length > 0);
}

/** "sonarr.example.com" from "https://sonarr.example.com/". */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
