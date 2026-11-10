import { useState } from 'react';

import styles from './app-avatar.module.css';

const HUES = 360;

function hue(text: string): number {
  let hash = 0;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) % HUES;
  return hash;
}

export function initials(title: string): string {
  const words = title
    .replace(/[^\p{L}\p{N} ]/gu, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return '?';
  const [first = '', second = ''] = words;
  return (words.length > 1 ? first.charAt(0) + second.charAt(0) : first.slice(0, 2)).toUpperCase();
}

type AppAvatarProps = { size?: 'lg' | 'md' | 'sm'; title: string; url?: string | undefined };

/**
 * The app's own icon, fetched from the app through Traefik (the browser already holds the
 * Authelia session for the whole domain), over a coloured monogram that shows when the
 * app has no icon or cannot be reached. Nothing is loaded from outside the server.
 */
export function AppAvatar({ size = 'md', title, url }: AppAvatarProps): React.ReactNode {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const icon = url === undefined || failed ? null : `${new URL(url).origin}/favicon.ico`;
  return (
    <span
      aria-hidden="true"
      className={`${styles['avatar']} ${styles[size]}`}
      style={{ '--hue': hue(title) } as React.CSSProperties}
    >
      {loaded ? null : initials(title)}
      {icon === null ? null : (
        <img
          alt=""
          className={loaded ? styles['icon'] : styles['hidden']}
          decoding="async"
          loading="lazy"
          onError={() => setFailed(true)}
          onLoad={(event) => {
            if (event.currentTarget.naturalWidth > 0) setLoaded(true);
            else setFailed(true);
          }}
          referrerPolicy="no-referrer"
          src={icon}
        />
      )}
    </span>
  );
}
