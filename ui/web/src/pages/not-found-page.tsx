import { Link } from 'react-router-dom';

export function NotFoundPage(): React.ReactNode {
  return (
    <div className="card empty">
      <h1>Page not found</h1>
      <p>That address is not part of the Saltbox UI.</p>
      <Link className="button primary" to="/">
        Go home
      </Link>
    </div>
  );
}
