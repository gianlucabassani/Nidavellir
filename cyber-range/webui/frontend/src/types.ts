export type Workspace = "research" | "benchmark" | "range";
export type Theme = "day" | "night";
export type Session = {
  id: string;
  name: string;
  status: string;
  scenario: string;
  expires_at: string | null;
  provider: string;
  nodes: { name: string; foothold: boolean }[];
};
export type Finding = {
  id: string | null;
  title: string;
  arena_id: string | null;
  arena_name: string;
  arena_known: boolean;
  verdict: string;
};
export type ResearchData = {
  sessions: Session[];
  review: Finding[];
  observed_at: string;
};
export type Build = {
  id: string;
  name: string;
  version: string;
  driver: string;
};
export type Challenge = {
  id: string;
  name: string;
  version: string;
  label: string;
};
export type Suite = {
  id: string;
  name: string;
  version: string;
  challenge_count: number;
  seed_count: number;
};
export type Evaluation = {
  id: string;
  state: string;
  suite_id: string;
  baseline_id: string;
  candidate_id: string;
};
export type BenchmarkData = {
  builds: Build[];
  challenges: Challenge[];
  suites: Suite[];
  evaluations: Evaluation[];
  source_arenas: { id: string; name: string }[];
  source_arenas_available: boolean;
  observed_at: string;
};
export type EvaluationDetailData = {
  id: string;
  state: string;
  evidence_scope: string;
  leakage_labels: string[];
  matched_pairs: number | null;
  infrastructure_failed_pairs: number | null;
  progress: { total: number; finished: number; running: number };
  differences: Record<
    string,
    {
      mean: number | null;
      pairs: number | null;
      bootstrap_95: [number, number] | null;
      interval_status: string | null;
    }
  >;
  challenges: {
    id: string;
    name: string;
    leakage_label: string;
    matched_pairs: number;
    infrastructure_failed_pairs: number;
    verified_mean: number | null;
  }[];
  trials: {
    id: string;
    seed: number;
    state: string;
    arena_id: string | null;
    side: string | null;
    challenge_id: string | null;
    error: string | null;
  }[];
  observed_at: string;
};
export type Scenario = {
  id: string;
  name: string;
  description: string;
  nodes: number;
  source: string;
  provider_class: string;
  tags: string[];
};
export type Arena = {
  id: string;
  name: string;
  status: string;
  scenario: string;
};
export type RangeData = {
  scenarios: Scenario[];
  arenas: Arena[];
  observed_at: string;
  simulation_mode: boolean;
};
export type TopologyData = {
  topology: {
    nodes: { name: string; kind: string; role: string }[];
    segments: { name: string; nodes: string[] }[];
    egress: string;
  } | null;
};
export type ArenaData = {
  id: string;
  name: string;
  state: string;
  scenario: string;
  provider: string;
  simulation_mode: boolean;
  expires_at: string | null;
  observed_at: string;
  budget: { remaining: number | null; cap: number | null; gate: string | null };
  reset: { status: string; reason: string | null };
  nodes: {
    name: string;
    state: string;
    foothold: boolean;
    service_count: number;
    web_capable: boolean;
    role?: string | null;
    image?: string | null;
    image_pinned?: boolean;
    declared_ports?: number[];
    segments?: string[];
    private_ip?: string | null;
    url?: string | null;
    ready?: boolean | null;
  }[];
  capabilities?: Record<string, { state: string; reason: string }> | null;
  topology: {
    segments: { name: string; nodes: string[] }[];
    unsegmented: string[];
  } | null;
  events: { type: string; ts: string; actor: string }[];
  findings: { id: string; title: string; verdict: string }[];
  poc_jobs: { id: string; status: string }[];
};
export type ResearchPreview = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  summary: { name?: string; nodes?: number; provider_class?: string };
  topology: {
    nodes: { name: string; kind: string; role: string; ports: number[] }[];
    segments: { name: string; nodes: string[] }[];
    egress: string | null;
  };
  resolved_ref: string | null;
  runtime_ref: string | null;
  introspection: {
    build_system?: string;
    declared_ports?: number[];
    platform?: string;
  };
  build_plan: { strategy?: string; auto_build?: boolean };
};
export type PocJob = {
  id: string;
  state: string;
  target_node: string | null;
  input_digest: string;
  cleanup_state: string | null;
  cleanup_error?: string | null;
  created_at: string | null;
  result?: {
    stdout?: string;
    stderr?: string;
    stdout_sha256?: string;
    stderr_sha256?: string;
    error?: string;
    artifacts?: { path: string; bytes: number; sha256: string }[];
  };
};
export type FindingRecord = {
  id: string;
  title: string;
  cwe: string | null;
  node: string | null;
  evidence: string | null;
  poc: string | null;
  source: string;
  verdict: string;
  manual_verdict: string | null;
  validation_reason: string | null;
  artifacts: { digest: string; bytes: number }[];
  transactions: {
    digest: string;
    method: string;
    path: string;
    status: number;
  }[];
};
export type EvidenceData = {
  artifacts: {
    finding_id: string;
    finding_title: string;
    digest: string;
    bytes: number;
  }[];
  validations: {
    finding_id: string;
    finding_title: string;
    kind: "effect" | "control";
    digest: string;
  }[];
  transactions: {
    finding_id: string;
    finding_title: string;
    digest: string;
    method: string;
    path: string;
    status: number;
  }[];
  signals: {
    kind: string | null;
    node: string | null;
    severity: string | null;
    summary: string | null;
    ts: string | null;
  }[];
  observed_at: string;
};
export type HttpTransaction = {
  digest: string;
  created_at: string;
  replay_of: string | null;
  request: {
    node: string;
    method: string;
    path: string;
    params: Record<string, string>;
    headers: Record<string, string>;
    body: string | null;
  };
  response: {
    status: number;
    reason?: string;
    headers?: Record<string, string>;
    body?: string;
    body_bytes?: number;
    body_sha256?: string;
    truncated?: boolean;
  };
};
export type HttpTransactionManifest = {
  digest: string;
  created_at: string;
  replay_of: string | null;
  bytes: number;
  actor: string | null;
  elapsed_ms: number | null;
};
export type ActivityData = {
  findings: {
    id: string;
    title: string;
    verdict: string;
    artifact_count: number;
    arena_id: string | null;
    arena_name: string;
    arena_known: boolean;
    ts: string | null;
  }[];
  artifacts: {
    digest: string;
    bytes: number;
    finding_title: string;
    arena_id: string | null;
    arena_name: string;
    arena_known: boolean;
    ts: string | null;
  }[];
  signals: {
    kind: string | null;
    node: string | null;
    severity: string | null;
    summary: string | null;
    arena_id: string | null;
    arena_name: string;
    arena_known: boolean;
    ts: string | null;
  }[];
  audit: {
    type: string;
    ts: string | null;
    actor: string;
    source: string;
    arena_id: string | null;
    arena_name: string;
    arena_known: boolean;
  }[];
  observed_at: string;
};
export type AgentsData = {
  builds: (Build & { digest: string })[];
  connections: {
    arena_id: string | null;
    arena_name: string;
    stance: string;
    model: string | null;
    provider: string | null;
    actor: string | null;
    last_seen: string | null;
    active: boolean;
    commands: number;
    findings: number;
  }[];
  timeline: {
    ts: string | null;
    arena_id: string | null;
    arena_name: string;
    type: string;
    actor: string | null;
    stance: string | null;
    summary: string;
  }[];
  observed_at: string;
};
export type SettingsData = {
  system_stop: { state: string };
  model_connection: {
    configured: boolean;
    provider: string | null;
    model: string | null;
    base_url: string | null;
    available: boolean;
  };
  observed_at: string;
};

export const paths: Record<Workspace, string> = {
  research: "/api/console/research",
  benchmark: "/api/console/benchmark",
  range: "/api/console/range",
};
