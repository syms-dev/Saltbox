import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { API_ROUTES, apiFetch } from '../api/client';

import {
  useContainerAction,
  useReboot,
  useStartJob,
  useUninstallApp,
  useUpdateAll,
  useUpdateApp,
  useUpdateSaltbox,
} from '../api/queries';
import type { App, AppRef, ContainerAction, Job, UninstallPlan } from '../api/types';
import { useConnection } from '../components/connection';
import { useConfirm, useToast } from '../components/feedback';

export function appTag(app: Pick<App, 'install_tag' | 'role' | 'sb_tag'>): string {
  return app.sb_tag ?? app.install_tag ?? app.role;
}

/** What uninstalling removes, with the one choice that cannot be undone left unticked. */
function UninstallBody({
  onChoice,
  plan,
  title,
}: {
  onChoice: (deleteData: boolean) => void;
  plan: UninstallPlan;
  title: string;
}): React.ReactNode {
  const [deleteData, setDeleteData] = useState(false);
  return (
    <>
      <p>
        {plan.containers.length > 0 ? (
          <>
            Stops and removes {plan.containers.length === 1 ? 'the container' : 'the containers'}{' '}
            <code>{plan.containers.join(', ')}</code>, so {title} no longer uses memory or CPU.
          </>
        ) : (
          <>{title} has no container left; only its settings folder remains.</>
        )}{' '}
        Your media files are not touched.
      </p>
      {plan.folders.length === 0 ? null : (
        <label>
          <input
            checked={deleteData}
            onChange={(event) => {
              onChoice(event.target.checked);
              setDeleteData(event.target.checked);
            }}
            type="checkbox"
          />{' '}
          Also delete its settings and database in <code>{plan.folders.join(', ')}</code>. This cannot be undone.
        </label>
      )}
      <p className="small">
        {deleteData || plan.folders.length === 0
          ? 'Installing it again later starts from scratch.'
          : 'With the settings kept, installing it again later brings it back as it was.'}{' '}
        Its DNS record and any settings for it in the inventory stay; they do no harm.
      </p>
    </>
  );
}

/** Said before recreating something every web app here depends on, this one included. */
function CoreWarning(): React.ReactNode {
  return (
    <p>
      This includes part of Saltbox’s core (the proxy or sign-in in front of every web app, this one too). Expect this
      page to drop for a moment; it reconnects by itself, signing you in again if it has to. The job carries on, and its
      log is under Activity.
    </p>
  );
}

/**
 * The job-starting actions every page shares: each asks first, says what will happen in
 * plain words, starts the job, and offers the live log.
 */
export function useJobActions(): {
  install: (app: App, reinstall?: boolean) => Promise<void>;
  reboot: () => Promise<void>;
  uninstall: (app: AppRef) => Promise<void>;
  updateAll: (apps: AppRef[]) => Promise<void>;
  updateApp: (app: AppRef) => Promise<void>;
  updateSaltbox: () => Promise<void>;
} {
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();
  const start = useStartJob();
  const one = useUpdateApp();
  const all = useUpdateAll();
  const saltbox = useUpdateSaltbox();
  const restart = useReboot();
  const remove = useUninstallApp();
  const connection = useConnection();

  function started(title: string, core = false): (job: Job) => void {
    return (job) => {
      // Recreating the proxy or sign-in drops this page; watch for it to come back.
      if (core) connection.expectOutage('proxy');
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
    reboot: async () => {
      const ok = await confirm({
        body: (
          <>
            <p>
              Everything on the server stops for a few minutes: every app, any stream or download in progress, and this
              page.
            </p>
            <p>The apps start again by themselves once the server is back.</p>
          </>
        ),
        confirmLabel: 'Restart the server',
        title: 'Restart the server now?',
        tone: 'danger',
      });
      if (!ok) return;
      restart.mutate(undefined, {
        onError: (error) => toast({ body: error.message, title: 'Could not restart the server', tone: 'danger' }),
        onSuccess: () => {
          // The page then watches for the server to go and come back, and says how it went.
          connection.expectOutage('reboot');
          toast({
            body: 'This page reconnects by itself in a few minutes.',
            title: 'The server is restarting',
            tone: 'info',
          });
        },
      });
    },
    uninstall: async (app) => {
      let plan: UninstallPlan;
      try {
        plan = await apiFetch<UninstallPlan>(API_ROUTES.appUninstall(app.repo, app.role));
      } catch (error) {
        failed(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      if (plan.blockers.length > 0) {
        toast({ body: plan.blockers.join('; '), title: `${app.title} cannot be uninstalled yet`, tone: 'danger' });
        return;
      }
      let deleteData = false;
      const ok = await confirm({
        body: <UninstallBody onChoice={(value) => (deleteData = value)} plan={plan} title={app.title} />,
        confirmLabel: `Uninstall ${app.title}`,
        title: `Uninstall ${app.title}?`,
        tone: 'danger',
      });
      if (!ok) return;
      remove.mutate(
        { deleteData, repo: app.repo, role: app.role },
        {
          onError: (error) => toast({ body: error.message, title: `Could not uninstall ${app.title}`, tone: 'danger' }),
          onSuccess: (result) => {
            const left =
              result.kept.length > 0
                ? { body: `Its settings are still in ${result.kept.join(', ')}.` }
                : result.deleted.length > 0
                  ? { body: `Deleted ${result.deleted.join(', ')}.` }
                  : {};
            toast({ ...left, title: `${app.title} uninstalled`, tone: 'ok' });
            void navigate('/apps');
          },
        },
      );
    },
    updateAll: async (apps) => {
      const ok = await confirm({
        body: (
          <>
            <p>New images are ready for {apps.map((a) => a.title).join(', ')}.</p>
            <p>Each app is recreated on its new image and is unavailable for a minute or two.</p>
            {apps.some((a) => a.core === true) ? <CoreWarning /> : null}
          </>
        ),
        confirmLabel: `Update ${apps.length} app${apps.length === 1 ? '' : 's'}`,
        title: 'Update all apps?',
      });
      if (ok) {
        const core = apps.some((a) => a.core === true);
        all.mutate(undefined, { onError: failed, onSuccess: started('Updating apps', core) });
      }
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
            {app.core === true ? <CoreWarning /> : null}
          </>
        ),
        confirmLabel: `Update ${app.title}`,
        title: `Update ${app.title}?`,
      });
      if (ok) {
        one.mutate(
          { repo: app.repo, role: app.role },
          { onError: failed, onSuccess: started(`Updating ${app.title}`, app.core === true) },
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
            <p>
              If the update brings announcements they are shown with the job, and if it needs migrations the job waits
              for you to say whether to run them. Apps keep running.
            </p>
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
