import { ExternalLink, HardDrive } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

import { useApps, useDrives } from '../api/queries';
import type { Drive, DriveHealth } from '../api/types';
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
export function driveAttention(health: DriveHealth | undefined): Attention[] {
  return (health?.drives ?? [])
    .filter((drive) => !drive.healthy)
    .map((drive) => ({
      actions: [{ kind: 'link' as const, label: 'Drive health', to: '/system#drives' }],
      detail: `${describe(drive)}. ${verdict(drive)}. Back up what is on it and plan to replace it.`,
      id: `drive:${drive.id}`,
      title: `Drive ${drive.name} is failing its health check`,
      tone: 'danger' as const,
    }));
}

function DriveRow({ drive }: { drive: Drive }): React.ReactNode {
  return (
    <li className={`${styles['drive']} ${drive.healthy ? '' : styles['failing']}`}>
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
          <p className={failing > 0 ? 'note danger small' : 'muted small'} role={failing > 0 ? 'alert' : undefined}>
            {failing === 0
              ? `${total === 1 ? 'The drive is' : `All ${total} drives are`} healthy, by the drives’ own SMART checks and by Scrutiny’s thresholds.`
              : `${failing} of ${total} drive${total === 1 ? '' : 's'} ${failing === 1 ? 'is' : 'are'} failing. Back up what is on ${failing === 1 ? 'it' : 'them'} and plan a replacement.`}
          </p>
          <ul className={styles['drives']}>
            {health.drives.map((drive) => (
              <DriveRow drive={drive} key={drive.id} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
