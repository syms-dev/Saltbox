import type { Health } from '../lib/status';
import styles from './status-dot.module.css';

type StatusDotProps = { health: Health; showLabel?: boolean };

/** A coloured dot with the state in words beside it (or for screen readers only). */
export function StatusDot({ health, showLabel = true }: StatusDotProps): React.ReactNode {
  return (
    <span className={`${styles['status']} ${styles[health.tone]}`}>
      <span aria-hidden="true" className={styles['dot']} />
      <span className={showLabel ? '' : 'visually-hidden'}>{health.label}</span>
    </span>
  );
}
