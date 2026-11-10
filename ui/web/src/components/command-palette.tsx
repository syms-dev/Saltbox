import {
  Activity,
  ArrowUpCircle,
  Cable,
  ExternalLink,
  FileCog,
  HardDrive,
  House,
  LayoutGrid,
  PackagePlus,
  RefreshCw,
  Search,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useApps, useCheckUpdates } from '../api/queries';
import { useJobActions } from '../lib/actions';
import { hostOf } from '../lib/status';
import { AppAvatar } from './app-avatar';
import { useToast } from './feedback';
import styles from './command-palette.module.css';

export type Command = {
  group: string;
  icon: React.ReactNode;
  id: string;
  keywords?: string;
  label: string;
  hint?: string;
  run: () => void;
};

/** Rank commands: label starts with the query, then a word does, then it appears anywhere. */
export function rankCommands(commands: Command[], query: string, limit = 40): Command[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return commands.slice(0, limit);
  const words = needle.split(/\s+/);
  const scored: [number, Command][] = [];
  for (const command of commands) {
    const label = command.label.toLowerCase();
    const haystack = `${label} ${command.keywords ?? ''} ${command.hint ?? ''}`.toLowerCase();
    if (!words.every((word) => haystack.includes(word))) continue;
    const score = label.startsWith(needle) ? 0 : label.split(/\s+/).some((w) => w.startsWith(words[0] ?? '')) ? 1 : 2;
    scored.push([score, command]);
  }
  const ranked = scored
    .sort((a, b) => a[0] - b[0])
    .slice(0, limit)
    .map(([, command]) => command);
  // Keep each group together, groups in the order of their best match.
  const order = [...new Set(ranked.map((command) => command.group))];
  return order.flatMap((group) => ranked.filter((command) => command.group === group));
}

const ICON = 18;

function useCommands(query: string, close: () => void): Command[] {
  const navigate = useNavigate();
  const apps = useApps();
  const check = useCheckUpdates();
  const actions = useJobActions();
  const toast = useToast();

  return useMemo(() => {
    const go = (to: string) => () => {
      close();
      void navigate(to);
    };
    const all = apps.data ?? [];
    const installed = all.filter((app) => app.installed);
    const pending = installed.filter((app) => app.update_available);
    const commands: Command[] = [
      { group: 'Go to', icon: <House size={ICON} />, id: 'home', label: 'Home', run: go('/') },
      { group: 'Go to', icon: <LayoutGrid size={ICON} />, id: 'apps', label: 'Installed apps', run: go('/apps') },
      {
        group: 'Go to',
        icon: <PackagePlus size={ICON} />,
        id: 'discover',
        keywords: 'catalog install new add browse',
        label: 'Discover apps',
        run: go('/apps/discover'),
      },
      {
        group: 'Go to',
        icon: <Activity size={ICON} />,
        id: 'activity',
        keywords: 'jobs log history',
        label: 'Activity',
        run: go('/activity'),
      },
      {
        group: 'Go to',
        icon: <HardDrive size={ICON} />,
        id: 'system',
        keywords: 'storage disks mounts space services version',
        label: 'System and storage',
        run: go('/system'),
      },
      {
        group: 'Go to',
        icon: <Cable size={ICON} />,
        id: 'connect',
        keywords: 'setup wire download clients indexers',
        label: 'Connect apps',
        run: go('/connect'),
      },
      {
        group: 'Go to',
        icon: <FileCog size={ICON} />,
        id: 'config',
        keywords: 'settings accounts yaml inventory',
        label: 'Config files',
        run: go('/config'),
      },
      {
        group: 'Actions',
        icon: <RefreshCw size={ICON} />,
        id: 'check-updates',
        keywords: 'refresh images',
        label: 'Check for updates',
        run: () => {
          close();
          check.mutate(undefined, { onSuccess: () => toast({ title: 'Checking for updates…', tone: 'info' }) });
        },
      },
      {
        group: 'Actions',
        icon: <ArrowUpCircle size={ICON} />,
        id: 'sb-update',
        keywords: 'saltbox upgrade git pull',
        label: 'Update Saltbox (sb update)',
        run: () => {
          close();
          void actions.updateSaltbox();
        },
      },
    ];
    if (pending.length > 0) {
      commands.push({
        group: 'Actions',
        icon: <ArrowUpCircle size={ICON} />,
        id: 'update-all',
        hint: pending.map((a) => a.title).join(', '),
        label: `Update ${pending.length} app${pending.length === 1 ? '' : 's'}`,
        run: () => {
          close();
          void actions.updateAll(pending);
        },
      });
    }
    for (const app of installed) {
      const url = app.urls[0];
      if (url === undefined) continue;
      commands.push({
        group: 'Open',
        hint: hostOf(url),
        icon: <AppAvatar size="sm" title={app.title} url={url} />,
        id: `open:${app.repo}/${app.role}`,
        keywords: app.role,
        label: `Open ${app.title}`,
        run: () => {
          close();
          window.open(url, '_blank', 'noopener');
        },
      });
    }
    // The whole catalog only once someone types: 200+ apps would bury everything else.
    const catalog = query.trim() === '' ? installed : all;
    for (const app of catalog) {
      commands.push({
        group: app.installed ? 'Manage' : 'Install',
        hint: app.installed ? 'installed' : app.repo === 'sandbox' ? 'sandbox app' : 'not installed',
        icon: <AppAvatar size="sm" title={app.title} />,
        id: `app:${app.repo}/${app.role}`,
        keywords: `${app.role} ${app.categories.join(' ')} ${app.summary}`,
        label: app.title,
        run: go(`/apps/${app.repo}/${app.role}`),
      });
    }
    return commands;
  }, [actions, apps.data, check, close, navigate, query, toast]);
}

