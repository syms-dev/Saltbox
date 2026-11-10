import type { UpdateState } from '../api/types';
import { StatusBadge } from './status-badge';

type OpenLinksProps = { urls: string[] };

/** "Open" links to an app's own web pages, in a new tab. */
export function OpenLinks({ urls }: OpenLinksProps): React.ReactNode {
  if (urls.length === 0) return null;
  return (
    <span className="row">
      {urls.map((url, index) => (
        <a aria-label={`Open ${new URL(url).host}`} href={url} key={url} rel="noreferrer" target="_blank" title={url}>
          {index === 0 ? 'Open ↗' : `${new URL(url).host} ↗`}
        </a>
      ))}
    </span>
  );
}

const UPDATE_LABELS: Record<UpdateState, string> = {
  current: 'up to date',
  unknown: 'not checked',
  update: 'update available',
};

const UPDATE_TONES: Record<UpdateState, string> = {
  current: 'succeeded',
  unknown: 'pending',
  update: 'interrupted',
};

type UpdateBadgeProps = { detail?: string; state: UpdateState };

export function UpdateBadge({ detail, state }: UpdateBadgeProps): React.ReactNode {
  return (
    <span title={detail ?? ''}>
      <StatusBadge label={UPDATE_LABELS[state]} status={UPDATE_TONES[state]} />
    </span>
  );
}

/** The most urgent update state across an app's containers. */
export function overallUpdate(states: UpdateState[]): UpdateState {
  if (states.includes('update')) return 'update';
  if (states.length > 0 && states.every((state) => state === 'current')) return 'current';
  return 'unknown';
}
