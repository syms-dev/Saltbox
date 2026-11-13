import { ExternalLink, HardDrive } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

import { useApps, useDismiss, useDrives } from '../api/queries';
import type { Drive, DriveAttribute, DriveHealth } from '../api/types';
import { StatusDot } from '../components/status-dot';
import { formatRelative } from '../format';
import styles from './drives-card.module.css';
import type { Attention } from './home-attention';

const HOURS_PER_YEAR = 8766;

/** Drive sizes the way they are sold: "8.0 TB", in powers of ten. */
export function formatDriveSize(bytes: number): string {
  if (bytes <= 0) return '';
  const gigabytes = bytes / 1e9;
  return gigabytes >= 1000 ? `${(gigabytes / 1000).toFixed(1)} TB` : `${Math.round(gigabytes)} GB`;
}

/** How long a drive has been spinning: "3.0 years", "45 days", "20 hours". */
export function formatPowerOn(hours: number): string {
  if (hours >= HOURS_PER_YEAR) return `${(hours / HOURS_PER_YEAR).toFixed(1)} years`;
  if (hours >= 48) return `${Math.round(hours / 24)} days`;
  return `${hours} hour${hours === 1 ? '' : 's'}`;
}

/** Which of the two checks a drive fails, in words. */
export function verdict(drive: Drive): string {
  if (drive.healthy) return 'Healthy';
  if (drive.failed_smart && drive.failed_scrutiny) return 'Failing its own SMART check and Scrutiny’s';
  return drive.failed_smart ? 'Failing its own SMART check' : 'Failing Scrutiny’s thresholds';
}

/** "ST8000VN004 · 8.0 TB" */
function describe(drive: Drive): string {
  return [drive.label, drive.model, formatDriveSize(drive.capacity)].filter((part) => part !== '').join(' · ');
}

/** A failing drive is the most urgent thing a server can say: it goes to the top of Home. */
/** "Reallocated Sectors Count is 24: observed failure rate 14%" */
export function attributeLine(attribute: DriveAttribute): string {
  const value = attribute.value === null ? '' : ` is ${attribute.value}`;
  const why = attribute.failed_smart
    ? 'past the limit the drive’s maker set'
    : attribute.failure_rate === null
      ? attribute.reason
      : `drives with this value fail about ${Math.round(attribute.failure_rate * 100)}% of the time`;
  return `${attribute.name}${value}${why === '' ? '' : `: ${why}`}`;
}

/** Which attributes a drive fails on, shortest useful form: "Reallocated Sectors Count is 24". */
function failingSummary(drive: Drive): string {
  const failing = drive.failing ?? [];
  if (failing.length === 0) return verdict(drive);
  return failing.map((a) => `${a.name}${a.value === null ? '' : ` is ${a.value}`}`).join(', ');
}

export function driveAttention(health: DriveHealth | undefined): Attention[] {
  return (health?.drives ?? [])
    .filter((drive) => !drive.healthy && drive.dismissed !== true)
    .map((drive) => ({
      actions: [{ kind: 'link' as const, label: 'Drive health', to: '/system#drives' }],
      detail: `${describe(drive)}. ${failingSummary(drive)}. Back up what is on it and plan to replace it.`,
      id: `drive:${drive.id}`,
      title: `Drive ${drive.name} is failing its health check`,
      tone: 'danger' as const,
    }));
}

