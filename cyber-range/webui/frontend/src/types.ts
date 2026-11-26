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
  challenge_ids: string[];
  seeds: number[];
  action_cap: number | null;
  deadline_seconds: number | null;
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
    score: number | null;
    passed: boolean | number | null;
    cost_usd: number | null;
    duration_seconds: number | null;
    actions: number | null;
    tokens: number | null;
  }[];
  suite_id: string | null;
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
  gateway_url?: string;
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
  events: { id?: number; type: string; ts: string; actor: string }[];
  deploy_phases?: DeployPhase[];
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
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type FindingRecord = {
  id: string;
  title: string;
  /** The reporter's own rating (UX-18): a claim, never used for scoring. */
  severity: Severity | null;
  at: string | null;
  validator_verdict: string;
  arena_id?: string | null;
  arena_name?: string | null;
  arena_known?: boolean;
  arena_state?: string | null;
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
  preview_clipped?: boolean;
  request: {
    node: string;
    method: string;
    path: string;
    params: Record<string, string>;
    headers: Record<string, string>;
    withheld_headers?: string[];
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
  summary?: {
    method: string | null;
    path: string | null;
    node: string | null;
    status: number | null;
    response_bytes: number | null;
  } | null;
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

export type FindingReview = {
  verdict: string;
  recorded_verdict: string | null;
  reason_code: string | null;
  validator_id: string | null;
  validator_version: number | null;
  recipe_digest: string | null;
  target_identity_digest: string | null;
  actor: {
    identity: string | null;
    digest: string;
    request: Record<string, unknown>;
    response: Record<string, unknown>;
    headers_withheld: boolean;
  } | null;
  controls: {
    name: string;
    state: "passed" | "failed" | "observational" | "unresolved";
    expected: Record<string, unknown>;
    observed: Record<string, unknown> | null;
    request: Record<string, unknown> | null;
  }[];
  effect: { digest: string; data: Record<string, unknown> } | null;
  control_digest: string | null;
  can_refute: boolean;
  refutation_allowed: boolean;
  unresolved: string[];
};

export type HttpComparison = {
  left: HttpTransaction;
  right: HttpTransaction;
  captured_body_equal: boolean | null;
  body_diff: string;
  response_headers_diff: string;
  complete: boolean;
  unresolved: string[];
  interpretation: string;
};
export type HttpRequestGroup = {
  group_id: string;
  name: string;
  notes: string;
  left: { digest: string; label: string };
  right: { digest: string; label: string };
};

// Source review (UI-R4). Machine fields come from a frozen snapshot; only
// `review` reflects operator judgment.
export type ReviewState =
  "unreviewed" | "in_review" | "dismissed" | "candidate";
export type ReviewStateCounts = Record<ReviewState, number>;
export type SourceReviewListItem = {
  session_id: string;
  name: string;
  commit_sha: string;
  repo_label: string | null;
  created_at: string;
  actor: string;
  capture_state: "capturing" | "complete" | "failed";
  complete: boolean;
  review_progress: {
    total_sites: number;
    by_review_state: ReviewStateCounts;
  } | null;
};
export type SourceReviewPattern = {
  pattern: string;
  total_matches: number | null;
  total_matches_complete: boolean | null;
  retained_sites: number | null;
  truncation_notes: string[];
  by_status: Record<string, number>;
  by_classification: Record<string, number>;
  by_review_state: Partial<ReviewStateCounts>;
};
export type SourceReviewFixLinkSummary = {
  link_id: string;
  label: string;
  advisory_id: string | null;
  fix_ref: string;
  affected_ref: string;
  fixed_ref: string;
  counts_complete: boolean | null;
};
export type SourceReviewSummary = {
  schema: string;
  session_id: string;
  name: string;
  created_at: string;
  actor: string;
  repo_id: string;
  repo_label: string | null;
  commit_sha: string;
  requested_ref: string;
  path_scope: string[];
  snapshot_digest: string | null;
  capture_state: "capturing" | "complete" | "failed";
  patterns: SourceReviewPattern[];
  complete: boolean;
  unresolved: string[];
  fix_links: SourceReviewFixLinkSummary[];
};
export type SiteReview = {
  state: ReviewState;
  note: string | null;
  finding_id: string | null;
  actor: string | null;
  at: string | null;
};
export type SourceReviewSite = {
  site_key: string;
  file: string;
  line: number;
  status: string;
  classification: string;
  evidence: string;
  evidence_clipped: boolean;
  review: SiteReview;
  review_history: SiteReview[];
  review_history_total: number;
  fix_links_touching_file: { link_id: string; label: string }[];
};
export type SourceReviewSitesPage = {
  session_id: string;
  pattern: string;
  sites: SourceReviewSite[];
  offset: number;
  next_offset: number | null;
  filtered_total: number;
  pattern_total: number;
  snapshot_digest: string;
};
export type SourceReviewAnswer = {
  data: Record<string, unknown>;
  truncation: { truncated: boolean; note: string };
  digest: string;
};
export type SourceReviewFixLink = SourceReviewFixLinkSummary & {
  requested_fix_ref: string;
  requested_affected_ref: string;
  requested_fixed_ref: string;
  fix_lookup: SourceReviewAnswer;
  layer_diff: SourceReviewAnswer;
  snapshot_digest: string;
};

// --- Research campaigns (NV-14) ----------------------------------------------
export type DisclosureState =
  "internal" | "reported" | "fixed" | "published" | "regressed";
export type CampaignDisclosure = {
  state: DisclosureState;
  note: string | null;
  reference: string | null;
  actor: string | null;
  at: string | null;
};
export type CampaignIdentity = {
  known: boolean;
  scenario: string | null;
  provider: string | null;
  recipe_digest: string | null;
  images: Record<
    string,
    {
      image: string | null;
      image_pinned: boolean;
      source_repo: string | null;
      source_ref: string | null;
    }
  >;
};
export type CampaignIdentityEntry = {
  finding_id: string;
  arena_id: string;
  identity: CampaignIdentity;
};
export type CampaignBundleRef = {
  bundle_digest: string;
  bytes: number;
  include_poc: boolean;
  include_evidence: boolean;
  unresolved_artifacts: number;
  actor: string;
  at: string;
};
export type CampaignFinding = {
  research_key: string;
  added_at: string;
  added_by: string;
  available: boolean;
  title: string | null;
  cwe: string | null;
  members: {
    finding_id: string;
    arena_id: string;
    scenario: string | null;
    verdict: { verdict: string | null; validator_id: string | null };
  }[];
  identities: {
    affected: CampaignIdentityEntry[];
    not_observed_under_controls: CampaignIdentityEntry[];
    unknown: CampaignIdentityEntry[];
  };
  comparison: { outcome: string } | null;
  disclosure: CampaignDisclosure;
  disclosure_history: CampaignDisclosure[];
  disclosure_history_total: number;
  state_supported_by_evidence: boolean | null;
  bundles: CampaignBundleRef[];
  bundles_total: number;
};
export type CampaignSummary = {
  schema: string;
  campaign_id: string;
  name: string;
  product: string;
  note: string | null;
  created_at: string;
  actor: string;
  findings: CampaignFinding[];
  by_disclosure_state: Record<DisclosureState, number>;
  unresolved: string[];
};
export type CampaignListItem = {
  campaign_id: string;
  name: string;
  product: string;
  created_at: string;
  actor: string;
  finding_groups: number;
};

export type DeployPhase = {
  phase: "network" | "pull" | "nodes" | "readiness";
  state: "started" | "done" | "skipped" | "failed";
  ts: string;
  started_at: string | null;
  image?: string;
  total?: number;
  error?: string;
  reason?: string;
  status?: string;
};

export type Span = {
  id: number;
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  actor: string;
  actor_kind: string;
  stance: string | null;
  kind: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  status: "ok" | "error" | "denied" | "budget_refused";
  error_class: string | null;
  input_digest: string | null;
  output_digest: string | null;
  input_preview: string | null;
  output_preview: string | null;
  attrs: Record<string, unknown>;
  visibility: "agent" | "operator";
  trial_id?: string | null;
};
/** UX-24: where a report section's text came from. */
export type ReportOrigin = "operator" | "derived" | "missing";
export type ReportFact = {
  value: string | null;
  origin: ReportOrigin;
  source?: string;
};
export type ReportSection = {
  key: string;
  title: string;
  origin: ReportOrigin;
  source?: string;
  text?: string;
  items?: string[];
  code?: string;
  links?: { url: string; title?: string }[];
};
export type WriteupReference = { url: string; title?: string };
export type Writeup = Partial<{
  severity: Severity;
  cwe: string;
  summary: string;
  impact: string;
  description: string;
  remediation: string;
  vendor: string;
  product: string;
  affected_versions: string;
  fixed_versions: string;
  component: string;
  attack_type: string;
  impact_type: string;
  cvss_vector: string;
  discoverer: string;
  references: WriteupReference[];
}>;
export type FindingReport = {
  id: string;
  title: string;
  cwe: { id: string; name: string; url: string } | null;
  facts: Record<string, ReportFact>;
  sections: ReportSection[];
  verdict: {
    validator: string | null;
    operator: string | null;
    verified: boolean;
  };
  readiness: {
    ready: boolean;
    missing: string[];
    checks: {
      id: string;
      label: string;
      ok: boolean;
      blocking: boolean;
      message: string | null;
    }[];
  };
  writeup: Writeup;
  updated_by: string | null;
  updated_at: string | null;
  markdown: string;
  cve_request: string;
};
