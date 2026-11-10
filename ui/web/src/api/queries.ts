import { useEffect, useRef } from 'react';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { API_ROUTES, apiFetch, apiPost, apiPut } from './client';
import type {
  App,
  AppDetail,
  ConfigFile,
  ConfigFileSummary,
  Inventory,
  Issue,
  Job,
  JobRequest,
  JobsResponse,
  MediaSnapshot,
  Meta,
  AutomationSettings,
  AutomationStatus,
  BackupSummary,
  ContainerAction,
  ContainerLogs,
  ContainerState,
  Overview,
  RecyclarrStatus,
  Resources,
  SetupResponse,
  TailscaleStatus,
  UpdatesResponse,
} from './types';

export const QUERY_KEYS = {
  APPS: 'apps',
  CONFIG: 'config',
  INVENTORY: 'inventory',
  JOBS: 'jobs',
  META: 'meta',
  BACKUPS: 'backups',
  LOGS: 'logs',
  OVERVIEW: 'overview',
  SETUP: 'setup',
  UPDATES: 'updates',
} as const;

const OVERVIEW_REFRESH_MS = 15_000;
const JOBS_REFRESH_MS = 3_000;

export function useMeta(): UseQueryResult<Meta> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<Meta>(API_ROUTES.META, { signal }),
    queryKey: [QUERY_KEYS.META],
  });
}

export function useOverview(): UseQueryResult<Overview> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<Overview>(API_ROUTES.OVERVIEW, { signal }),
    queryKey: [QUERY_KEYS.OVERVIEW],
    refetchInterval: OVERVIEW_REFRESH_MS,
  });
}

export function useApps(): UseQueryResult<App[]> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<App[]>(API_ROUTES.APPS, { signal }),
    queryKey: [QUERY_KEYS.APPS],
  });
}

export function useAppDetail(repo: string, role: string, reveal = false): UseQueryResult<AppDetail> {
  return useQuery({
    placeholderData: (previous) => previous,
    queryFn: ({ signal }) =>
      apiFetch<AppDetail>(`${API_ROUTES.appDetail(repo, role)}${reveal ? '?reveal=true' : ''}`, { signal }),
    queryKey: [QUERY_KEYS.APPS, repo, role, reveal],
  });
}

export function useJobs(): UseQueryResult<JobsResponse> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<JobsResponse>(API_ROUTES.JOBS, { signal }),
    queryKey: [QUERY_KEYS.JOBS],
    refetchInterval: JOBS_REFRESH_MS,
  });
}

export function useJob(id: string): UseQueryResult<Job> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<Job>(API_ROUTES.job(id), { signal }),
    queryKey: [QUERY_KEYS.JOBS, id],
    refetchInterval: (query) => (query.state.data?.status === 'running' ? JOBS_REFRESH_MS : false),
  });
}

export function useConfigFiles(): UseQueryResult<ConfigFileSummary[]> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<ConfigFileSummary[]>(API_ROUTES.CONFIG, { signal }),
    queryKey: [QUERY_KEYS.CONFIG],
  });
}

export function useConfigFile(name: string, reveal = false): UseQueryResult<ConfigFile> {
  return useQuery({
    queryFn: ({ signal }) =>
      apiFetch<ConfigFile>(`${API_ROUTES.configFile(name)}${reveal ? '?reveal=true' : ''}`, { signal }),
    queryKey: [QUERY_KEYS.CONFIG, name, reveal],
  });
}

export function useInventory(reveal = false): UseQueryResult<Inventory> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<Inventory>(`${API_ROUTES.INVENTORY}${reveal ? '?reveal=true' : ''}`, { signal }),
    queryKey: [QUERY_KEYS.INVENTORY, reveal],
  });
}

export function useStartJob(): UseMutationResult<Job, Error, JobRequest> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: JobRequest) => apiPost<Job>(API_ROUTES.JOBS, request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.OVERVIEW] });
    },
  });
}

export function useCancelJob(): UseMutationResult<{ cancelled: boolean }, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<{ cancelled: boolean }>(API_ROUTES.jobCancel(id)),
    onSuccess: () => void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] }),
  });
}

type SaveConfigInput = { name: string; text: string };
type SaveConfigResult = { issues: Issue[]; name: string };