function DriveRow({ drive }: { drive: Drive }): React.ReactNode {
  const dismiss = useDismiss();
  const failing = drive.failing ?? [];
  const dismissed = drive.dismissed === true;
  return (
    <li className={`${styles['drive']} ${drive.healthy || dismissed ? '' : styles['failing']}`}>
      <div className={styles['head']}>
        <strong className={styles['name']}>{drive.name}</strong>
        <span className={styles['kind']}>{drive.kind}</span>
        <span className="spacer" />
        <StatusDot health={{ label: verdict(drive), tone: drive.healthy ? 'ok' : 'danger' }} />
      </div>
      <span className="muted small">{describe(drive)}</span>
      <dl className={styles['facts']}>
        <div>
          <dt>Temperature</dt>
          <dd>{drive.temperature === null ? '–' : `${drive.temperature} °C`}</dd>
        </div>
        <div>
          <dt>Powered on</dt>
          <dd>{drive.power_on_hours === null ? '–' : formatPowerOn(drive.power_on_hours)}</dd>
        </div>
        <div>
          <dt>Checked</dt>
          <dd>{drive.checked_at === null ? 'not yet' : formatRelative(drive.checked_at)}</dd>
        </div>
      </dl>
      {drive.healthy ? null : (
        <div className={styles['why']}>
          {failing.length === 0 ? (
            <span className="small muted">Scrutiny did not say which attribute; its page for the drive has more.</span>
          ) : (
            <ul className={styles['attributes']}>
              {failing.map((attribute) => (
                <li key={attribute.id} title={attribute.description}>
                  {attributeLine(attribute)}
                  {attribute.critical ? <span className={styles['critical']}>critical</span> : null}
                </li>
              ))}
            </ul>
          )}
          {drive.key == null ? null : (
            <div className="row">
              {dismissed ? <span className="small muted">Dismissed: not shown on Home.</span> : null}
              <span className="spacer" />
              <button
                className="small ghost"
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate({ dismiss: !dismissed, key: drive.key ?? '', label: drive.name })}
                type="button"
              >
                {dismissed ? 'Show on Home again' : 'Dismiss'}
              </button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** Every drive's health as Scrutiny judges it. Not shown at all without Scrutiny. */
export function DrivesCard(): React.ReactNode {
  const drives = useDrives();
  const apps = useApps();
  const location = useLocation();
  const section = useRef<HTMLElement>(null);
  const health = drives.data;
  const loaded = health !== undefined;
  useEffect(() => {
    if (loaded && location.hash === '#drives') section.current?.scrollIntoView({ block: 'start' });
  }, [loaded, location.hash]);
  if (health === undefined || !health.installed) return null;
  const failing = health.drives.filter((drive) => !drive.healthy).length;
  const open = health.drives.filter((drive) => !drive.healthy && drive.dismissed !== true).length;
  const total = health.drives.length;
  const scrutiny = apps.data?.find((app) => app.role === 'scrutiny')?.urls[0];
  return (
    <section aria-labelledby="drives-title" className="card stack-sm" id="drives" ref={section}>
      <div className="row">
        <h2 className={styles['title']} id="drives-title">
          <HardDrive aria-hidden="true" size={18} /> Drive health
        </h2>
        <span className="spacer" />
        {scrutiny === undefined ? null : (
          <a className="small" href={scrutiny} rel="noreferrer" target="_blank">
            Open Scrutiny <ExternalLink aria-hidden="true" size={13} />
          </a>
        )}
      </div>
      {health.error !== '' ? (
        <p className="note warn small">Scrutiny did not answer: {health.error}</p>
      ) : total === 0 ? (
        <p className="muted small">Scrutiny has not reported on any drive yet.</p>
      ) : (
        <>
          <p className={open > 0 ? 'note danger small' : 'muted small'} role={open > 0 ? 'alert' : undefined}>
            {failing === 0
              ? `${total === 1 ? 'The drive is' : `All ${total} drives are`} healthy, by the drives’ own SMART checks and by Scrutiny’s thresholds.`
              : `${failing} of ${total} drive${total === 1 ? '' : 's'} ${failing === 1 ? 'is' : 'are'} failing${open === 0 ? ' (dismissed)' : ''}. Back up what is on ${failing === 1 ? 'it' : 'them'} and plan a replacement. A dismissed drive comes back here if another attribute starts failing.`}
          </p>
          <ul aria-label="Drives" className={styles['drives']}>
            {health.drives.map((drive) => (
              <DriveRow drive={drive} key={drive.id} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
