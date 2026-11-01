import type { JobRequest } from './types';

const BASE = '/api';

export const API_ROUTES = {
  APPS: '/apps',
  CONFIG: '/config',
  CONFIG_VALIDATE: '/config/validate',
  INVENTORY: '/inventory',
  JOBS: '/jobs',
  META: '/meta',
  OVERVIEW: '/overview',
  appDetail: (repo: string, role: string) => `/apps/${repo}/${role}` as const,
  appOverrides: (repo: string, role: string) => `/apps/${repo}/${role}/overrides` as const,
  configFile: (name: string) => `/config/${name}` as const,
  job: (id: string) => `/jobs/${id}` as const,
  jobCancel: (id: string) => `/jobs/${id}/cancel` as const,
  jobLog: (id: string) => `/jobs/${id}/log` as const,
  jobStream: (id: string) => `/jobs/${id}/stream` as const,
} as const;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

type ErrorBody = { detail?: unknown; error?: unknown };

function describe(body: ErrorBody | null, fallback: string): string {
  const detail = body?.detail ?? body?.error;
  if (typeof detail === 'string') return detail;
  if (detail !== undefined) return JSON.stringify(detail);
  return fallback;
}

/** Fetch JSON from the daemon. Throws `ApiError` for non-2xx responses. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('Accept', 'application/json');
  if (init?.body !== undefined && init.body !== null) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let body: ErrorBody | null = null;
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      body = null;
    }
    throw new ApiError(response.status, describe(body, `${response.status} ${response.statusText}`));
  }
  return (await response.json()) as T;
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: 'POST' };
  if (body !== undefined) init.body = JSON.stringify(body);
  return apiFetch<T>(path, init);
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { body: JSON.stringify(body), method: 'PUT' });
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { body: JSON.stringify(body), method: 'PATCH' });
}

/** Absolute WebSocket URL for a job's log stream, matching the page's scheme and host. */
export function jobStreamUrl(id: string, location: Pick<Location, 'host' | 'protocol'> = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}${BASE}${API_ROUTES.jobStream(id)}`;
}

export function installRequest(tags: string[], options: Partial<JobRequest> = {}): JobRequest {
  return { kind: 'install', tags, ...options };
}
