import type { App, Issue, Overview } from '../api/types';
import { jobTitle } from '../components/shell';
import { formatBytes } from '../format';

const DISK_WARN_PERCENT = 85;
const DISK_DANGER_PERCENT = 95;

export type AttentionAction =
  | { kind: 'link'; label: string; to: string }
  | { kind: 'logs'; container: string; label: string; to: string }
  | { container: string; kind: 'restart' | 'start'; label: string }
  | { app: App; kind: 'update'; label: string }
  | { apps: App[]; kind: 'updateAll'; label: string }
  | { kind: 'sbUpdate'; label: string }
  | { jobId: string; kind: 'retry'; label: string };

export type Attention = {
  actions: AttentionAction[];
  detail?: string | undefined;
  id: string;
  title: string;
  tone: 'danger' | 'info' | 'warn';
};

function appFor(apps: App[], container: string): App | undefined {
  return apps.find((app) => app.installed && app.containers.some((c) => c.name === container));
}

/**
 * Everything on the server that needs a person, most urgent first, each with the action
 * that fixes it (restart, update, open the failing file, retry the job).
 */
export function attentionItems(data: Overview, apps: App[] = []): Attention[] {
  const items: Attention[] = [];
  if (!data.containers.available) {
    items.push({
      actions: [],
      detail: 'The daemon cannot reach Docker, so app status is unknown.',
      id: 'docker',
      title: 'Docker is not reachable',
      tone: 'danger',
    });
  }
  for (const name of data.containers.unhealthy) {
    const app = appFor(apps, name);
    items.push({
      actions: [
        { container: name, kind: 'restart', label: 'Restart' },
        {
          container: name,
          kind: 'logs',
          label: 'View logs',
          to: app ? `/apps/${app.repo}/${app.role}?tab=logs` : '/apps',
        },
      ],
      detail: 'Its health check is failing.',
      id: `unhealthy:${name}`,
      title: `${app?.title ?? name} is unhealthy`,
      tone: 'danger',
    });
  }
  for (const name of data.containers.stopped) {
    const app = appFor(apps, name);
    items.push({
      actions: [
        { container: name, kind: 'start', label: 'Start' },
        {
          container: name,
          kind: 'logs',
          label: 'View logs',
          to: app ? `/apps/${app.repo}/${app.role}?tab=logs` : '/apps',
        },
      ],
      id: `stopped:${name}`,
      title: `${app?.title ?? name} is not running`,
      tone: 'warn',
    });
  }
  const last = data.jobs.recent[0];
  if (last !== undefined && last.status === 'failed') {
    items.push({
      actions: [
        { kind: 'link', label: 'See what failed', to: `/activity/${last.id}` },
        { jobId: last.id, kind: 'retry', label: 'Run again' },
      ],
      id: `job:${last.id}`,
      title: `The last job failed: ${jobTitle(last)}`,
      tone: 'danger',
    });
  }
  const broken = Object.entries(data.config_issues)
    .map(([file, issues]) => ({ errors: issues.filter((i: Issue) => i.level === 'error'), file }))
    .filter((entry) => entry.errors.length > 0);
  const fileLabel = (file: string): string => (file === 'inventory' ? 'Inventory' : `${file}.yml`);
  if (broken.length > 2) {
    const count = broken.reduce((sum, entry) => sum + entry.errors.length, 0);
    items.push({
      actions: [{ kind: 'link', label: 'Review', to: `/config/${broken[0]?.file ?? 'accounts'}` }],
      detail: broken.map((entry) => fileLabel(entry.file)).join(', '),
      id: 'config',
      title: `${count} config errors in ${broken.length} files`,
      tone: 'danger',
    });
  } else {
    for (const { errors, file } of broken) {
      const first = errors[0];
      items.push({
        actions: [{ kind: 'link', label: 'Open the file', to: `/config/${file}` }],
        detail: first === undefined ? undefined : `${first.path || 'file'}: ${first.message}`,
        id: `config:${file}`,
        title: `${fileLabel(file)} has ${errors.length} error${errors.length === 1 ? '' : 's'}`,
        tone: 'danger',
      });
    }
  }
  for (const disk of data.host.disks) {
    if (disk.percent >= DISK_WARN_PERCENT) {
      items.push({
        actions: [{ kind: 'link', label: 'Storage', to: '/system' }],
        detail: `${formatBytes(disk.free)} free of ${formatBytes(disk.total)}`,
        id: `disk:${disk.path}`,
        title: `${disk.path} is ${disk.percent}% full`,
        tone: disk.percent >= DISK_DANGER_PERCENT ? 'danger' : 'warn',
      });
    }
  }
  const pending = data.updates?.pending ?? [];
  if (pending.length > 0) {
    const pendingApps = apps.filter((app) => app.installed && app.update_available);
    const names = pendingApps.length > 0 ? pendingApps.map((a) => a.title) : pending;
    items.push({
      actions:
        pendingApps.length === 1 && pendingApps[0] !== undefined
          ? [{ app: pendingApps[0], kind: 'update', label: 'Update' }]
          : [
              { apps: pendingApps, kind: 'updateAll', label: 'Update all' },
              { kind: 'link', label: 'Review', to: '/apps?show=updates' },
            ],
      detail: names.join(', '),
      id: 'updates',
      title: `${names.length} app update${names.length === 1 ? '' : 's'} available`,
      tone: 'info',
    });
  }
  const saltbox = data.updates?.saltbox ?? [];
  if (saltbox.length > 0) {
    items.push({
      actions: [{ kind: 'sbUpdate', label: 'Run sb update' }],
      detail: `New commits for ${saltbox.join(', ')}`,
      id: 'saltbox',
      title: 'Saltbox update available',
      tone: 'info',
    });
  }
  if (data.host.reboot_required) {
    items.push({
      actions: [],
      detail: 'Ubuntu installed updates that need a restart of the server.',
      id: 'reboot',
      title: 'A reboot is pending',
      tone: 'warn',
    });
  }
  if (!data.install.installed) {
    items.push({
      actions: [],
      detail: 'Run the installer (saltbox-ui) on the server first.',
      id: 'install',
      title: 'Saltbox is not installed on this server yet',
      tone: 'warn',
    });
  }
  return items;
}
