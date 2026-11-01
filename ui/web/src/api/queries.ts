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
  Meta,
  Overview,
} from './types';

export const QUERY_KEYS = {
  APPS: 'apps',
  CONFIG: 'config',
  INVENTORY: 'inventory',
  JOBS: 'jobs',
  META: 'meta',
  OVERVIEW: 'overview',
} as const;

const OVERVIEW_REFRESH_MS = 15_000;
const JOBS_REFRESH_MS = 3_000;

export function useMeta(): UseQueryResult<Meta> {
  return useQuery({ queryFn: () => apiFetch<Meta>(API_ROUTES.META), queryKey: [QUERY_KEYS.META] });
}

export function useOverview(): UseQueryResult<Overview> {
  return useQuery({
    queryFn: () => apiFetch<Overview>(API_ROUTES.OVERVIEW),
    queryKey: [QUERY_KEYS.OVERVIEW],
    refetchInterval: OVERVIEW_REFRESH_MS,
  });
}

export function useApps(): UseQueryResult<App[]> {
  return useQuery({ queryFn: () => apiFetch<App[]>(API_ROUTES.APPS), queryKey: [QUERY_KEYS.APPS] });
}

export function useAppDetail(repo: string, role: string): UseQueryResult<AppDetail> {
  return useQuery({
    queryFn: () => apiFetch<AppDetail>(API_ROUTES.appDetail(repo, role)),
    queryKey: [QUERY_KEYS.APPS, repo, role],
  });
}

export function useJobs(): UseQueryResult<JobsResponse> {
  return useQuery({
    queryFn: () => apiFetch<JobsResponse>(API_ROUTES.JOBS),
    queryKey: [QUERY_KEYS.JOBS],
    refetchInterval: JOBS_REFRESH_MS,
  });
}

export function useJob(id: string): UseQueryResult<Job> {
  return useQuery({
    queryFn: () => apiFetch<Job>(API_ROUTES.job(id)),
    queryKey: [QUERY_KEYS.JOBS, id],
    refetchInterval: (query) => (query.state.data?.status === 'running' ? JOBS_REFRESH_MS : false),
  });
}

export function useConfigFiles(): UseQueryResult<ConfigFileSummary[]> {
  return useQuery({
    queryFn: () => apiFetch<ConfigFileSummary[]>(API_ROUTES.CONFIG),
    queryKey: [QUERY_KEYS.CONFIG],
  });
}

export function useConfigFile(name: string): UseQueryResult<ConfigFile> {
  return useQuery({
    queryFn: () => apiFetch<ConfigFile>(API_ROUTES.configFile(name)),
    queryKey: [QUERY_KEYS.CONFIG, name],
  });
}

export function useInventory(): UseQueryResult<Inventory> {
  return useQuery({ queryFn: () => apiFetch<Inventory>(API_ROUTES.INVENTORY), queryKey: [QUERY_KEYS.INVENTORY] });
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
