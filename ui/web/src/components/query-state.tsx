type LoadingProps = { what?: string };

export function Loading({ what = 'data' }: LoadingProps): React.ReactNode {
  return (
    <p aria-busy="true" className="muted">
      Loading {what}…
    </p>
  );
}

type ErrorMessageProps = { error: unknown; prefix?: string };

export function ErrorMessage({ error, prefix }: ErrorMessageProps): React.ReactNode {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" style={{ color: 'var(--color-danger)' }}>
      {prefix === undefined ? message : `${prefix}: ${message}`}
    </p>
  );
}
