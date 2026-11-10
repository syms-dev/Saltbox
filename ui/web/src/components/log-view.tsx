import { useEffect, useMemo, useRef } from 'react';

import { lineKind } from '../lib/ansible';
import styles from './log-view.module.css';

const MAX_LINES = 5_000;

type LogViewProps = {
  emptyText?: string;
  filter?: string;
  follow?: boolean;
  highlightLine?: number | null;
  label: string;
  lines: string[];
};

/**
 * A log pane with Ansible-aware colouring that sticks to the bottom while following.
 * Shows the last 5,000 lines; the raw log stays available for anything longer.
 */
export function LogView({
  emptyText = 'No output yet.',
  filter = '',
  follow = true,
  highlightLine = null,
  label,
  lines,
}: LogViewProps): React.ReactNode {
  const pane = useRef<HTMLDivElement>(null);
  const needle = filter.trim().toLowerCase();
  const shown = useMemo(() => {
    const numbered = lines.map((text, index) => ({ index, text }));
    const matching = needle === '' ? numbered : numbered.filter((l) => l.text.toLowerCase().includes(needle));
    return matching.slice(-MAX_LINES);
  }, [lines, needle]);
  const hidden = (needle === '' ? lines.length : shown.length) - shown.length;

  useEffect(() => {
    if (follow && pane.current !== null) pane.current.scrollTop = pane.current.scrollHeight;
  }, [follow, shown]);

  useEffect(() => {
    if (highlightLine === null || pane.current === null) return;
    pane.current.querySelector(`[data-line="${highlightLine}"]`)?.scrollIntoView({ block: 'center' });
  }, [highlightLine]);

  return (
    <div aria-label={label} aria-live="off" className={styles['log']} ref={pane} role="log" tabIndex={0}>
      {hidden > 0 ? <div className={styles['skip']}>{hidden} earlier lines not shown</div> : null}
      {shown.length === 0 ? (
        <div className={styles['skip']}>{needle === '' ? emptyText : 'No lines match the filter.'}</div>
      ) : (
        shown.map((line) => (
          <div
            className={`${styles['line']} ${styles[lineKind(line.text)]} ${line.index === highlightLine ? styles['mark'] : ''}`}
            data-line={line.index}
            key={line.index}
          >
            {line.text === '' ? ' ' : line.text}
          </div>
        ))
      )}
    </div>
  );
}
