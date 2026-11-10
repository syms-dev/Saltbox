import { X } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import styles from './feedback.module.css';

// -- confirm --------------------------------------------------------------------------
export type ConfirmOptions = {
  body: React.ReactNode;
  confirmLabel: string;
  title: string;
  tone?: 'danger' | 'primary';
};

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

/** `await confirm({...})` resolves true when the person confirms, false otherwise. */
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (confirm === null) throw new Error('useConfirm needs a FeedbackProvider');
  return confirm;
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

function ConfirmDialog({ pending, onClose }: { onClose: (ok: boolean) => void; pending: Pending }): React.ReactNode {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (typeof element.showModal === 'function' && !element.open) element.showModal();
    else element.setAttribute('open', '');
  }, []);
  return (
    <dialog
      aria-labelledby="confirm-title"
      className={styles['dialog']}
      onCancel={(event) => {
        event.preventDefault();
        onClose(false);
      }}
      ref={dialog}
    >
      <form
        method="dialog"
        onSubmit={(event) => {
          event.preventDefault();
          onClose(true);
        }}
      >
        <h2 id="confirm-title">{pending.title}</h2>
        <div className={styles['body']}>{pending.body}</div>
        <div className={styles['actions']}>
          <button onClick={() => onClose(false)} type="button">
            Cancel
          </button>
          <button autoFocus className={pending.tone === 'danger' ? 'danger' : 'primary'} type="submit">
            {pending.confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}

// -- toasts -----------------------------------------------------------------------------
export type Toast = { body?: string; href?: string; linkLabel?: string; title: string; tone: 'danger' | 'info' | 'ok' };

type ToastFn = (toast: Toast) => void;

const ToastContext = createContext<ToastFn | null>(null);

export function useToast(): ToastFn {
  const toast = useContext(ToastContext);
  if (toast === null) throw new Error('useToast needs a FeedbackProvider');
  return toast;
}

const TOAST_MS = 7_000;

type Shown = Toast & { id: number };

// -- provider -----------------------------------------------------------------------------
export function FeedbackProvider({ children }: { children: React.ReactNode }): React.ReactNode {
  const [pending, setPending] = useState<Pending | null>(null);
  const [toasts, setToasts] = useState<Shown[]>([]);
  const nextId = useRef(0);

  const confirm = useCallback<ConfirmFn>(
    (options) => new Promise<boolean>((resolve) => setPending({ ...options, resolve })),
    [],
  );
  const dismiss = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const toast = useCallback<ToastFn>(
    (item) => {
      nextId.current += 1;
      const id = nextId.current;
      setToasts((list) => [...list.slice(-3), { ...item, id }]);
      setTimeout(() => dismiss(id), TOAST_MS);
    },
    [dismiss],
  );
  const close = useCallback(
    (ok: boolean) => {
      pending?.resolve(ok);
      setPending(null);
    },
    [pending],
  );

  const value = useMemo(() => ({ confirm, toast }), [confirm, toast]);
  return (
    <ConfirmContext.Provider value={value.confirm}>
      <ToastContext.Provider value={value.toast}>
        {children}
        {pending === null ? null : <ConfirmDialog onClose={close} pending={pending} />}
        <div aria-live="polite" className={styles['toasts']} role="status">
          {toasts.map((item) => (
            <div className={`${styles['toast']} ${styles[item.tone]}`} key={item.id}>
              <div className={styles['toastText']}>
                <strong>{item.title}</strong>
                {item.body === undefined ? null : <span>{item.body}</span>}
                {item.href === undefined ? null : (
                  <Link onClick={() => dismiss(item.id)} to={item.href}>
                    {item.linkLabel ?? 'View'}
                  </Link>
                )}
              </div>
              <button aria-label="Dismiss" className="ghost icon small" onClick={() => dismiss(item.id)} type="button">
                <X size={16} />
              </button>
            </div>
          ))}
        </div>
      </ToastContext.Provider>
    </ConfirmContext.Provider>
  );
}
