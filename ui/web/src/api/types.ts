// Shapes returned by the saltbox-ui daemon (see saltbox_ui/daemon/routes.py).

export type Issue = {
  level: 'error' | 'warning';
  message: string;
  path: string;
};

export type JobStatus = 'failed' | 'interrupted' | 'pending' | 'running' | 'succeeded';

export type Job = {
  command: string[];
  command_line: string;
  finished_at: string | null;
  id: string;
  kind: string;
  log_path: string | null;
  returncode: number | null;
  started_at: string | null;
  status: JobStatus;
  tags: string[];
};

export type JobsStatus = {
  busy: boolean;
  current: Job | null;
  lock: Record<string, unknown> | null;
};

export type JobsResponse = JobsStatus & { jobs: Job[] };

export type JobRequest = {
  extra_vars?: string[];
  kind: 'install' | 'update' | 'validate';
  no_cache?: boolean;
  skip_tags?: string[];
  tags?: string[];
  verbose?: boolean;
  verbosity?: number;
};

export type Disk = {
  free: number;
  path: string;
  percent: number;
  total: number;
  used: number;
};

export type Mount = { source: string; target: string; type: string };

export type Unit = Record<string, string>;

export type ContainerSummary = {
  available: boolean;
  running: number;
  stopped: string[];
  total: number;
  unhealthy: string[];
};

export type Service = Record<string, unknown> & { service: string };

export type Overview = {
  config_issues: Record<string, Issue[]>;
  containers: ContainerSummary;
  host: { disks: Disk[]; mounts: Mount[]; reboot_required: boolean; units: Unit[] };
  install: { configs_present: boolean; installed: boolean; roles_with_facts: string[] };
  jobs: JobsStatus & { recent: Job[] };
  services: Service[];
};

export type ContainerState = { health: string | null; name: string; status: string };

export type App = {
  app_links: unknown[];
  categories: string[];
  containers: ContainerState[];
  default_instances: string[];
  docs_url: string;
  install_tag: string | null;
  installed: boolean;
  instances: string[];
  link: string;
  main_tags: string[];
  repo: 'saltbox' | 'sandbox';
  role: string;
  sb_tag: string | null;
  section: string;
  selector: string | null;
  summary: string;
  supports_instances: boolean;
  tags: string[];
  title: string;
  when: string[];
};

export type Field = {
  help: string;
  hidden: boolean;
  hidden_reason: string | null;
  jinja: boolean;
  line: number;
  name: string;
  raw: string;
  scope: string;
  section: string;
  subsection: string;
  suffix: string | null;
  type: string;
  value: unknown;
};

export type AppDetail = {
  app: Omit<App, 'containers' | 'installed' | 'instances'>;
  facts: Record<string, Record<string, string>>;
  fields: Field[];
  instances: string[];
  overrides: Record<string, Record<string, unknown>>;
};

export type ConfigFileSummary = {
  exists: boolean;
  filename: string;
  name: string;
  optional: boolean;
  schema: boolean;
  source: 'default' | 'file' | 'missing';
};

export type ConfigFile = {
  data: Record<string, unknown>;
  issues: Issue[];
  name: string;
  path: string;
  source: 'default' | 'file' | 'missing';
  text: string;
};

export type Inventory = {
  data: Record<string, unknown>;
  issues: Issue[];
  path: string;
  text: string;
};

export type Meta = {
  layout: Record<string, string>;
  saltbox: { branch: string | null; commit: string | null; remote: string | null };
  version: string;
  web: boolean;
};

export type StreamMessage = { text: string; type: 'log' } | { job: Job; type: 'done' };
