import styles from './meter.module.css';

const WARN = 85;
const DANGER = 95;

/** A usage bar that turns amber at 85% and red at 95%. */
export function Meter({ label, percent }: { label?: string; percent: number }): React.ReactNode {
  const tone = percent >= DANGER ? 'danger' : percent >= WARN ? 'warn' : 'ok';
  return (
    <div
      aria-label={label ?? `${percent}% used`}
      aria-valuemax={100}
      aria-valuemin={0}
      aria-valuenow={percent}
      className={styles['meter']}
      role="meter"
    >
      <div className={`${styles['fill']} ${styles[tone]}`} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}
