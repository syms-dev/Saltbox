// Shapes returned by the saltbox-ui daemon (see saltbox_ui/daemon/routes.py).

export type Issue = {
  level: 'error' | 'warning';
  message: string;
  path: string;
};

export type JobStatus = 'failed' | 'interrupted' | 'pending' | 'running' | 'succeeded';

/** An announcement `sb update` showed: Markdown text, and the migration tag it asks for, if any. */
export type Announcement = {
  date: string;
  message: string;
  migration: string | null;
  repo: string;
  title: string;
};

/** What a running job is waiting to be told: whether to run the migrations `sb update` listed. */
export type JobQuestion = {
  kind: 'migrations';
  migrations: { date: string; repo: string; tag: string }[];
  text: string;
};

export type Job = {
  announcements?: Announcement[];
  command: string[];
  command_line: string;
  finished_at: string | null;
  id: string;
  kind: string;
  log_path: string | null;
  question?: JobQuestion | null;
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
  verbosity?: number;
};

export type Disk = {
  free: number;
  path: string;
  paths?: string[];
  percent: number;
  total: number;
  used: number;
};

export type Mount = { source: string; target: string; type: string };

export type Unit = { active: string; description: string; sub: string; unit: string };

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
  updates: UpdatesSummary;
  host: { disks: Disk[]; mounts: Mount[]; reboot_packages?: string[]; reboot_required: boolean; units: Unit[] };
  install: { configs_present: boolean; installed: boolean; roles_with_facts: string[] };
  jobs: JobsStatus & { recent: Job[] };
  services: Service[];
};

export type UpdateState = 'current' | 'unknown' | 'update';

export type ContainerState = {
  health: string | null;
  image: string;
  name: string;
  status: string;
  update: UpdateState;
  update_detail: string;
  urls: string[];
};

/** A known error message: what it means and what to do about it. */
export type LogRule = {
  fix: string[];
  id: string;
  meaning: string;
  /** `problem`: something is not working. `notice`: harmless, but explains the noise. */
  severity: 'notice' | 'problem';
  title: string;
};

/** One error that recurs in a container's log; `message` is its latest occurrence. */
export type LogGroup = { count: number; last_seen: string; message: string; rule: LogRule | null };

export type LogProblems = {
  available: boolean;
  checked_at: number;
  containers: { app: AppRef | null; groups: LogGroup[]; name: string }[];
  scanned: number;
  window: string;
};

/** What uninstalling an app would remove, and what stands in the way. */
export type UninstallPlan = { blockers: string[]; containers: string[]; folders: string[]; instances: string[] };

export type UninstallResult = { deleted: string[]; kept: string[]; removed: string[] };

/** Enough of an app to name it and update it. */
export type AppRef = Pick<App, 'repo' | 'role' | 'title'> & { core?: boolean };

/** An app with a newer image for one or more of its containers. */
export type PendingUpdate = AppRef & { containers: string[]; core: boolean };

export type UpdatesSummary = {
  /** One entry per app to update; the daemon decides which app each container belongs to. */
  apps?: PendingUpdate[];
  checked_at: number | null;
  pending: string[];
  running: boolean;
  saltbox?: string[];
  /** Containers with a newer image that no Saltbox role is known for. */
  unknown?: string[];
};

/** A Saltbox checkout (saltbox, sandbox, saltbox_mod) compared with the branch it tracks. */
export type RepoStatus = {
  branch: string;
  commit: string;
  detail: string;
  name: string;
  path: string;
  remote_commit: string;
  source: string;
  status: UpdateState;
};

export type UpdatesResponse = {
  checked_at: number | null;
  error: string;
  images: Record<string, { containers: string[]; detail: string; image: string; status: UpdateState }>;
  repos?: RepoStatus[];
  running: boolean;
};

export type App = {
  app_links: AppLink[];
  categories: string[];
  containers: ContainerState[];
  /** Runs as part of Saltbox itself (Traefik, Authelia) rather than being an app someone picked. */
  core?: boolean;
  default_instances: string[];
  update_available: boolean;
  urls: string[];
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
  app: Omit<App, 'containers' | 'installed' | 'instances' | 'update_available' | 'urls'>;
  containers: ContainerState[];
  core?: boolean;
  installed: boolean;
  update_available: boolean;
  urls: string[];
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
  /** How many secrets the text shows as placeholders. */
  hidden?: number;
  issues: Issue[];
  name: string;
  path: string;
  source: 'default' | 'file' | 'missing';
  text: string;
};

export type Inventory = {
  data: Record<string, unknown>;
  hidden?: number;
  issues: Issue[];
  path: string;
  text: string;
};

export type Meta = {
  domain?: string | null;
  layout: Record<string, string>;
  saltbox: { branch: string | null; commit: string | null; remote: string | null };
  user?: string | null;
  version: string;
  web: boolean;
};

export type StreamMessage = { text: string; type: 'log' } | { job: Job; type: 'done' };

export type ContainerAction = 'restart' | 'start' | 'stop';

export type ContainerLogs = { lines: string[]; name: string };

export type SetupStatus = 'done' | 'error' | 'manual' | 'skip' | 'todo';

