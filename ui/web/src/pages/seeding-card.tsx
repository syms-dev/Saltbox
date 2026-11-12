import { Sprout } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useSaveSeeding, useSeeding } from '../api/queries';
import type { SeedingStatus } from '../api/types';
import { useToast } from '../components/feedback';
import { formatBytes } from '../format';
import styles from './seeding-card.module.css';

/** "3 torrents (12 GB)". */
export function torrentCount(group: { count: number; size: number } | undefined): string {
  const count = group?.count ?? 0;
  return `${count} torrent${count === 1 ? '' : 's'}${count === 0 ? '' : ` (${formatBytes(group?.size ?? 0)})`}`;
}

/** A positive number typed into a field, or null when it is empty or not one. */
export function parseLimit(text: string): number | null {
  const value = Number(text.trim().replace(',', '.'));
  return text.trim() === '' || !Number.isFinite(value) || value <= 0 ? null : value;
}

/** The limits form: each limit has a switch and a number; saving stops torrents at the first one reached. */
function Limits({ status }: { status: SeedingStatus }): React.ReactNode {
  const limits = status.limits;
  const save = useSaveSeeding();
  const toast = useToast();
  const [useRatio, setUseRatio] = useState(limits?.ratio != null);
  const [ratio, setRatio] = useState(limits?.ratio == null ? '' : String(limits.ratio));
  const [useDays, setUseDays] = useState(limits?.days != null);
  const [days, setDays] = useState(limits?.days == null ? '' : String(limits.days));
  const chosen = {
    days: useDays ? parseLimit(days) : null,
    ratio: useRatio ? parseLimit(ratio) : null,
  };
  const invalid = (useRatio && chosen.ratio === null) || (useDays && chosen.days === null);
  const changed =
    chosen.ratio !== (limits?.ratio ?? null) || chosen.days !== (limits?.days ?? null) || limits?.action !== 'stop';

  return (
    <form
      className="stack-sm"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(chosen, {
          onError: (error) => toast({ body: error.message, title: 'Could not save the limits', tone: 'danger' }),
          onSuccess: () => toast({ title: 'Seeding limits saved', tone: 'ok' }),
        });
      }}
    >
      <fieldset className={styles['limits']}>
        <legend>Stop seeding a torrent</legend>
        <div className={styles['limit']}>
          <label>
            <input checked={useRatio} onChange={(e) => setUseRatio(e.target.checked)} type="checkbox" /> at a share
            ratio of
          </label>
          <input
            aria-label="Share ratio"
            className={styles['number']}
            disabled={!useRatio}
            inputMode="decimal"
            onChange={(e) => setRatio(e.target.value)}
            placeholder="e.g. 2"
            value={ratio}
          />
        </div>
        <div className={styles['limit']}>
          <label>
            <input checked={useDays} onChange={(e) => setUseDays(e.target.checked)} type="checkbox" /> after seeding for
          </label>
          <input
            aria-label="Days of seeding"
            className={styles['number']}
            disabled={!useDays}
            inputMode="decimal"
            onChange={(e) => setDays(e.target.value)}
            placeholder="e.g. 14"
            value={days}
          />
          <span>days</span>
        </div>
      </fieldset>
      <p className="muted small">
        With both on, a torrent stops at whichever it reaches first. It is stopped, not removed: Sonarr and Radarr then
        remove the ones they added, with their copy in the downloads folder (your library keeps its own). Trackers with
        seeding rules need at least what they ask for, and a limit set on an indexer in Prowlarr overrides these for its
        torrents.
        {limits?.inactive_days == null
          ? ''
          : ` qBittorrent also stops torrents that sit idle for ${limits.inactive_days} days (set in qBittorrent).`}
      </p>
      <div className="row">
        <button className="primary" disabled={invalid || !changed || save.isPending} type="submit">
          Save limits
        </button>
        {invalid ? <span className="muted small">Enter a number above 0, or switch the limit off.</span> : null}
      </div>
    </form>
  );
}

/** Finished torrents that keep seeding, the limits that stop them, and apps for finer rules. */
export function SeedingCard(): React.ReactNode {
  const seeding = useSeeding();
  const status = seeding.data;
  if (status === undefined || !status.installed) return null;
  const tools = status.tools;
  return (
    <section aria-labelledby="seeding-title" className="card stack-sm">
      <h2 className={styles['title']} id="seeding-title">
        <Sprout aria-hidden="true" size={18} /> Seeding
      </h2>
      {status.error !== '' || status.limits === undefined ? (
        <p className="note warn small">qBittorrent did not answer: {status.error}</p>
      ) : (
        <>
          <dl className={styles['facts']}>
            <div>
              <dt>Still seeding</dt>
              <dd>
                {torrentCount(status.seeding)}
                {(status.seeding?.count ?? 0) > 0 && status.longest_seeding_days !== undefined
                  ? `, the longest for ${status.longest_seeding_days} days`
                  : ''}
              </dd>
            </div>
            <div>
              <dt>Stopped, still in qBittorrent</dt>
              <dd>{torrentCount(status.stopped)}</dd>
            </div>
            {(status.categories ?? []).length === 0 ? null : (
              <div>
                <dt>By category</dt>
                <dd>
                  {(status.categories ?? [])
                    .map((c) => `${c.name === '' ? 'none' : c.name} ${c.seeding + c.stopped}`)
                    .join(' · ')}
                </dd>
              </div>
            )}
          </dl>
          {status.unlimited === true ? (
            <p className="note warn small" role="status">
              No seeding limit is set, so finished torrents seed forever and pile up. Sonarr and Radarr remove a
              finished torrent only after qBittorrent has stopped it at a limit.
            </p>
          ) : null}
          {status.limits.action === 'remove' || status.limits.action === 'remove_files' ? (
            <p className="note warn small" role="status">
              qBittorrent is set to remove torrents itself at the limit. Sonarr and Radarr report that as an error;
              saving here changes it to stop.
            </p>
          ) : null}
          <Limits key={JSON.stringify(status.limits)} status={status} />
        </>
      )}
      {tools.length === 0 ? null : (
        <p className="muted small">
          For rules per tracker or category, or to clear out what is left stopped, the catalogs have{' '}
          {tools.map((tool, index) => (
            <span key={tool.role}>
              {index === 0 ? '' : index === tools.length - 1 ? ' and ' : ', '}
              <Link to={`/apps/${tool.repo}/${tool.role}`}>{tool.title}</Link>
              {tool.installed ? ' (installed)' : ''}
            </span>
          ))}
          .
        </p>
      )}
    </section>
  );
}
