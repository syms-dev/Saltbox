import { NavLink, Outlet } from 'react-router-dom';

import { useJobs, useMeta } from '../api/queries';
import { StatusBadge } from './status-badge';
import styles from './shell.module.css';

const NAV = [
  { label: 'Overview', to: '/' },
  { label: 'Apps', to: '/apps' },
  { label: 'Jobs', to: '/jobs' },
  { label: 'Config', to: '/config' },
] as const;

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles['navLink']} ${styles['navLinkActive']}` : (styles['navLink'] ?? '');
}

export function Shell(): React.ReactNode {
  const meta = useMeta();
  const jobs = useJobs();
  const current = jobs.data?.current ?? null;
  return (
    <div className={styles['shell']}>
      <aside className={styles['sidebar']}>
        <div className={styles['brand']}>
          <span className={styles['brandName']}>Saltbox</span>
          <span className={`muted ${styles['brandVersion']}`}>
            {meta.data
              ? `ui ${meta.data.version} · ${meta.data.saltbox.branch ?? '?'}@${meta.data.saltbox.commit ?? '?'}`
              : ''}
          </span>
        </div>
        <nav aria-label="Main" className={styles['nav']}>
          {NAV.map((item) => (
            <NavLink className={navClass} end={item.to === '/'} key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {current !== null ? (
          <div className={styles['currentJob']}>
            <StatusBadge status={current.status} />
            <NavLink to={`/jobs/${current.id}`}>
              {current.kind} {current.tags.join(',')}
            </NavLink>
          </div>
        ) : null}
        {meta.isError ? <p className={styles['offline']}>The daemon is not reachable.</p> : null}
      </aside>
      <main className={styles['main']}>
        <Outlet />
      </main>
    </div>
  );
}
