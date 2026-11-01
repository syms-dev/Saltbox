import { Navigate, Route, Routes } from 'react-router-dom';

import { Shell } from './components/shell';
import { AppPage } from './pages/app-page';
import { AppsPage } from './pages/apps-page';
import { ConfigPage } from './pages/config-page';
import { JobPage } from './pages/job-page';
import { JobsPage } from './pages/jobs-page';
import { NotFoundPage } from './pages/not-found-page';
import { OverviewPage } from './pages/overview-page';

export const ROUTES = {
  APPS: '/apps',
  CONFIG: '/config',
  JOBS: '/jobs',
  OVERVIEW: '/',
  app: (repo: string, role: string) => `/apps/${repo}/${role}` as const,
  configFile: (name: string) => `/config/${name}` as const,
  job: (id: string) => `/jobs/${id}` as const,
} as const;

export function App(): React.ReactNode {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route element={<OverviewPage />} index />
        <Route element={<AppsPage />} path="apps" />
        <Route element={<AppPage />} path="apps/:repo/:role" />
        <Route element={<JobsPage />} path="jobs" />
        <Route element={<JobPage />} path="jobs/:id" />
        <Route element={<Navigate replace to="/config/accounts" />} path="config" />
        <Route element={<ConfigPage />} path="config/:name" />
        <Route element={<NotFoundPage />} path="*" />
      </Route>
    </Routes>
  );
}
