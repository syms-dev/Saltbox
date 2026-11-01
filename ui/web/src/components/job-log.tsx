import { useEffect, useRef } from 'react';

import styles from './job-log.module.css';

type JobLogProps = {
  follow?: boolean;
  text: string;
};

/** A scrolling log pane that sticks to the bottom while the job runs. */
export function JobLog({ follow = true, text }: JobLogProps): React.ReactNode {
  const pane = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (follow && pane.current !== null) pane.current.scrollTop = pane.current.scrollHeight;
  }, [follow, text]);
  return (
    <pre aria-live="polite" className={styles['log']} ref={pane} tabIndex={0}>
      {text === '' ? 'waiting for output…' : text}
    </pre>
  );
}
