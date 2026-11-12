import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { JobQuestion } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { Announcements, MigrationQuestion, recap } from './job-page';

const QUESTION: JobQuestion = {
  kind: 'migrations',
  migrations: [{ date: '2031-01-01', repo: 'Saltbox', tag: 'move-things' }],
  text: '  1  Saltbox   move-things   2031-01-01',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('recap', () => {
  it('sums the play recap over hosts', () => {
    expect(recap('localhost : ok=3 changed=1 failed=0\nother : ok=2 changed=0 failed=1')).toMatchObject({
      changed: 1,
      failed: 1,
      ok: 5,
    });
    expect(recap('no recap here')).toBeNull();
  });
});

describe('MigrationQuestion', () => {
  it('lists the tags sb wants to run and sends the answer that was clicked', async () => {
    const api = stubApi({ 'POST /jobs/j1/answer': { answered: true } });
    renderAt(<MigrationQuestion id="j1" question={QUESTION} />);
    expect(screen.getByRole('alert')).toHaveTextContent('waiting for your answer');
    expect(screen.getByRole('row', { name: 'Saltbox move-things 2031-01-01' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Skip them' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/jobs/j1/answer',
        expect.objectContaining({ body: JSON.stringify({ answer: false }), method: 'POST' }),
      ),
    );
  });

  it('shows what sb printed when the table could not be read', () => {
    stubApi({});
    renderAt(<MigrationQuestion id="j1" question={{ ...QUESTION, migrations: [] }} />);
    expect(screen.getByText('1 Saltbox move-things 2031-01-01', { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});

describe('Announcements', () => {
  it('shows each announcement with where it came from and its migration tag', () => {
    renderAt(
      <Announcements
        items={[
          {
            date: '2031-01-01',
            message: '## Moved\n\nRead this.',
            migration: 'move-things',
            repo: 'Saltbox',
            title: 'Breaking',
          },
          { date: '2031-02-01', message: 'Smaller news.', migration: null, repo: 'Sandbox', title: 'Notice' },
        ]}
      />,
    );
    const region = screen.getByRole('region', { name: 'Announcements from this update' });
    expect(region).toHaveTextContent('Breaking');
    expect(region).toHaveTextContent('Saltbox · 2031-01-01 · migration tag move-things');
    expect(region).toHaveTextContent('Read this.');
    expect(region).toHaveTextContent('Sandbox · 2031-02-01');
  });
});