export type SetupTask = { app: string; detail: string; id: string; status: SetupStatus; title: string };

export type SetupResponse = { summary: Partial<Record<SetupStatus, number>>; tasks: SetupTask[] };

export type AppLink = { name: string; purpose: string; url: string };

export type HostStats = {
  cores: number;
  load: number[];
  load_percent: number | null;
  memory_percent: number | null;
  memory_total: number;
  memory_used: number;
  swap_total?: number;
  swap_used?: number;
  uptime: number | null;
};

/** qBittorrent's global seeding limits; `null` means that limit is off. */
export type SeedingLimits = {
  action: 'remove' | 'remove_files' | 'stop' | 'super_seed';
  days: number | null;
  inactive_days: number | null;
  ratio: number | null;
};

export type SeedingGroup = { count: number; size: number };

/** Finished torrents in qBittorrent: still seeding, or stopped and left there. */
export type SeedingStatus = {
  categories?: { name: string; seeding: number; stopped: number }[];
  error: string;
  installed: boolean;
  limits?: SeedingLimits;
  longest_seeding_days?: number;
  seeding?: SeedingGroup;
  stopped?: SeedingGroup;
  /** Apps in the catalogs that manage finished torrents by finer rules. */
  tools: (AppRef & { installed: boolean })[];
  /** No limit at all: nothing ever stops, so nothing is ever removed. */
  unlimited?: boolean;
};

export type ContainerStats = {
  cpu_percent: number;
  memory: number;
  memory_limit: number;
  memory_percent: number;
  name: string;
  pids: number;
};

export type Resources = { containers: ContainerStats[]; error: string; host: HostStats };

export type TailscaleStatus = {
  addresses?: string[];
  dns_name?: string;
  error?: string;
  hostname?: string;
  installed: boolean;
  magic_dns?: boolean;
  online?: boolean;
  owner?: string;
  peers?: number;
  peers_online?: number;
  running?: boolean;
  serve?: { enabled: boolean; error?: string; url?: string };
  state?: string;
  version?: string;
};

export type BackupSummary = {
  configured: boolean;
  destinations: { destination: string; enabled: boolean; kind: string }[];
  last_job: Job | null;
  latest: { age_seconds: number; modified: number; path: string; size: number } | null;
  schedule: string;
};

type Section<T> = ({ available: true } & T) | { available: false; error: string };

export type VpnStatus = {
  configured: boolean;
  container?: string;
  forwarded_port?: number | null;
  health?: string | null;
  public_ip?: string;
  qbittorrent_protected?: boolean;
  routed?: string[];
  running?: boolean;
};

export type DownloadItem = { eta?: number | null; name: string; progress: number; speed?: number; time_left?: string };

export type QbitStatus = { download_speed: number; downloading: number; items: DownloadItem[]; upload_speed: number };

export type SabStatus = {
  download_speed: number;
  downloading: number;
  items: DownloadItem[];
  paused: boolean;
  size_left: string;
  time_left: string;
};

export type PlexSession = {
  player: string;
  progress: number;
  state: string;
  subtitle: string;
  title: string;
  transcoding: boolean;
  type: string;
  user: string;
};

export type UpcomingItem = {
  app: string;
  date: string;
  downloaded: boolean;
  kind: 'episode' | 'movie';
  subtitle: string;
  title: string;
};

export type MediaSnapshot = {
  checked_at: number;
  plex?: Section<{ sessions: PlexSession[] }>;
  qbittorrent?: Section<QbitStatus>;
  sabnzbd?: Section<SabStatus>;
  upcoming?: Section<{ errors: string[]; items: UpcomingItem[] }>;
  vpn?: Section<VpnStatus>;
};

export type RecyclarrProfile = { default: boolean; name: string; summary: string; trash_id: string };

export type RecyclarrApp = 'radarr' | 'sonarr';

export type RecyclarrStatus = {
  config_exists: boolean;
  installed: boolean;
  instances: Record<RecyclarrApp, string[]>;
  last_job: Job | null;
  managed: boolean;
  profiles: Record<RecyclarrApp, RecyclarrProfile[]>;
  running: boolean;
  selected: Record<RecyclarrApp, string[]>;
};

export type AlertEvent = 'disk' | 'job_failed' | 'maintenance' | 'unhealthy' | 'updates' | 'vpn';

export type MaintenanceRun = {
  date: string;
  finished_at?: number;
  started_at: number;
  status?: 'failed' | 'nothing' | 'succeeded';
  steps: { detail?: string; job?: string; status: string; what: string }[];
};

export type AutomationSettings = {
  alerts: { enabled: boolean; events: Record<AlertEvent, boolean>; url: string };
  maintenance: { enabled: boolean; exclude: string[]; last_run?: MaintenanceRun; time: string };
};

export type AlertEntry = { at: number; body: string; event: AlertEvent; result?: string; sent: boolean; title: string };

export type AutomationStatus = {
  apprise_available: boolean;
  events: Record<AlertEvent, string>;
  history: AlertEntry[];
  next_maintenance: string | null;
  settings: AutomationSettings;
  url_from_accounts: boolean;
};
