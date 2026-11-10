/** Reading Ansible output: what failed, and how to colour each line. */

export type LineKind = 'changed' | 'error' | 'heading' | 'ok' | 'plain' | 'skip' | 'task' | 'warn';

const KINDS: [RegExp, LineKind][] = [
  [/^(fatal|failed):|FAILED!|\bERROR\b|\[ERROR\]|^\s*ERROR\s*$/, 'error'],
  [/^(TASK|RUNNING HANDLER) \[/, 'task'],
  [/^(PLAY|PLAY RECAP|TASKS RECAP)\b/, 'heading'],
  [/^changed:/, 'changed'],
  [/^ok:/, 'ok'],
  [/^(skipping|included):/, 'skip'],
  [/\[WARNING\]|\bWARN(ING)?\b|\[WARN\]/, 'warn'],
];

export function lineKind(line: string): LineKind {
  for (const [pattern, kind] of KINDS) if (pattern.test(line)) return kind;
  return 'plain';
}

export type Failure = { line: number; message: string; task: string | null };

const MSG = /"msg":\s*"((?:[^"\\]|\\.)*)"/;
const STDERR = /"stderr":\s*"((?:[^"\\]|\\.)*)"/;

function unescape(text: string): string {
  try {
    return JSON.parse(`"${text}"`) as string;
  } catch {
    return text;
  }
}

/**
 * The first failure in an Ansible log: the task it happened in and its message, so a
 * failed job can say "Failed at X: Y" instead of leaving people to scroll the log.
 */
export function findFailure(log: string): Failure | null {
  const lines = log.split('\n');
  let task: string | null = null;
  for (const [index, line] of lines.entries()) {
    const taskMatch = /^(?:TASK|RUNNING HANDLER) \[(.+?)\]/.exec(line);
    if (taskMatch !== null) task = taskMatch[1] ?? null;
    if (/^(fatal|failed): /.test(line)) {
      const message = MSG.exec(line)?.[1] ?? STDERR.exec(line)?.[1];
      return { line: index, message: message === undefined ? line : unescape(message), task };
    }
  }
  const error = lines.findIndex((line) => /^\s*ERROR\b|^ERROR!/.test(line));
  if (error >= 0) {
    const next = lines.slice(error + 1).find((line) => line.trim() !== '');
    return { line: error, message: (next ?? lines[error] ?? '').trim(), task };
  }
  return null;
}
