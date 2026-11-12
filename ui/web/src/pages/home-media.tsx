import { ArrowDown, ArrowUp, CalendarDays, CircleCheck, Film, Play, Shield, ShieldAlert, Tv } from 'lucide-react';

import { Link } from 'react-router-dom';

import { useSeeding } from '../api/queries';
import type { MediaSnapshot, UpcomingItem } from '../api/types';
import { StatusDot } from '../components/status-dot';
import { formatBytes, formatDay, formatSpeed } from '../format';
import type { Attention } from './home-attention';
import styles from './home-media.module.css';

/** VPN problems belong in the attention list, with a way to fix them. */
export function mediaAttention(media: MediaSnapshot | undefined): Attention[] {
  const vpn = media?.vpn;
  if (vpn === undefined || !vpn.available || !vpn.configured) return [];
  const items: Attention[] = [];
  if (vpn.running !== true) {
    items.push({
      actions: [{ container: vpn.container ?? 'gluetun', kind: 'start', label: 'Start' }],
      detail: `Everything routed through it (${(vpn.routed ?? []).join(', ') || 'no apps'}) is offline.`,
      id: 'vpn:down',
      title: 'The VPN (Gluetun) is not running',
      tone: 'danger',
    });
  }
  if (vpn.qbittorrent_protected === false) {
    items.push({
      actions: [{ kind: 'link', label: 'qBittorrent settings', to: '/apps/saltbox/qbittorrent?tab=settings' }],
      detail:
        'Its traffic leaves through your home connection. Set qbittorrent_docker_network_mode to container:gluetun.',
      id: 'vpn:leak',
      title: 'qBittorrent is not behind the VPN',
      tone: 'danger',
    });
  }
  return items;
}

function Bar({ percent }: { percent: number }): React.ReactNode {
  return (
    <span aria-hidden="true" className={styles['bar']}>
      <span style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </span>
  );
}

function VpnCard({ vpn }: { vpn: NonNullable<MediaSnapshot['vpn']> }): React.ReactNode {
  if (vpn.available && !vpn.configured) return null;
  return (
    <section aria-labelledby="vpn-title" className={`card ${styles['card']}`}>
      <h3 className={styles['title']} id="vpn-title">
        {vpn.available && vpn.running === true && vpn.qbittorrent_protected !== false ? (
          <Shield aria-hidden="true" size={16} />
        ) : (
          <ShieldAlert aria-hidden="true" size={16} />
        )}
        VPN
      </h3>
      {!vpn.available ? (
        <p className="muted small">{vpn.error}</p>
      ) : (
        <div className="stack-sm">
          <StatusDot
            health={
              vpn.running !== true
                ? { label: 'Down', tone: 'danger' }
                : vpn.health === 'unhealthy'
                  ? { label: 'Unhealthy', tone: 'danger' }
                  : { label: 'Protected', tone: 'ok' }
            }
          />
          <dl className={styles['facts']}>
            <dt>Public IP</dt>
            <dd>
              <code>{vpn.public_ip || '—'}</code>
            </dd>
            <dt>Forwarded port</dt>
            <dd>
              <code>{vpn.forwarded_port ?? '—'}</code>
            </dd>
            <dt>Routed</dt>
            <dd>{(vpn.routed ?? []).join(', ') || 'nothing'}</dd>
          </dl>
        </div>
      )}
    </section>
  );
}

/** How much is seeding after it finished, with the way to the limits that stop it. */
function SeedingLine(): React.ReactNode {
  const seeding = useSeeding();
  const status = seeding.data;
  if (status?.seeding === undefined) return null;
  const { count, size } = status.seeding;
  return (
    <Link className={`small ${styles['seeding']}`} to="/connect">
      {count} seeding{count === 0 ? '' : ` (${formatBytes(size)})`}
      {status.unlimited === true ? ' · no limit set' : ''}
    </Link>
  );
}

