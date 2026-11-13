import { useCheckSelf, useJobs, useSelf } from '../api/queries';
import type { SelfStatus } from '../api/types';
import { useJobActions } from '../lib/actions';
import type { Attention } from '../pages/home-attention';
import styles from './saltbox-updates.module.css';

/** What is installed, in one line: "0.1.0, from a source checkout at abc1234". */
export function installedLine(status: SelfStatus): string {
  if (status.mode === 'wheel') return `${status.version}, installed from a release`;
  const at = status.source === null || status.source.commit === '' ? '' : ` at ${status.source.commit}`;
  return `${status.version}, running from a source checkout${at}`;
}

/** What there is to update to, or why that cannot be said. */
export function newerLine(status: SelfStatus): string {
  if (!status.update_available) return status.can_update ? 'Up to date.' : status.detail;
  if (status.mode === 'wheel') return `Version ${status.latest?.version ?? '?'} is available.`;
  const commit = status.source?.remote_commit ?? '';
  return `New commits are available${commit === '' ? '' : ` (${commit})`}.`;
}

/** A newer version of this app is one more thing Home can offer to do. */
export function selfAttention(status: SelfStatus | undefined): Attention[] {
  if (status === undefined || !status.update_available || !status.can_update) return [];
  return [
    {
      actions: [{ kind: 'selfUpdate', label: 'Update Saltbox UI' }],
      detail: newerLine(status),
      id: 'self-update',
      title: 'Saltbox UI update available',
      tone: 'info',
    },
  ];
}

/** This app's own version, and the button that updates it. */
export function SelfUpdateCard(): React.ReactNode {
  const self = useSelf();
  const jobs = useJobs();
  const check = useCheckSelf();
  const actions = useJobActions();
  const status = self.data;
  const busy = jobs.data?.busy ?? false;
  return (
    <section aria-labelledby="self-title" className="card" id="saltbox-ui">
      <div className="row">
        <h2 className={styles['title']} id="self-title">
          Saltbox UI version
        </h2>
        <button disabled={check.isPending || self.isPending} onClick={() => check.mutate()} type="button">
          Check now
        </button>
        <button
          className={status?.update_available === true ? 'primary' : ''}
          disabled={busy || status === undefined || !status.can_update || !status.update_available}
          onClick={() => void actions.updateSelf()}
          type="button"
        >
          Update Saltbox UI
        </button>
      </div>
      {status === undefined ? (
        <p className="muted">{self.isError ? `Could not check: ${self.error.message}` : 'Checking…'}</p>
      ) : (
        <>
          <p className={styles['flush']}>{installedLine(status)}</p>
          <p className={`muted ${styles['flush']}`}>{newerLine(status)}</p>
        </>
      )}
    </section>
  );
}
