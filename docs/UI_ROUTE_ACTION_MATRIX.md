# WebUI route and action inventory

Generated from `cyber-range/webui/app.py` by `scripts/inventory-webui-routes.py`.
This is the first pass of phase 0. It records every Flask route and HTTP
method; it does **not** prove React action/state parity. The status column
states the present migration boundary, not a completed replacement.

**Current inventory:** 133 route/method operations. Re-run the script after route changes.

| Current URL | Method | Handler | Workspace / destination | Auth | CSRF | Contract | Deep link | Migration status |
|---|---|---|---|---|---|---|---|---|
| `/favicon.ico` | GET | `favicon` | Public support → `current path` | Public | — | Flask page / form | Preserve current URL | Keep |
| `/login` | GET | `login` | Session → `/login` | Public | — | Flask page / form | Preserve current URL | Legacy until login parity |
| `/login` | POST | `login` | Session → `/login` | Public | Required | Flask page / form | Preserve current URL | Legacy until login parity |
| `/logout` | POST | `logout` | Session → `/logout` | Operator session | Required | Flask page / form | Preserve current URL | Legacy until login parity |
| `/` | GET | `overview` | Research / home → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy page retained |
| `/console` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/arena/<instance_id>` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/arenas/new` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/scenarios` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/scenarios/import` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/research/new` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/benchmark/registry` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/activity` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/library/targets` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/library/agents` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/settings` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/profile` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/evaluations/new` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/console/evaluations/<evaluation_id>` | GET | `royal_console` | New console → `/console` | Operator session | — | Flask page / form | New route | Implemented projection/shell |
| `/api/console/arenas` | POST | `console_arena_create` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/research/preview` | POST | `console_research_preview` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/research/launch` | POST | `console_research_launch` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/evaluations/<evaluation_id>` | GET | `console_evaluation` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/evaluations` | POST | `console_evaluation_create` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>` | GET | `console_arena` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/setup` | GET | `console_arena_setup` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/findings` | GET | `console_arena_findings` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/evidence` | GET | `console_arena_evidence` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/lifecycle` | POST | `console_arena_lifecycle` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/research-gate` | POST | `console_research_gate` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/research` | GET | `console_research` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/benchmark` | GET | `console_benchmark` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/benchmark/builds` | POST | `console_benchmark_build_create` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/benchmark/challenges` | POST | `console_benchmark_challenge_create` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/benchmark/suites` | POST | `console_benchmark_suite_create` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/activity` | GET | `console_activity` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/agents` | GET | `console_agents` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/settings` | GET | `console_settings` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/system-stop` | POST | `console_system_stop` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/range` | GET | `console_range` | New console → `/console` | Operator session | — | JSON / stream proxy | New route | Implemented projection/shell |
| `/arenas` | GET | `arenas` | Research / home → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy page retained |
| `/engagements` | GET | `engagements` | Research / arena → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/engagements/new` | GET | `new_engagement` | Research / arena → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/engagements/new` | POST | `new_engagement` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/launch` | GET | `launch` | Cyber Range → `/console?workspace=range` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/wizard` | GET | `wizard` | Research / arena → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/api/arenas/sut/preview` | POST | `sut_preview_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/targets/source-bundles` | POST | `source_bundle_upload_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/scenarios` | GET | `scenarios` | Cyber Range → `/console?workspace=range` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/library/challenges` | GET | `challenge_library` | Cyber Range → `/console?workspace=range` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/arena/<instance_id>` | GET | `arena_detail` | Research / arena → `/console?workspace=research` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/arena/<instance_id>/forwards` | POST | `arena_forward_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/arena/<instance_id>/forwards/<forward_id>/revoke` | POST | `arena_forward_revoke_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/arena/<instance_id>/stop` | POST | `arena_stop_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/arena/<instance_id>/resume` | POST | `arena_resume_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/agents` | GET | `agents` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/activity/agents` | GET | `agent_activity` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/audit` | GET | `audit` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/activity/audit` | GET | `audit_trail` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/settings` | GET | `settings` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/settings/emergency-stop` | POST | `system_stop_form` | Shared resources → `/console profile menu / legacy page` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/settings/emergency-stop/clear` | POST | `system_stop_clear_form` | Shared resources → `/console profile menu / legacy page` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/administration/settings` | GET | `administration_settings` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations` | GET | `evaluations` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations/builds` | POST | `evaluation_build_create` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations/challenges` | POST | `evaluation_challenge_create` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations/suites` | POST | `evaluation_suite_create` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations/new` | POST | `evaluation_create` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/evaluations/<evaluation_id>` | GET | `evaluation_detail` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/library/targets` | GET | `target_library` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/library/agents` | GET | `agent_library` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/activity/findings` | GET | `findings_index` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/activity/evidence` | GET | `evidence_index` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/administration/providers` | GET | `providers_capacity` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/administration/security` | GET | `security` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/profile` | GET | `profile` | Shared resources → `/console profile menu / legacy page` | Operator session | — | Flask page / form | Preserve current URL | Legacy action linked |
| `/api/system-usage` | GET | `system_usage` | Shared resources → `/console profile menu / legacy page` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/create` | POST | `create_lab` | Cyber Range → `/console?workspace=range` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/build-custom` | POST | `build_custom` | Cyber Range → `/console?workspace=range` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/build-sut` | POST | `build_sut` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/api/destroy/<instance_id>` | POST | `destroy_lab` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/destroy/<instance_id>` | POST | `destroy_lab_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/reset/<instance_id>` | POST | `reset_lab_form` | Research / arena → `/console?workspace=research` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/archive/delete/<instance_id>` | POST | `archive_delete` | Shared resources → `/console profile menu / legacy page` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/archive/clear` | POST | `archive_clear` | Shared resources → `/console profile menu / legacy page` | Operator session | Required | Flask page / form | Preserve current URL | Legacy action linked |
| `/api/health` | GET | `orchestrator_health` | Public support → `current path` | Public | — | JSON / stream proxy | Preserve current URL | Keep |
| `/api/current-agent` | GET | `current_agent` | Shared resources → `/console profile menu / legacy page` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/agents` | GET | `api_agents` | Shared resources → `/console profile menu / legacy page` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/model-connection` | GET | `model_connection_get` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/model-connection` | PUT | `model_connection_set` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/model-connection` | DELETE | `model_connection_delete` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/model-connection/verify` | POST | `model_connection_verify` | Benchmark / settings → `/console?workspace=benchmark` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/copilot` | POST | `copilot` | Shared resources → `/console profile menu / legacy page` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>` | GET | `setup_status_proxy` | Research / intake → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>/start` | POST | `setup_start_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>/step` | POST | `setup_step_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>/finish` | POST | `setup_finish_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>/proposals/<step_id>/<decision>` | POST | `setup_decision_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/setup/<instance_id>/generate-proposals` | POST | `setup_generate_proposals_proxy` | Research / intake → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/preview` | POST | `scenario_preview_proxy` | Cyber Range → `/console?workspace=range` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/generate` | POST | `scenario_generate_proxy` | Cyber Range → `/console?workspace=range` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/import` | POST | `scenario_import_proxy` | Cyber Range → `/console?workspace=range` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/import/vulhub` | POST | `scenario_import_vulhub_proxy` | Cyber Range → `/console?workspace=range` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/<scenario_id>/topology` | GET | `scenario_topology_proxy` | Cyber Range → `/console?workspace=range` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/events` | GET | `arena_events_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/stream` | GET | `arena_stream` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/eval-export` | GET | `arena_eval_export_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/workspaces` | GET | `arena_workspaces_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/console/arenas/<instance_id>/browser/visit` | POST | `console_browser_visit` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/files/upload` | POST | `console_file_upload` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/console/arenas/<instance_id>/files/download` | POST | `console_file_download` | New console → `/console` | Operator session | Required | JSON / stream proxy | New route | Implemented projection/shell |
| `/api/arenas/<instance_id>/http/transactions` | GET | `http_transactions_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/http/transactions/<digest>` | GET | `http_transaction_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/validation-evidence/<digest>` | GET | `validation_evidence_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/http/request` | POST | `http_request_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/http/transactions/<digest>/replay` | POST | `http_replay_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/poc-jobs` | GET | `poc_jobs_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/poc-jobs` | POST | `poc_jobs_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/poc-jobs/<job_id>` | GET | `poc_job_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/poc-jobs/<job_id>/cancel` | POST | `poc_job_cancel_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/preflight` | GET | `arena_preflight_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/workspaces/<workspace_node>/diff` | GET | `arena_workspace_diff_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/workspaces/<workspace_node>/patch-artifacts` | POST | `arena_workspace_patch_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/evidence-artifacts/<digest>` | GET | `evidence_artifact_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/bindings` | GET | `list_bindings_proxy` | Research / arena → `/console?workspace=research` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/bindings` | POST | `grant_binding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/bindings/<agent_name>` | DELETE | `revoke_binding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/findings/manual` | POST | `manual_finding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/findings/<finding_id>/verify` | POST | `verify_finding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/bindings/<agent_name>/pause` | POST | `pause_binding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/arenas/<instance_id>/bindings/<agent_name>/resume` | POST | `resume_binding_proxy` | Research / arena → `/console?workspace=research` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/scenarios/<scenario_id>` | DELETE | `scenario_delete_proxy` | Cyber Range → `/console?workspace=range` | Operator session | Required | JSON / stream proxy | Preserve current URL | Legacy action linked |
| `/api/poll/<instance_id>` | GET | `poll_status` | Shared resources → `/console profile menu / legacy page` | Operator session | — | JSON / stream proxy | Preserve current URL | Legacy action linked |

## State and contract review still required

For each row, inspect role/ownership checks, validation and denial states,
old page/JavaScript caller, new component and exact BFF request/response.
Record protected downloads, upload bounds, SSE resume and the old deep
link/fragment mapping. A legacy route retires only after its mutation and
read-only paths have browser tests at 1440, 1024, 390 and 320 px.

Current React coverage: authenticated Research, Benchmark and Cyber Range
indexes; Git, OCI and source-bundle intake; arena overview, setup, agent
bindings, HTTP, isolated browser visits, foothold transfer, PoC, findings,
evidence and infrastructure; comparison creation, build/challenge/suite
registration and evaluation results; scenario library, spec/Vulhub/model
preview and import, launch and arena lifecycle; shared Targets, Agents,
Activity, Settings and Profile views. These use narrow BFF projections and
keep `/console` opt-in. The operation rows remain an inventory, not proof
of old action/state parity. Exact old deep links, protected downloads,
full live journeys and accessibility review remain open.