export function useSaveConfig(): UseMutationResult<SaveConfigResult, Error, SaveConfigInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, text }: SaveConfigInput) => apiPut<SaveConfigResult>(API_ROUTES.configFile(name), { text }),
    onSuccess: (_result, { name }) => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.CONFIG, name] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.CONFIG] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.OVERVIEW] });
    },
  });
}

export function useSaveInventory(): UseMutationResult<{ issues: Issue[] }, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => apiPut<{ issues: Issue[] }>(API_ROUTES.INVENTORY, { text }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.INVENTORY] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.APPS] });
    },
  });
}

type OverridesInput = { repo: string; role: string; unset?: string[]; values?: Record<string, unknown> };
type OverridesResult = { overrides: Record<string, Record<string, unknown>>; removed: string[] };

export function useUpdateOverrides(): UseMutationResult<OverridesResult, Error, OverridesInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ repo, role, unset, values }: OverridesInput) =>
      apiPut<OverridesResult>(API_ROUTES.appOverrides(repo, role), { unset: unset ?? [], values: values ?? {} }),
    onSuccess: (_result, { repo, role }) => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.APPS, repo, role] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.APPS] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.INVENTORY] });
    },
  });
}

export function useValidateConfig(): UseMutationResult<Record<string, Issue[]>, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<Record<string, Issue[]>>(API_ROUTES.CONFIG_VALIDATE),
    onSuccess: () => void client.invalidateQueries({ queryKey: [QUERY_KEYS.OVERVIEW] }),
  });
}

const UPDATES_POLL_MS = 3_000;

/** Update status; polls while a check runs, then refreshes the pages that show its results. */
export function useUpdates(): UseQueryResult<UpdatesResponse> {
  const client = useQueryClient();
  const result = useQuery({
    queryFn: ({ signal }) => apiFetch<UpdatesResponse>(API_ROUTES.UPDATES, { signal }),
    queryKey: [QUERY_KEYS.UPDATES],
    refetchInterval: (query) => (query.state.data?.running === true ? UPDATES_POLL_MS : false),
  });
  const checkedAt = result.data?.checked_at ?? null;
  const seen = useRef(checkedAt);
  useEffect(() => {
    if (checkedAt === seen.current) return;
    seen.current = checkedAt;
    // A first load still in flight would otherwise be reused as is, from before the check.
    for (const key of [QUERY_KEYS.OVERVIEW, QUERY_KEYS.APPS]) {
      void client.cancelQueries({ queryKey: [key] }).then(() => client.invalidateQueries({ queryKey: [key] }));
    }
  }, [checkedAt, client]);
  return result;
}

function invalidateUpdates(client: ReturnType<typeof useQueryClient>): void {
  void client.invalidateQueries({ queryKey: [QUERY_KEYS.UPDATES] });
  void client.invalidateQueries({ queryKey: [QUERY_KEYS.APPS] });
  void client.invalidateQueries({ queryKey: [QUERY_KEYS.OVERVIEW] });
  void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] });
}

export function useCheckUpdates(): UseMutationResult<UpdatesResponse, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<UpdatesResponse>(API_ROUTES.UPDATES_CHECK),
    onSuccess: () => invalidateUpdates(client),
  });
}

type UpdateAppInput = { repo: string; role: string };

export function useUpdateApp(): UseMutationResult<Job, Error, UpdateAppInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ repo, role }: UpdateAppInput) => apiPost<Job>(API_ROUTES.appUpdate(repo, role)),
    onSuccess: () => invalidateUpdates(client),
  });
}

export function useUpdateAll(): UseMutationResult<Job, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<Job>(API_ROUTES.UPDATES_APPLY),
    onSuccess: () => invalidateUpdates(client),
  });
}

/** `sb update`: brings the Saltbox checkouts up to their branches. */
export function useUpdateSaltbox(): UseMutationResult<Job, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<Job>(API_ROUTES.SALTBOX_UPDATE),
    onSuccess: () => invalidateUpdates(client),
  });
}

type ContainerActionInput = { action: ContainerAction; name: string };

/** Start, stop or restart a container; refreshes everything that shows container state. */
export function useContainerAction(): UseMutationResult<ContainerState, Error, ContainerActionInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ action, name }: ContainerActionInput) =>
      apiPost<ContainerState>(API_ROUTES.containerAction(name, action)),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.APPS] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.OVERVIEW] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.LOGS] });
    },
  });
}

const LOGS_LIVE_MS = 4_000;

