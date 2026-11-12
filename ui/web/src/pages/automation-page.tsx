import { BellRing, CalendarClock, LoaderCircle, Send } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useApps, useAutomation, useRunMaintenance, useSaveAutomation, useTestAlert } from '../api/queries';
import type { AlertEvent, AutomationStatus } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusDot } from '../components/status-dot';
import { formatRelative, formatWhen } from '../format';
import styles from './automation-page.module.css';

const HIDDEN = '‹hidden›';
const EVENT_ORDER: AlertEvent[] = ['unhealthy', 'job_failed', 'vpn', 'disk', 'updates', 'maintenance'];

function AlertsCard({ data }: { data: AutomationStatus }): React.ReactNode {
  const alerts = data.settings.alerts;
  const [enabled, setEnabled] = useState(alerts.enabled);
  const [events, setEvents] = useState(alerts.events);
  const [url, setUrl] = useState(alerts.url);
  const [editingUrl, setEditingUrl] = useState(alerts.url === '');
  const save = useSaveAutomation();
  const test = useTestAlert();
  const toast = useToast();
  const dirty =
    enabled !== alerts.enabled ||
    url !== alerts.url ||
    EVENT_ORDER.some((event) => events[event] !== alerts.events[event]);

  return (
    <section aria-labelledby="alerts-title" className="card stack-sm">
      <div className="row">
        <h2 className={styles['title']} id="alerts-title">
          <BellRing aria-hidden="true" size={18} /> Alerts
        </h2>
        <span className="spacer" />
        <label className={styles['switch']}>
          <input checked={enabled} onChange={(e) => setEnabled(e.target.checked)} type="checkbox" /> Send alerts
        </label>
      </div>
      <p className="muted small">
        Get a message on your phone when something on the server needs you. Alerts use Apprise, the tool Saltbox already
        uses for its own notifications, so ntfy, Pushover, Discord, Telegram, email and{' '}
        <a href="https://github.com/caronc/apprise/wiki#notification-services" rel="noreferrer" target="_blank">
          many more
        </a>{' '}
        work.
      </p>
      {!data.apprise_available ? (
        <p className="note warn small">Apprise is not installed on this server, so alerts cannot be sent yet.</p>
      ) : null}
      <div className={styles['field']}>
        <label htmlFor="apprise-url">Send to (Apprise URL)</label>
        {editingUrl ? (
          <input
            id="apprise-url"
            onChange={(e) => setUrl(e.target.value)}
            placeholder={data.url_from_accounts ? 'Using the apprise address in accounts.yml' : 'ntfy://my-topic'}
            spellCheck={false}
            value={url === HIDDEN ? '' : url}
          />
        ) : (
          <div className="row">
            <code className={styles['hidden']}>{HIDDEN}</code>
            <button className="small" onClick={() => setEditingUrl(true)} type="button">
              Change
            </button>
          </div>
        )}
        {data.url_from_accounts && url === '' ? (
          <span className="muted small">Leave empty to keep using the apprise address from accounts.yml.</span>
        ) : null}
      </div>
      <fieldset className={styles['events']}>
        <legend>Tell me when</legend>
        {EVENT_ORDER.map((event) => (
          <label key={event}>
            <input
              checked={events[event]}
              onChange={(e) => setEvents((current) => ({ ...current, [event]: e.target.checked }))}
              type="checkbox"
            />{' '}
            {data.events[event]}
          </label>
        ))}
      </fieldset>
      <div className="row">
        <button
          className="primary"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(
              { alerts: { enabled, events, url: url === '' && !editingUrl ? HIDDEN : url } },
              {
                onError: (error) => toast({ body: error.message, title: 'Could not save', tone: 'danger' }),
                onSuccess: (saved) => {
                  setUrl(saved.settings.alerts.url);
                  setEditingUrl(saved.settings.alerts.url === '');
                  toast({ title: 'Alert settings saved', tone: 'ok' });
                },
              },
            )
          }
          type="button"
        >
          Save
        </button>
        <button
          disabled={dirty || test.isPending}
          onClick={() =>
            test.mutate(undefined, {
              onError: (error) => toast({ body: error.message, title: 'Test failed', tone: 'danger' }),
              onSuccess: (result) =>
                toast(
                  result.ok
                    ? { title: 'Test alert sent', tone: 'ok' }
                    : { body: result.message, title: 'Test alert not sent', tone: 'danger' },
                ),
            })
          }
          title={dirty ? 'Save first' : undefined}
          type="button"
        >
          {test.isPending ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <Send aria-hidden="true" size={15} />
          )}{' '}
          Send a test alert
        </button>
      </div>
    </section>
  );
}

