import { HardDrive } from 'lucide-react';

import { Link } from 'react-router-dom';

import { useOverview } from '../api/queries';
import { Meter } from '../components/meter';
import { ErrorMessage, Loading } from '../components/query-state';
import { SaltboxUpdates } from '../components/saltbox-updates';
import { StatusDot } from '../components/status-dot';
import { formatBytes } from '../format';
import { BackupsCard, ResourcesCard, TailscaleCard } from './system-sections';
import styles from './system-page.module.css';

const MOUNT_KINDS: Record<string, string> = {
  cifs: 'SMB share',
  'fuse.mergerfs': 'mergerfs pool',
  'fuse.rclone': 'rclone remote',
  nfs: 'NFS share',
  nfs4: 'NFS share',
};

export function SystemPage(): React.ReactNode {
  const overview = useOverview();
  if (overview.isPending) return <Loading what="system" />;
  if (overview.isError) return <ErrorMessage error={overview.error} prefix="System" />;
  const { disks, mounts, reboot_required: reboot, units } = overview.data.host;
  return (
    <div className="stack">
      <div className="row">
        <h1 className={styles['flush']}>System</h1>
        <span className="spacer" />
        <Link className="button small" to="/automation">
          Alerts and nightly maintenance
        </Link>
      </div>
      {reboot ? <p className="note warn">Ubuntu installed updates that need a restart of the server.</p> : null}

      <ResourcesCard />

      <section aria-labelledby="storage-title" className="card">
        <h2 id="storage-title">Storage</h2>
        {disks.length === 0 ? (
          <p className="muted">No disk information.</p>
        ) : (
          <ul className={styles['disks']}>
            {disks.map((disk) => (
              <li className={styles['disk']} key={disk.path}>
                <HardDrive aria-hidden="true" className="muted" size={20} />
                <div className={styles['diskBody']}>
                  <div className={styles['diskHead']}>
                    <code>{(disk.paths ?? [disk.path]).join(' · ')}</code>
                    <span className="small">
                      <strong>{formatBytes(disk.free)}</strong>{' '}
                      <span className="muted">free of {formatBytes(disk.total)}</span>
                    </span>
                  </div>
                  <Meter label={`${disk.path} ${disk.percent}% used`} percent={disk.percent} />
                  <span className="muted small">{disk.percent}% used</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className={styles['pair']}>
        <section aria-labelledby="mounts-title" className="card">
          <h2 id="mounts-title">Mounts</h2>
          {mounts.length === 0 ? (
            <p className="muted small">No rclone remotes, mergerfs pools or network shares are mounted.</p>
          ) : (
            <table>
              <tbody>
                {mounts.map((mount) => (
                  <tr key={mount.target}>
                    <td>
                      <code>{mount.target}</code>
                      <div className="muted small">{mount.source}</div>
                    </td>
                    <td className="muted">{MOUNT_KINDS[mount.type] ?? mount.type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section aria-labelledby="services-title" className="card">
          <h2 id="services-title">Saltbox services</h2>
          {units.length === 0 ? (
            <p className="muted small">No Saltbox-managed systemd services.</p>
          ) : (
            <ul className={styles['units']}>
              {units.map((unit) => (
                <li key={unit.unit}>
                  <StatusDot
                    health={{
                      label: `${unit.active}${unit.sub === '' || unit.sub === unit.active ? '' : ` (${unit.sub})`}`,
                      tone: unit.active === 'active' ? 'ok' : unit.active === 'failed' ? 'danger' : 'muted',
                    }}
                  />
                  <span className={styles['unitName']}>
                    <code>{unit.unit}</code>
                    <span className="muted small">{unit.description}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className={styles['pair']}>
        <TailscaleCard />
        <BackupsCard />
      </div>

      <SaltboxUpdates />
    </div>
  );
}