export function useContainerLogs(name: string, tail: number, live: boolean): UseQueryResult<ContainerLogs> {
  return useQuery({
    enabled: name !== '',
    queryFn: ({ signal }) => apiFetch<ContainerLogs>(API_ROUTES.containerLogs(name, tail), { signal }),
    queryKey: [QUERY_KEYS.LOGS, name, tail],
    refetchInterval: live ? LOGS_LIVE_MS : false,
  });
}

export function useSetup(reveal = false): UseQueryResult<SetupResponse> {
  return useQuery({
    placeholderData: (previous) => previous,
    queryFn: ({ signal }) => apiFetch<SetupResponse>(`${API_ROUTES.SETUP}${reveal ? '?reveal=true' : ''}`, { signal }),
    queryKey: [QUERY_KEYS.SETUP, reveal],
  });
}

export function useApplySetup(): UseMutationResult<SetupResponse, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SetupResponse>(API_ROUTES.SETUP_APPLY),
    onSuccess: () => void client.invalidateQueries({ queryKey: [QUERY_KEYS.SETUP] }),
  });
}

const RESOURCES_REFRESH_MS = 10_000;

export function useResources(): UseQueryResult<Resources> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<Resources>(API_ROUTES.RESOURCES, { signal }),
    queryKey: ['resources'],
    refetchInterval: RESOURCES_REFRESH_MS,
  });
}

export function useTailscale(): UseQueryResult<TailscaleStatus> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<TailscaleStatus>(API_ROUTES.TAILSCALE, { signal }),
    queryKey: ['tailscale'],
  });
}

export function useBackups(): UseQueryResult<BackupSummary> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<BackupSummary>(API_ROUTES.BACKUPS, { signal }),
    queryKey: [QUERY_KEYS.BACKUPS],
  });
}

export function useRunBackup(): UseMutationResult<Job, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<Job>(API_ROUTES.BACKUPS_RUN),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.BACKUPS] });
    },
  });
}

const MEDIA_REFRESH_MS = 15_000;

export function useMedia(): UseQueryResult<MediaSnapshot> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<MediaSnapshot>(API_ROUTES.MEDIA, { signal }),
    queryKey: ['media'],
    refetchInterval: MEDIA_REFRESH_MS,
  });
}

export function useRecyclarr(): UseQueryResult<RecyclarrStatus> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<RecyclarrStatus>(API_ROUTES.RECYCLARR, { signal }),
    queryKey: ['recyclarr'],
  });
}

type RecyclarrSelection = { radarr: string[]; sonarr: string[] };

export function useSaveRecyclarr(): UseMutationResult<{ backup: string | null }, Error, RecyclarrSelection> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (selection: RecyclarrSelection) => apiPut<{ backup: string | null }>(API_ROUTES.RECYCLARR, selection),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['recyclarr'] }),
  });
}

export function useRecyclarrSync(): UseMutationResult<Job, Error, { preview: boolean }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { preview: boolean }) => apiPost<Job>(API_ROUTES.RECYCLARR_SYNC, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['recyclarr'] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] });
    },
  });
}

export function useAutomation(): UseQueryResult<AutomationStatus> {
  return useQuery({
    queryFn: ({ signal }) => apiFetch<AutomationStatus>(API_ROUTES.AUTOMATION, { signal }),
    queryKey: ['automation'],
    refetchInterval: 30_000,
  });
}

type AutomationChange = {
  alerts?: Partial<AutomationSettings['alerts']>;
  maintenance?: Partial<AutomationSettings['maintenance']>;
};

export function useSaveAutomation(): UseMutationResult<AutomationStatus, Error, AutomationChange> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (change: AutomationChange) => apiPut<AutomationStatus>(API_ROUTES.AUTOMATION, change),
    onSuccess: (data) => client.setQueryData(['automation'], data),
  });
}

export function useTestAlert(): UseMutationResult<{ message: string; ok: boolean }, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ message: string; ok: boolean }>(API_ROUTES.AUTOMATION_TEST),
    onSettled: () => void client.invalidateQueries({ queryKey: ['automation'] }),
  });
}

export function useRunMaintenance(): UseMutationResult<{ started: boolean }, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ started: boolean }>(API_ROUTES.AUTOMATION_MAINTENANCE),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['automation'] });
      void client.invalidateQueries({ queryKey: [QUERY_KEYS.JOBS] });
    },
  });
}