type CommandPaletteProps = { onClose: () => void };

export function CommandPalette({ onClose }: CommandPaletteProps): React.ReactNode {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const commands = useCommands(query, onClose);
  const results = useMemo(() => rankCommands(commands, query), [commands, query]);

  useEffect(() => {
    const element = dialog.current;
    if (element !== null && typeof element.showModal === 'function' && !element.open) element.showModal();
  }, []);

  useEffect(() => {
    dialog.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  function onKeyDown(event: React.KeyboardEvent): void {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      results[active]?.run();
    }
  }

  let lastGroup = '';
  return (
    <dialog
      aria-label="Search and commands"
      className={styles['palette']}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
      ref={dialog}
    >
      <div className={styles['search']}>
        <Search aria-hidden="true" size={18} />
        <input
          aria-activedescendant={results[active] === undefined ? undefined : `command-${active}`}
          aria-controls="command-results"
          aria-label="Search apps, pages and actions"
          autoComplete="off"
          autoFocus
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          placeholder="Search apps, pages and actions…"
          role="combobox"
          aria-expanded="true"
          value={query}
        />
        <kbd>Esc</kbd>
      </div>
      <ul className={styles['results']} id="command-results" role="listbox">
        {results.length === 0 ? <li className={styles['none']}>Nothing matches “{query}”.</li> : null}
        {results.map((command, index) => {
          const heading = command.group !== lastGroup ? command.group : null;
          lastGroup = command.group;
          return (
            <li key={command.id} role="presentation">
              {heading === null ? null : <div className={styles['group']}>{heading}</div>}
              <div
                aria-selected={index === active}
                className={styles['item']}
                data-index={index}
                id={`command-${index}`}
                onClick={command.run}
                onMouseMove={() => setActive(index)}
                role="option"
              >
                <span className={styles['icon']}>{command.icon}</span>
                <span className={styles['label']}>{command.label}</span>
                {command.hint === undefined ? null : <span className={styles['hint']}>{command.hint}</span>}
                {command.group === 'Open' ? <ExternalLink aria-hidden="true" size={14} /> : null}
              </div>
            </li>
          );
        })}
      </ul>
      <div className={styles['footer']}>
        <span>
          <kbd>↑</kbd> <kbd>↓</kbd> to move
        </span>
        <span>
          <kbd>Enter</kbd> to run
        </span>
      </div>
    </dialog>
  );
}
