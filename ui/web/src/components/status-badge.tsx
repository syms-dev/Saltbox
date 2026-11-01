import styles from './status-badge.module.css';

type Tone = 'danger' | 'muted' | 'ok' | 'warn';

const TONES: Record<string, Tone> = {
  exited: 'muted',
  failed: 'danger',
  healthy: 'ok',
  interrupted: 'warn',
  pending: 'muted',
  running: 'ok',
  succeeded: 'ok',
  unhealthy: 'danger',
};

type StatusBadgeProps = {
  label?: string;
  status: string;
};

export function StatusBadge({ label, status }: StatusBadgeProps): React.ReactNode {
  const tone = TONES[status] ?? 'muted';
  return (
    <span className={`${styles['badge']} ${styles[tone]}`} role="status">
      {label ?? status}
    </span>
  );
}