function MaintenanceCard({ data }: { data: AutomationStatus }): React.ReactNode {
  const maintenance = data.settings.maintenance;
  const [enabled, setEnabled] = useState(maintenance.enabled);
  const [time, setTime] = useState(maintenance.time);
  const [exclude, setExclude] = useState(maintenance.exclude);
  const apps = useApps();
  const save = useSaveAutomation();
  const run = useRunMaintenance();
  const confirm = useConfirm();
  const toast = useToast();
  const installed = (apps.data ?? []).filter((app) => app.installed && app.containers.length > 0);
  const dirty =
    enabled !== maintenance.enabled ||
    time !== maintenance.time ||
    [...exclude].sort().join() !== [...maintenance.exclude].sort().join();
  const last = maintenance.last_run;

  async function runNow(): Promise<void> {
    const ok = await confirm({
      body: (
        <p>
          Checks for new images now and updates every app that has one
          {exclude.length > 0 ? ', except the ones you excluded' : ''}. Updated apps restart.
        </p>
      ),
      confirmLabel: 'Run maintenance',
      title: 'Run maintenance now?',
    });
    if (!ok) return;
    run.mutate(undefined, {
      onError: (error) => toast({ body: error.message, title: 'Could not start maintenance', tone: 'danger' }),
      onSuccess: () => toast({ href: '/activity', linkLabel: 'Activity', title: 'Maintenance started', tone: 'info' }),
    });
  }

  return (
    <section aria-labelledby="maintenance-title" className="card stack-sm">
      <div className="row">
        <h2 className={styles['title']} id="maintenance-title">
          <CalendarClock aria-hidden="true" size={18} /> Nightly maintenance
        </h2>
        <span className="spacer" />
        <label className={styles['switch']}>
          <input checked={enabled} onChange={(e) => setEnabled(e.target.checked)} type="checkbox" /> Run every night
        </label>
      </div>
      <p className="muted small">
        Updates apps with new images while you sleep, then sends one summary (with alerts on). Apps restart for a minute
        or two as they update.
      </p>
      <div className={styles['grid']}>
        <div className={styles['field']}>
          <label htmlFor="maintenance-time">Start at (server time)</label>
          <input id="maintenance-time" onChange={(e) => setTime(e.target.value)} type="time" value={time} />
        </div>
        <p className="muted small">
          Saltbox itself is not updated here: <code>sb update</code> shows announcements and can ask about migrations,
          so you start it yourself, from Home or System.
        </p>
      </div>
      <fieldset className={styles['events']}>
        <legend>Never update automatically</legend>
        {installed.length === 0 ? <span className="muted small">No apps installed.</span> : null}
        <div className={styles['excludes']}>
          {installed.map((app) => (
            <label key={app.role}>
              <input
                checked={exclude.includes(app.role)}
                onChange={(e) =>
                  setExclude((current) =>
                    e.target.checked ? [...current, app.role] : current.filter((role) => role !== app.role),
                  )
                }
                type="checkbox"
              />{' '}
              {app.title}
            </label>
          ))}
        </div>
      </fieldset>
      <dl className={styles['facts']}>
        <dt>Next run</dt>
        <dd>{data.next_maintenance === null ? 'off' : formatWhen(data.next_maintenance)}</dd>
        <dt>Last run</dt>
        <dd>
          {last === undefined ? (
            'never'
          ) : (
            <>
              {formatRelative(last.started_at)} ·{' '}
              {last.status === undefined ? 'running' : last.status === 'nothing' ? 'nothing to update' : last.status}
              {last.steps.map((step) => (
                <div className="small muted" key={step.what}>
                  {step.job === undefined ? step.what : <Link to={`/activity/${step.job}`}>{step.what}</Link>}:{' '}
                  {step.status}
                  {step.detail === undefined ? '' : ` (${step.detail})`}
                </div>
              ))}
            </>
          )}
        </dd>
      </dl>
      <div className="row">
        <button
          className="primary"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(
              { maintenance: { enabled, exclude, time } },
              {
                onError: (error) => toast({ body: error.message, title: 'Could not save', tone: 'danger' }),
                onSuccess: () => toast({ title: 'Maintenance settings saved', tone: 'ok' }),
              },
            )
          }
          type="button"
        >
          Save
        </button>
        <button disabled={dirty || run.isPending} onClick={() => void runNow()} type="button">
          Run now
        </button>
      </div>
    </section>
  );
}

function HistoryCard({ data }: { data: AutomationStatus }): React.ReactNode {
  return (
    <section aria-labelledby="history-title" className="card">
      <h2 id="history-title">Recent alerts</h2>
      {data.history.length === 0 ? (
        <p className="muted small">Nothing has happened that needed an alert.</p>
      ) : (
        <ul className={styles['history']}>
          {data.history.map((entry) => (
            <li key={`${entry.at}-${entry.title}`}>
              <StatusDot
                health={entry.sent ? { label: 'Sent', tone: 'ok' } : { label: 'Not sent', tone: 'muted' }}
                showLabel={false}
              />
              <span className={styles['entry']}>
                <strong>{entry.title}</strong>
                <span className="muted small">
                  {formatRelative(entry.at)}
                  {entry.sent
                    ? ''
                    : entry.result === undefined
                      ? ' · alerts off for this'
                      : ` · not sent: ${entry.result}`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AutomationPage(): React.ReactNode {
  const automation = useAutomation();
  if (automation.isPending) return <Loading what="automation" />;
  if (automation.isError) return <ErrorMessage error={automation.error} prefix="Automation" />;
  const data = automation.data;
  const key = JSON.stringify(data.settings);
  return (
    <div className="stack">
      <h1>Automation</h1>
      <div className={styles['pair']}>
        <AlertsCard data={data} key={`alerts-${key}`} />
        <MaintenanceCard data={data} key={`maintenance-${key}`} />
      </div>
      <HistoryCard data={data} />
    </div>
  );
}
