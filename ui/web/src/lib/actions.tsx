import { useNavigate } from 'react-router-dom';

import { useContainerAction, useStartJob, useUpdateAll, useUpdateApp, useUpdateSaltbox } from '../api/queries';
import type { App, ContainerAction, Job } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';

export function appTag(app: Pick<App, 'install_tag' | 'role' | 'sb_tag'>): string {
  return app.sb_tag ?? app.install_tag ?? app.role;
}

/**
 * The job-starting actions every page shares: each asks first, says what will happen in
 * plain words, starts the job, and offers the live log.
 */
export function useJobActions(): {
  install: (app: App, reinstall?: boolean) => Promise<void>;
  updateAll: (apps: App[]) => Promise<void>;
  updateApp: (app: App) => Promise<void>;
  updateSaltbox: () => Promise<void>;
} {
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();
  const start = useStartJob();
  const one = useUpdateApp();
  const all = useUpdateAll();
  const saltbox = useUpdateSaltbox();

  function started(title: string): (job: Job) => void {
    return (job) => {
      toast({ href: `/activity/${job.id}`, linkLabel: 'Watch the log', title, tone: 'info' });
      void navigate(`/activity/${job.id}`);
    };
  }

  function failed(error: Error): void {
    toast({ body: error.message, title: 'Could not start the job', tone: 'danger' });
  }

  return {
    install: async (app, reinstall = false) => {
      const tag = appTag(app);
      const ok = await confirm({
        body: (
          <>
            <p>
              Runs <code>sb install {tag}</code>.{' '}
              {reinstall
                ? 'The container is recreated with its current settings and inventory overrides; its data stays.'
                : 'Saltbox creates the container, its folders under /opt and its address on your domain.'}
            </p>
            <p>It usually takes a minute or two. You can follow the log while it runs.</p>
          </>
        ),
        confirmLabel: reinstall ? `Reinstall ${app.title}` : `Install ${app.title}`,
        title: reinstall ? `Reinstall ${app.title}?` : `Install ${app.title}?`,
      });
      if (!ok) return;
      start.mutate(
        { kind: 'install', tags: [tag] },
        { onError: failed, onSuccess: started(`${reinstall ? 'Reinstalling' : 'Installing'} ${app.title}`) },
      );
    },
    updateAll: async (apps) => {
      const ok = await confirm({
        body: (
          <>
            <p>New images are ready for {apps.map((a) => a.title).join(', ')}.</p>
            <p>Each app is recreated on its new image and is unavailable for a minute or two.</p>
          </>
        ),
        confirmLabel: `Update ${apps.length} app${apps.length === 1 ? '' : 's'}`,
        title: 'Update all apps?',
      });
      if (ok) all.mutate(undefined, { onError: failed, onSuccess: started('Updating apps') });
    },
    updateApp: async (app) => {
      const ok = await confirm({
        body: (
          <>
            <p>
              Pulls the new image and recreates {app.title}. It is unavailable for a minute or two; settings and data
              stay.
            </p>
            {app.role === 'gluetun' ? (
              <p>Apps that run inside Gluetun’s network (such as qBittorrent) are recreated too.</p>
            ) : null}
          </>
        ),
        confirmLabel: `Update ${app.title}`,
        title: `Update ${app.title}?`,
      });
      if (ok) {
        one.mutate(
          { repo: app.repo, role: app.role },
          { onError: failed, onSuccess: started(`Updating ${app.title}`) },
        );
      }
    },
    updateSaltbox: async () => {
      const ok = await confirm({
        body: (
          <>
            <p>
              Runs <code>sb update</code>: resets the Saltbox checkouts to the latest commit on their branches and
              refreshes the settings files.
            </p>
            <p>Apps keep running.</p>
          </>
        ),
        confirmLabel: 'Run sb update',
        title: 'Update Saltbox?',
      });
      if (ok) saltbox.mutate(undefined, { onError: failed, onSuccess: started('Updating Saltbox') });
    },
  };
}

const ACTION_WORDS: Record<ContainerAction, [string, string]> = {
  restart: ['Restart', 'restarted'],
  start: ['Start', 'started'],
  stop: ['Stop', 'stopped'],
};

/** Start, stop or restart a container, asking first for anything that interrupts it. */
export function useContainerActions(): {
  pending: boolean;
  run: (name: string, action: ContainerAction) => Promise<void>;
} {
  const confirm = useConfirm();
  const toast = useToast();
  const mutation = useContainerAction();
  return {
    pending: mutation.isPending,
    run: async (name, action) => {
      const [verb, done] = ACTION_WORDS[action];
      if (action !== 'start') {
        const ok = await confirm({
          body: (
            <p>
              {action === 'stop'
                ? `${name} stays stopped until you start it again or the server restarts.`
                : `${name} is unavailable for a few seconds while it restarts.`}
            </p>
          ),
          confirmLabel: `${verb} ${name}`,
          title: `${verb} ${name}?`,
          tone: action === 'stop' ? 'danger' : 'primary',
        });
        if (!ok) return;
      }
      mutation.mutate(
        { action, name },
        {
          onError: (error) => toast({ body: error.message, title: `Could not ${action} ${name}`, tone: 'danger' }),
          onSuccess: () => toast({ title: `${name} ${done}`, tone: 'ok' }),
        },
      );
    },
  };
}
