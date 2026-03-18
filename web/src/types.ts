/** TypeScript types mirroring Python dataclasses. */

export interface RunLog {
  run_id: string;
  prompt: string;
  status: "running" | "completed" | "failed";
  phases: PhaseEntry[];
  total_cost_usd: number;
  started_at: string;
  finished_at: string | null;
  branch_name: string | null;
  prd_rel: string | null;
  task_rel: string | null;
  source_issue: number | null;
  source_issue_url: string | null;
}

export interface PhaseEntry {
  phase: string;
  success: boolean;
  cost_usd: number | null;
  duration_ms: number;
  session_id: string;
  model: string | null;
  error: string | null;
  artifacts: Record<string, string>;
}

export interface RunHeader {
  run_id: string;
  status: string;
  branch_name: string | null;
  total_cost_usd: number;
  started_at: string;
  finished_at: string | null;
  wall_clock_ms: number;
  prompt: string;
  prompt_truncated: string;
  source_issue_url: string | null;
  last_successful_phase: string | null;
  prd_rel: string | null;
  task_rel: string | null;
}

export interface PhaseTimelineEntry {
  phase: string;
  model: string | null;
  duration_ms: number;
  cost_usd: number | null;
  success: boolean;
  is_collapsed: boolean;
  collapsed_count: number;
  round_number: number | null;
  session_id: string;
  error: string | null;
  is_skipped: boolean;
}

export interface ReviewSummary {
  review_rounds: number;
  fix_iterations: number;
  per_round_review_counts: number[];
}

export interface ShowResult {
  header: RunHeader;
  timeline: PhaseTimelineEntry[];
  review_summary: ReviewSummary | null;
  has_decision: boolean;
  decision_success: boolean;
  has_ci_fix: boolean;
  ci_fix_attempts: number;
  ci_fix_final_success: boolean;
  phase_filter: string | null;
  phase_detail: PhaseTimelineEntry[];
}

export interface RunSummary {
  total_runs: number;
  completed: number;
  failed: number;
  in_progress: number;
  success_rate: number;
  failure_rate: number;
  total_cost_usd: number;
}

export interface PhaseCostRow {
  phase: string;
  total_cost: number;
  avg_cost: number;
  pct_of_total: number;
}

export interface PhaseFailureRow {
  phase: string;
  executions: number;
  failures: number;
  failure_rate: number;
}

export interface ReviewLoopStats {
  avg_review_rounds: number;
  first_pass_approval_rate: number;
  total_review_rounds: number;
  total_fix_iterations: number;
}

export interface DurationRow {
  label: string;
  avg_duration_ms: number;
}

export interface RecentRunEntry {
  run_id: string;
  status: string;
  cost_usd: number;
}

export interface ModelUsageRow {
  model: string;
  invocations: number;
  total_cost: number;
  avg_cost: number;
}

export interface StatsResult {
  summary: RunSummary;
  cost_breakdown: PhaseCostRow[];
  failure_hotspots: PhaseFailureRow[];
  review_loop: ReviewLoopStats;
  duration_stats: DurationRow[];
  recent_trend: RecentRunEntry[];
  phase_detail: unknown[];
  phase_filter: string | null;
  model_usage: ModelUsageRow[];
}

export interface Persona {
  role: string;
  expertise: string;
  perspective: string;
  reviewer: boolean;
}

export interface ProjectInfo {
  name: string;
  description: string;
  stack: string;
}

export interface ConfigResult {
  model: string;
  phase_models: Record<string, string>;
  budget: {
    per_phase: number;
    per_run: number;
    max_duration_hours: number;
    max_total_usd: number;
  };
  phases: {
    plan: boolean;
    implement: boolean;
    review: boolean;
    deliver: boolean;
  };
  branch_prefix: string;
  prds_dir: string;
  tasks_dir: string;
  reviews_dir: string;
  proposals_dir: string;
  max_fix_iterations: number;
  auto_approve: boolean;
  learnings: { enabled: boolean; max_entries: number };
  ci_fix: {
    enabled: boolean;
    max_retries: number;
    wait_timeout: number;
    log_char_cap: number;
  };
  vision: string;
  project: ProjectInfo | null;
  personas: Persona[];
}

export interface QueueItem {
  id: string;
  source_type: string;
  source_value: string;
  status: string;
  added_at: string;
  run_id: string | null;
  cost_usd: number;
  duration_ms: number;
  pr_url: string | null;
  error: string | null;
  issue_title: string | null;
}

export interface QueueState {
  queue_id: string;
  items: QueueItem[];
  aggregate_cost_usd: number;
  start_time_iso: string | null;
  status: string;
}

export interface ArtifactResult {
  path: string;
  content: string;
  filename: string;
}

export interface ProposalEntry {
  filename: string;
  path: string;
  modified_at: string;
}

export interface ReviewEntry {
  filename: string;
  path: string;
  subdirectory: string;
  modified_at: string;
}
