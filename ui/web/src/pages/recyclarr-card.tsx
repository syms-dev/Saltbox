import { Eye, PackagePlus, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  useApps,
  useAssignProfile,
  useJobs,
  useRecyclarr,
  useRecyclarrSync,
  useRecyclarrUsage,
  useSaveRecyclarr,
} from '../api/queries';
import type { ProfileUse, RecyclarrApp, RecyclarrStatus } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';
import { jobTitle } from '../components/shell';
import { formatRelative } from '../format';
import { useJobActions } from '../lib/actions';
import styles from './recyclarr-card.module.css';

const LABELS: Record<RecyclarrApp, string> = { radarr: 'Movies', sonarr: 'TV shows' };

/** The current selection, or the TRaSH defaults when there is no config yet. */
export function initialSelection(status: RecyclarrStatus): Record<RecyclarrApp, string[]> {
  const pick = (app: RecyclarrApp): string[] =>
    status.config_exists ? status.selected[app] : status.profiles[app].filter((p) => p.default).map((p) => p.trash_id);
  return { radarr: pick('radarr'), sonarr: pick('sonarr') };
}

function Editor({ status }: { status: RecyclarrStatus }): React.ReactNode {
  const [selection, setSelection] = useState(() => initialSelection(status));
  const save = useSaveRecyclarr();
  const sync = useRecyclarrSync();
  const jobs = useJobs();
  const toast = useToast();
  const navigate = useNavigate();
  const saved = initialSelection(status);
  // With no config yet, the suggested defaults are unsaved too.
  const dirty =
    !status.config_exists ||
    (['sonarr', 'radarr'] as const).some((app) => [...selection[app]].sort().join() !== [...saved[app]].sort().join());
  const busy = (jobs.data?.busy ?? false) || sync.isPending;
  const nothing = selection.sonarr.length === 0 && selection.radarr.length === 0;

  function toggle(app: RecyclarrApp, id: string): void {
    setSelection((current) => ({
      ...current,
      [app]: current[app].includes(id) ? current[app].filter((x) => x !== id) : [...current[app], id],
    }));
  }

  function run(preview: boolean): void {
    sync.mutate(
      { preview },
      {
        onError: (error) => toast({ body: error.message, title: 'Could not run Recyclarr', tone: 'danger' }),
        onSuccess: (job) => void navigate(`/activity/${job.id}`),
      },
    );
  }

  return (
    <div className="stack-sm">
      {status.config_exists && !status.managed ? (
        <p className="note warn small">
          Your recyclarr.yml was written by hand. Saving here replaces it and keeps the old one as a dated .bak copy.
        </p>
      ) : null}
      <div className={styles['apps']}>
        {(['sonarr', 'radarr'] as const).map((app) => (
          <fieldset className={styles['app']} key={app}>
            <legend>
              {LABELS[app]}{' '}
              <span className="muted small">
                {status.instances[app].length === 0
                  ? `(${app} is not installed)`
                  : `(${status.instances[app].join(', ')})`}
              </span>
            </legend>
            {status.profiles[app].map((profile) => (
              <label className={styles['profile']} key={profile.trash_id}>
                <input
                  checked={selection[app].includes(profile.trash_id)}
                  disabled={status.instances[app].length === 0}
                  onChange={() => toggle(app, profile.trash_id)}
                  type="checkbox"
                />
                <span>
                  <strong>{profile.name}</strong>
                  <span className="muted small">{profile.summary}</span>
                </span>
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      <div className="row">
        <button
          className="primary"
          disabled={!dirty || nothing || save.isPending}
          onClick={() =>
            save.mutate(selection, {
              onError: (error) => toast({ body: error.message, title: 'Could not save', tone: 'danger' }),
              onSuccess: (result) =>
                toast({
                  body:
                    result.backup === null
                      ? 'Preview the changes, or sync now.'
                      : `Your old config is kept as ${result.backup.split('/').pop() ?? 'a .bak copy'}.`,
                  title: 'Profiles saved',
                  tone: 'ok',
                }),
            })
          }
          type="button"
        >
          Save profiles
        </button>
        <button
          disabled={busy || dirty || !status.running || !status.config_exists}
          onClick={() => run(true)}
          type="button"
        >
          <Eye aria-hidden="true" size={15} /> Preview changes
        </button>
        <button
          disabled={busy || dirty || !status.running || !status.config_exists}
          onClick={() => run(false)}
          type="button"
        >
          <RefreshCw aria-hidden="true" size={15} /> Sync now
        </button>
        {dirty ? <span className="muted small">Save before syncing.</span> : null}
        {!status.running ? <span className="muted small">The recyclarr container is not running.</span> : null}
      </div>
      <p className="muted small">
        {status.last_job === null ? (
          'Not synced from here yet. '
        ) : (
          <>
            Last run: <Link to={`/activity/${status.last_job.id}`}>{jobTitle(status.last_job)}</Link>{' '}
            {status.last_job.status} {formatRelative(status.last_job.started_at)}.{' '}
          </>
        )}
        Recyclarr also syncs once a day by itself. In Sonarr and Radarr, pick the new profiles for your shows and films.
      </p>
    </div>
  );
}

const APP_NAMES: Record<ProfileUse['app'], string> = { radarr: 'Radarr', sonarr: 'Sonarr' };

/** "120 on HD-1080p, 23 on Any" for the profiles that have something on them. */
export function profileLine(use: ProfileUse): string {
  const used = (use.profiles ?? []).filter((profile) => profile.count > 0);
  return used.map((profile) => `${profile.count} on ${profile.name}`).join(', ');
}

/** One Sonarr or Radarr: whether the synced profiles are there and in use, and a way to use them. */
function InstanceUse({ use }: { use: ProfileUse }): React.ReactNode {
  const assign = useAssignProfile();
  const confirm = useConfirm();
  const toast = useToast();
  const title = use.name === use.app ? APP_NAMES[use.app] : `${APP_NAMES[use.app]} (${use.name})`;
  if (use.error !== undefined && use.error !== '') {
    return (
      <li>
        <strong>{title}</strong> <span className="muted small">did not answer: {use.error}</span>
      </li>
    );
  }
  const total = use.total ?? 0;
  const noun = use.noun ?? 'items';
  const synced = (use.profiles ?? []).filter((profile) => profile.synced);

  async function move(profile: { count: number; id: number; name: string }): Promise<void> {
    const moving = total - profile.count;
    const ok = await confirm({
      body: (
        <>
          <p>
            Changes the quality profile of {moving} {noun} in {title} to <strong>{profile.name}</strong>, the same as
            selecting them all in its mass editor.
          </p>
          <p>
            Nothing is downloaded now. From then on {title} replaces a file when it finds a release the new profile
            prefers. To go back, set the old profile again in {title}.
          </p>
        </>
      ),
      confirmLabel: `Move ${moving} ${noun}`,
      title: `Use ${profile.name} for everything in ${title}?`,
    });
    if (!ok) return;
    assign.mutate(
      { instance: use.name, profile_id: profile.id },
      {
        onError: (error) => toast({ body: error.message, title: 'Could not change the profiles', tone: 'danger' }),
        onSuccess: (result) =>
          toast({ title: `${result.moved} ${noun} in ${title} now use ${result.profile}`, tone: 'ok' }),
      },
    );
  }

  return (
    <li className={styles['use']}>
      <div>
        <strong>{title}</strong>{' '}
        <span className="muted small">
          {total} {noun}
          {total > 0 ? `: ${profileLine(use)}` : ''}
        </span>
      </div>
      {(use.missing ?? []).map((name) => (
        <span className="small" key={name}>
          <strong>{name}</strong> is not in {title} yet. Press “Sync now” above to create it.
        </span>
      ))}
      {synced.map((profile) =>
        profile.count >= total ? (
          <span className="small" key={profile.id}>
            {total === 0 ? `${profile.name} is ready for what you add.` : `Everything uses ${profile.name}.`}
          </span>
        ) : (
          <div className="row" key={profile.id}>
            <span className="small">
              {profile.count === 0 ? 'Nothing uses' : `${profile.count} of ${total} use`}{' '}
              <strong>{profile.name}</strong> yet.
            </span>
            <button className="small" disabled={assign.isPending} onClick={() => void move(profile)} type="button">
              Move all {noun} to {profile.name}
            </button>
          </div>
        ),
      )}
    </li>
  );
}

/** Recyclarr creates profiles and never assigns them: this shows whether anything uses them. */
function ProfileUsage(): React.ReactNode {
  const usage = useRecyclarrUsage(true);
  const instances = usage.data?.instances ?? [];
  if (usage.data === undefined || instances.length === 0) return null;
  return (
    <div className="stack-sm">
      <h3 className={styles['flush']}>In use</h3>
      <p className="muted small">
        A sync creates the profiles in Sonarr and Radarr; it does not put any show or film on them. What you already
        have keeps its old profile until you move it, and new additions use whichever profile you pick when adding.
      </p>
      <ul className={styles['uses']}>
        {instances.map((use) => (
          <InstanceUse key={use.name} use={use} />
        ))}
      </ul>
    </div>
  );
}

export function RecyclarrCard(): React.ReactNode {
  const recyclarr = useRecyclarr();
  const apps = useApps();
  const actions = useJobActions();
  const app = apps.data?.find((a) => a.role === 'recyclarr');
  return (
    <section aria-labelledby="recyclarr-title" className="card">
      <h2 className={styles['title']} id="recyclarr-title">
        <SlidersHorizontal aria-hidden="true" size={18} /> Quality profiles
      </h2>
      <p className="muted small">
        Recyclarr keeps Sonarr and Radarr’s quality profiles and custom formats in line with the TRaSH Guides, so they
        grab good releases and skip bad ones.
      </p>
      {recyclarr.data === undefined ? (
        <p className="muted small">Reading…</p>
      ) : !recyclarr.data.installed ? (
        <div className="row">
          <span className="muted">Recyclarr is not installed.</span>
          {app === undefined ? null : (
            <button className="small primary" onClick={() => void actions.install(app)} type="button">
              <PackagePlus aria-hidden="true" size={15} /> Install Recyclarr
            </button>
          )}
        </div>
      ) : (
        <>
          <Editor key={JSON.stringify(recyclarr.data.selected)} status={recyclarr.data} />
          <ProfileUsage />
        </>
      )}
    </section>
  );
}
