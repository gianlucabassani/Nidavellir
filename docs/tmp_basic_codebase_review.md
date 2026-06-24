# Codebase Audit: Redundancies & Inconsistencies

This audit documents code redundancies, logic inconsistencies, and documentation drift identified in the Nidavellir codebase.

---

## 1. High Severity Issues

### 1.1 `OpenStackProvider` Code Duplication
* **File:** [openstack.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/providers/openstack.py) vs [terraform_base.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/providers/terraform_base.py)
* **Description:** `OpenStackProvider` duplicates the complete subprocess execution, retry loops, error redacting, and output parsing logic of `TerraformDriver`. It inherits directly from `RangeProvider` instead of subclassing `TerraformDriver` as `AWSProvider` does.
* **Impact:** 
  * High maintenance overhead: any future improvements to OpenTofu timeouts, logging, retries, or environment cleanup must be duplicated in two places.
  * Over 100 lines of redundant subprocess management code.
* **Recommendation:** Refactor `OpenStackProvider` to inherit from `TerraformDriver`. Implement the required hooks (`_template_dir`, `_runs_dir`, `_write_vars`, and `_post_process_outputs`) and delete the redundant lifecycle methods.

### 1.2 Missing Compatibility Checks in `api.py` and `OpenStackProvider`
* **Files:** [api.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/api.py) & [openstack.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/providers/openstack.py)
* **Description:** 
  1. In `api.py`, `_check_provider_compatibility(scenario_id, provider_name)` immediately returns if `provider_name` is `None`. If a deploy request is sent without specifying a provider, it bypasses API-level compatibility checking and gets queued even if the default provider (e.g. `openstack` or `docker-local`) is incompatible with the scenario.
  2. Unlike `AWSProvider` and `DockerLocalProvider`, `OpenStackProvider` does not implement `_supports()` or perform any compatibility checks in its `deploy` method.
* **Impact:** Deploying an incompatible scenario (e.g., trying to deploy a container scenario or custom lab on an OpenStack provider) bypasses immediate API validation and fails asynchronously in the background Celery task during the OpenTofu step, confusing operators.
* **Recommendation:**
  * In `api.py`, resolve `None` to the default provider name using `default_provider_name()` before checking compatibility.
  * Implement the `_supports()` method in `OpenStackProvider` to verify that the scenario requires a `vm` or `any` class infrastructure, and call it at the start of `deploy()`.

---

## 2. Medium Severity Issues

### 2.1 `MockProvider` Flat Output Contract Inconsistency
* **Files:** [mock.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/providers/mock.py) vs [app.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/webui/app.py)
* **Description:** The orchestrator and dashboard expect node-specific outputs in a flat structure (e.g., `node_<name>_name`, `node_<name>_private_ip`, `node_<name>_ssh_command`) to populate the topology and nodes lists. However, `MockProvider` returns only the legacy VM-role-prefixed keys (`attack_vm_private_ip`, `victim_vm_private_ip`, etc.) and does not emit the `node_<name>_*` keys.
* **Impact:** When running in mock mode, `_parse_nodes()` in Flask cannot find any keys starting with `node_` and ending with `_name`. This results in the "Nodes" table in the WebUI Arena Detail dashboard displaying as completely empty.
* **Recommendation:** Update `MockProvider.deploy()` to return both legacy keys and the modern `node_<name>_*` keys (e.g. `node_kali_name: "kali"`, `node_kali_private_ip: "192.168.50.10"`, `node_kali_ssh_command: "ssh kali@192.168.1.80"`, `node_dvwa_name: "dvwa"`, `node_dvwa_private_ip: "192.168.0.10"`) to conform to the active output contract.

### 2.2 Finding Scoring Gap in Custom Arenas
* **File:** [api.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/api.py)
* **Description:** In `api.py` `report_finding()`, the scoring logic resolves the known-vulnerabilities manifest by calling `scenarios.scenario_manifest(record.get("scenario"))`. For custom arenas, the database record's `scenario` field holds a dynamic label like `custom:kali-cli+dvwa` rather than a registered scenario ID.
* **Impact:** `scenarios.scenario_manifest()` returns `None` for the custom label, meaning the scoring engine behaves as if there are no vulnerabilities to match. Attacker agents will receive a neutral acknowledgment, but their findings will never score or match a CWE.
* **Recommendation:** Decide on a strategy for custom/SUT arena vulnerability evaluation (e.g., allow operators to submit/inject a custom manifest upon launch, or document that scoring is disabled for dynamically assembled custom arenas).

---

## 3. Low Severity Issues & Documentation Drift

### 3.1 Outdated Docstrings in Agent Gateway
* **Files:** [stances.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/agent-gateway/gateway/stances.py) & [server.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/agent-gateway/gateway/server.py)
* **Description:** 
  * The docstring in `stances.py` claims that the per-stance execution toolsets (`run_command`, `observe_stream`, `query_events`, etc.) are "intentionally EMPTY in this skeleton".
  * The docstring in `server.py` states that "Per-stance execution toolsets... are added in a later increment; this skeleton exposes only the lifecycle surface."
* **Impact:** In reality, the execution toolsets for attacker and defender stances are fully implemented and registered in FastMCP. The docstrings are misleading for developers.
* **Recommendation:** Update the docstrings to accurately reflect that the execution tools are implemented and registered.

### 3.2 Registry Parsing Inefficiency in `scenarios.py`
* **File:** [scenarios.py](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/services/scenario-orchestrator/scenarios.py)
* **Description:** Calling `scenario_ids()` or `list_scenarios()` scans the `TEMPLATES_DIR/*.yaml` files, reads them, parses them using PyYAML, and performs Pydantic validation on the fly every single time.
* **Impact:**
  * On every deploy request, `scenarios.scenario_ids()` is called to validate the scenario name, triggering this I/O and CPU-bound process.
  * In the Agent Gateway's `get_briefing()`, it calls `list_scenarios()` just to get a description for a single scenario, meaning all YAML templates are parsed again.
* **Recommendation:** Implement a simple cache (e.g., using `functools.lru_cache` or a global module variable) for the scenario registry that only invalidates if the files in the templates directory are modified.

### 3.3 Redundant and Outdated Quickstart Instructions
* **File:** [README.md](file:///home/gianluca_b/Work/projects/Nidavellir/docs/README.md)
* **Description:** The quickstart guide is duplicated across "Docker Quick Start", "Quick Start (Simulation Mode)", and a third generic "Quick Start". The second section contains outdated paths like `cd services/scenario-orchestrator` instead of the correct path `cd cyber-range/services/scenario-orchestrator`.
* **Impact:** Clutters documentation and causes user confusion if they try to follow the outdated paths in the second quickstart section.
* **Recommendation:** Consolidate the documentation into one clean "Getting Started" section with tabs or distinct subsections for Docker vs Local/Mock mode, and ensure all paths are correct.

### 3.4 Missing Provider Selection in WebUI
* **File:** [launch.html](file:///home/gianluca_b/Work/projects/Nidavellir/cyber-range/webui/templates/launch.html)
* **Description:** The API supports selecting a specific provider during deployment, but the WebUI Predefined Scenario launch form does not present a provider dropdown. It defaults to the orchestrator's configured default provider.
* **Impact:** Operators cannot target a specific backend (e.g., selecting `aws` over `openstack`) for predefined scenarios via the WebUI.
* **Recommendation:** Add a dropdown menu for selecting the provider (populated from the `/providers` API) to the launch form, or confirm if this is an intentional UX design choice to keep launching simple.
