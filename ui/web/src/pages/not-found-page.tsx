import { Link } from 'react-router-dom';

export function NotFoundPage(): React.ReactNode {
  return (
    <div className="stack">
      <h1>Not found</h1>
      <p>
        <Link to="/">Back to the overview</Link>
      </p>
    </div>
  );
}