function DownloadsCard({ media }: { media: MediaSnapshot }): React.ReactNode {
  const qbit = media.qbittorrent;
  const sab = media.sabnzbd;
  if (qbit === undefined && sab === undefined) return null;
  return (
    <section aria-labelledby="downloads-title" className={`card ${styles['card']}`}>
      <h3 className={styles['title']} id="downloads-title">
        <ArrowDown aria-hidden="true" size={16} /> Downloads
      </h3>
      <div className="stack-sm">
        {qbit === undefined ? null : (
          <div className={styles['client']}>
            <div className={styles['clientHead']}>
              <strong>qBittorrent</strong>
              {qbit.available ? (
                <span className={`small ${styles['speeds']}`}>
                  <ArrowDown aria-hidden="true" size={12} /> {formatSpeed(qbit.download_speed)}{' '}
                  <ArrowUp aria-hidden="true" size={12} /> {formatSpeed(qbit.upload_speed)}
                </span>
              ) : null}
            </div>
            {!qbit.available ? (
              <span className="muted small">{qbit.error}</span>
            ) : qbit.items.length === 0 ? (
              <span className="muted small">Nothing downloading</span>
            ) : (
              <ul className={styles['items']}>
                {qbit.items.map((item) => (
                  <li key={item.name}>
                    <span className={styles['itemName']} title={item.name}>
                      {item.name}
                    </span>
                    <span className={styles['itemMeta']}>
                      <Bar percent={item.progress} />
                      <span className="small muted">{item.progress.toFixed(0)}%</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {qbit.available ? <SeedingLine /> : null}
          </div>
        )}
        {sab === undefined ? null : (
          <div className={styles['client']}>
            <div className={styles['clientHead']}>
              <strong>SABnzbd</strong>
              {sab.available ? (
                <span className={`small ${styles['speeds']}`}>
                  {sab.paused ? (
                    'paused'
                  ) : (
                    <>
                      <ArrowDown aria-hidden="true" size={12} /> {formatSpeed(sab.download_speed)}
                    </>
                  )}
                </span>
              ) : null}
            </div>
            {!sab.available ? (
              <span className="muted small">{sab.error}</span>
            ) : sab.items.length === 0 ? (
              <span className="muted small">Queue empty</span>
            ) : (
              <ul className={styles['items']}>
                {sab.items.map((item) => (
                  <li key={item.name}>
                    <span className={styles['itemName']} title={item.name}>
                      {item.name}
                    </span>
                    <span className={styles['itemMeta']}>
                      <Bar percent={item.progress} />
                      <span className="small muted">{item.time_left}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function PlayingCard({ plex }: { plex: NonNullable<MediaSnapshot['plex']> }): React.ReactNode {
  return (
    <section aria-labelledby="playing-title" className={`card ${styles['card']}`}>
      <h3 className={styles['title']} id="playing-title">
        <Play aria-hidden="true" size={16} /> Now playing
      </h3>
      {!plex.available ? (
        <p className="muted small">{plex.error}</p>
      ) : plex.sessions.length === 0 ? (
        <p className="muted small">Nobody is watching anything on Plex.</p>
      ) : (
        <ul className={styles['items']}>
          {plex.sessions.map((session, index) => (
            <li key={`${session.user}-${index}`}>
              <span className={styles['itemName']}>
                <strong>{session.title}</strong> <span className="muted">{session.subtitle}</span>
              </span>
              <span className="small muted">
                {session.user} on {session.player}
                {session.state === 'paused' ? ' · paused' : ''}
                {session.transcoding ? ' · transcoding' : ''}
              </span>
              <Bar percent={session.progress} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function groupByDay(items: UpcomingItem[]): [string, UpcomingItem[]][] {
  const groups = new Map<string, UpcomingItem[]>();
  for (const item of items) {
    const day = formatDay(item.date);
    groups.set(day, [...(groups.get(day) ?? []), item]);
  }
  return [...groups.entries()];
}

function UpcomingCard({ upcoming }: { upcoming: NonNullable<MediaSnapshot['upcoming']> }): React.ReactNode {
  return (
    <section aria-labelledby="upcoming-title" className={`card ${styles['card']}`}>
      <h3 className={styles['title']} id="upcoming-title">
        <CalendarDays aria-hidden="true" size={16} /> Coming up
      </h3>
      {!upcoming.available ? (
        <p className="muted small">{upcoming.error}</p>
      ) : upcoming.items.length === 0 ? (
        <p className="muted small">Nothing monitored airs or releases this week.</p>
      ) : (
        <div className="stack-sm">
          {groupByDay(upcoming.items).map(([day, items]) => (
            <div key={day}>
              <div className={styles['day']}>{day}</div>
              <ul className={styles['items']}>
                {items.map((item) => (
                  <li className={styles['upcoming']} key={`${item.app}-${item.title}-${item.subtitle}`}>
                    {item.kind === 'episode' ? (
                      <Tv aria-hidden="true" className="muted" size={14} />
                    ) : (
                      <Film aria-hidden="true" className="muted" size={14} />
                    )}
                    <span className={styles['itemName']}>
                      {item.title} <span className="muted small">{item.subtitle}</span>
                    </span>
                    {item.downloaded ? (
                      <CircleCheck aria-label="downloaded" className={styles['got']} size={14} />
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** The media row on Home; renders nothing on a server without media apps. */
export function MediaRow({ media }: { media: MediaSnapshot | undefined }): React.ReactNode {
  if (media === undefined) return null;
  const vpnShown = media.vpn !== undefined && !(media.vpn.available && !media.vpn.configured);
  const anything =
    vpnShown || media.qbittorrent !== undefined || media.sabnzbd !== undefined || media.plex !== undefined;
  if (!anything) return null;
  const cards = [
    media.vpn === undefined ? null : <VpnCard key="vpn" vpn={media.vpn} />,
    <DownloadsCard key="downloads" media={media} />,
    media.plex === undefined ? null : <PlayingCard key="plex" plex={media.plex} />,
    media.upcoming === undefined ||
    (media.upcoming.available && media.upcoming.items.length === 0 && media.plex === undefined) ? null : (
      <UpcomingCard key="upcoming" upcoming={media.upcoming} />
    ),
  ];
  return (
    <section aria-label="Media" className={styles['row']}>
      <h2 className="visually-hidden">Media</h2>
      {cards}
    </section>
  );
}
