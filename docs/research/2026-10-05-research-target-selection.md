# Research target selection — 2026-10-05

Selecting the next open-source target for Nidavellir vulnerability research. This is a
writing-only deliverable: no platform code changed. All live metadata (repository stats,
advisory counts, releases, Docker tags, program pages) was retrieved on **2026-10-05**.
Advisory counts and version numbers below are date-stamped and will drift; re-verify before
pinning a fixture.

## 1. Constraints applied

Hard filters from the task, restated so the ranking is auditable:

- Nidavellir's supported intake is Docker-local: pinned Git/OCI/source bundle, official
  Docker image or compose, deterministic seed/reset, contained attacker foothold.
- Independent validators are strongest on **observable authorization effects and business
  logic** (existing calibration classes: cross-account object authorization, single-use
  grants). Memory-corruption-only targets are a poor fit.
- Legal research only: public projects, local self-hosted instances, no live third-party
  systems, no bounty credentials.
- Preference for self-hosted/internet-facing, actively maintained, source-available
  projects with an official Docker image/compose and synthetic data support.

## 2. Method and evidence basis

- **Repository and release metadata**: GitHub REST via `gh api` (`repos/{owner}/{repo}`,
  `/releases/latest`, `/security-advisories?state=published&per_page=100`), plus the
  Codeberg API for Forgejo (the GitHub mirror is gone; see uncertainty register).
- **Advisory history**: per-repo GitHub Security Advisories (GHSA) counts and recent
  entries, and NVD CVE keyword counts through the NVD 2.0 API
  (`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=<term>`). NVD keyword
  matches are directional, not exact: generic names over-count (documented in the
  uncertainty register).
- **Deployment, licensing and disclosure**: project docs/repo files verified by HTTP fetch
  on 2026-10-05; Docker Hub API for pull counts and image digests; HackerOne program pages
  probed by HTTP status only.
- Known limitation: the repository advisory-list endpoint caps at 100 items and ignores
  `page` (pages 1–3 return the same first GHSA), so `100` in the tables means "at least
  100", not exactly 100.

## 3. Long list (25 candidates)

Fit is a judgment against the constraints in section 1, from 1 (poor) to 5 (ideal). It is
grounded in the linked advisories, deploy artifacts and disclosure process, not a claim
that a vulnerability exists.

| Project | Stack | License | Latest release (date) | Active (last push) | Official Docker | Disclosure | GHSA (repo) | NVD keyword | Fit |
|---|---|---|---|---|---|---|---|---|---|
| [Gitea](https://github.com/go-gitea/gitea) | Go | MIT | [v28.0.0](https://github.com/go-gitea/gitea/releases/tag/v28.0.0) (2026-09-29) | 2026-10-05 | [docs](https://docs.gitea.com/installation/install-with-docker) | [SECURITY.md](https://github.com/go-gitea/gitea/blob/main/SECURITY.md) | 100+ | 97 | 3 |
| [Forgejo](https://codeberg.org/forgejo/forgejo) | Go | GPL-3.0 | [v16.0.5](https://codeberg.org/forgejo/forgejo/releases/tag/v16.0.5) (2026-09-17) | 2026-10-05 | [docs](https://forgejo.org/docs/latest/admin/installation-docker/) | repo on Codeberg (no SECURITY.md found) | n/a (Codeberg) | 11 | 3 |
| [Grafana](https://github.com/grafana/grafana) | Go/TS | AGPL-3.0 | [v13.2.3](https://github.com/grafana/grafana/releases/tag/v13.2.3) (2026-09-29) | 2026-10-05 | [docs](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/) | [security page](https://grafana.com/security/) | 28 | 158 | 2 |
| [Metabase](https://github.com/metabase/metabase) | Clojure | AGPL-3.0 + commercial | [v0.63.19](https://github.com/metabase/metabase/releases/tag/v0.63.19) (2026-10-01) | 2026-10-05 | [docs](https://www.metabase.com/docs/latest/installation-and-operation/running-metabase-on-docker) | [SECURITY.md](https://github.com/metabase/metabase/blob/master/SECURITY.md) | 44 | 33 | 3 |
| [Apache Superset](https://github.com/apache/superset) | Python | Apache-2.0 | [6.1.0](https://github.com/apache/superset/releases/tag/6.1.0) (2026-05-13) | 2026-10-05 | [compose docs](https://superset.apache.org/docs/installation/docker-compose) | [ASF security](https://www.apache.org/security/) | 0 (ASF process) | 70 | 2 |
| [Mattermost](https://github.com/mattermost/mattermost) | Go/TS | MIT-compiled / AGPL-source + commercial | [v11.11.1](https://github.com/mattermost/mattermost/releases/tag/v11.11.1) (2026-09-24) | 2026-10-05 | [docs](https://docs.mattermost.com/install/install-docker.html) | [HackerOne](https://hackerone.com/mattermost), [bulletins](https://mattermost.com/security-updates/) | 0 (own bulletins) | 655* | 2 |
| [Rocket.Chat](https://github.com/RocketChat/Rocket.Chat) | TS/Meteor | MIT core + ee dirs | [8.9.0](https://github.com/RocketChat/Rocket.Chat/releases/tag/8.9.0) (2026-10-05) | 2026-10-05 | [compose docs](https://docs.rocket.chat/docs/deploy-with-docker-docker-compose) | [HackerOne VDP](https://hackerone.com/rocket_chat), [SECURITY.md](https://github.com/RocketChat/Rocket.Chat/blob/develop/SECURITY.md) | 21 | 81 | 4 |
| [Zulip](https://github.com/zulip/zulip) | Python | Apache-2.0 | [12.3](https://github.com/zulip/zulip/releases/tag/12.3) (2026-09-21) | 2026-10-05 | [install docs](https://zulip.readthedocs.io/en/latest/production/install.html) | [SECURITY.md](https://github.com/zulip/zulip/blob/main/SECURITY.md) | 41 | 72 | 2 |
| [Nextcloud Server](https://github.com/nextcloud/server) | PHP | AGPL-3.0 | [v35.0.1](https://github.com/nextcloud/server/releases/tag/v35.0.1) (2026-09-24) | 2026-10-05 | [Docker Hub](https://hub.docker.com/_/nextcloud) | [HackerOne](https://hackerone.com/nextcloud) | 0 (own advisories) | 239* | 2 |
| [Outline](https://github.com/outline/outline) | TS/Node | BSL 1.1 (source-available) | [v1.10.1](https://github.com/outline/outline/releases/tag/v1.10.1) (2026-09-09) | 2026-10-05 | [compose](https://github.com/outline/outline/blob/main/docker-compose.yml), [docs](https://docs.getoutline.com/s/hosting/doc/docker-7pfeLP5a8t) | [SECURITY.md](https://github.com/outline/outline/blob/main/docs/SECURITY.md) | 26 | 68* | 4 |
| [Directus](https://github.com/directus/directus) | TS/Node | MSCL-1.0-GPL (source-available) | [v12.4.1](https://github.com/directus/directus/releases/tag/v12.4.1) (2026-09-23) | 2026-10-05 | [docker guide](https://docs.directus.io/self-hosted/docker-guide.html) | [advisories](https://github.com/directus/directus/security/advisories) | 78 | 75 | 4 |
| [Strapi](https://github.com/strapi/strapi) | TS/Node | mixed (Strapi license) | [v5.56.0](https://github.com/strapi/strapi/releases/tag/v5.56.0) (2026-09-30) | 2026-10-05 | [docs](https://docs.strapi.io/cms/installation/docker) | [security page](https://strapi.io/security), [HackerOne](https://hackerone.com/strapi) | 21 | 44 | 3 |
| [Appwrite](https://github.com/appwrite/appwrite) | PHP | BSD-3-Clause | [2.3.0](https://github.com/appwrite/appwrite/releases/tag/2.3.0) (2026-09-23) | 2026-10-05 | [self-host docs](https://appwrite.io/docs/advanced/self-hosting) | [SECURITY.md](https://github.com/appwrite/appwrite/blob/main/SECURITY.md) | 0 | 9 | 3 |
| [Keycloak](https://github.com/keycloak/keycloak) | Java | Apache-2.0 | [26.8.0](https://github.com/keycloak/keycloak/releases/tag/26.8.0) (2026-10-01) | 2026-10-05 | [docs](https://www.keycloak.org/getting-started/getting-started-docker) | [security page](https://www.keycloak.org/security) | 83 | 327 | 2 |
| [Authentik](https://github.com/goauthentik/authentik) | Python/Go | MIT + enterprise dirs | [2026.8.3](https://github.com/goauthentik/authentik/releases/tag/version/2026.8.3) (2026-09-17) | 2026-10-05 | [compose docs](https://docs.goauthentik.io/install-config/install/docker-compose/) | [SECURITY.md](https://github.com/goauthentik/authentik/blob/main/SECURITY.md) | 47 | 49 | 3 |
| [Vaultwarden](https://github.com/dani-garcia/vaultwarden) | Rust | AGPL-3.0 | [1.37.3](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.3) (2026-09-13) | 2026-10-05 | [official image](https://hub.docker.com/r/vaultwarden/server), [compose wiki](https://github.com/dani-garcia/vaultwarden/wiki/Using-Docker-Compose) | [SECURITY.md](https://github.com/dani-garcia/vaultwarden/blob/main/SECURITY.md), [advisories](https://github.com/dani-garcia/vaultwarden/security/advisories) | 30 | 25 | 5 |
| [MinIO](https://github.com/minio/minio) | Go | AGPL-3.0 | [RELEASE.2025-10-15](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z) (2025-10-16) | 2026-04-24 | [container docs](https://min.io/docs/minio/container/index.html) | [SECURITY.md](https://github.com/minio/minio/blob/master/SECURITY.md) | 27 | 136 | 2 |
| [Harbor](https://github.com/goharbor/harbor) | Go | Apache-2.0 | [v2.15.2](https://github.com/goharbor/harbor/releases/tag/v2.15.2) (2026-07-02) | 2026-10-05 | [install docs](https://goharbor.io/docs/2.15.0/install-config/) | [SECURITY.md](https://github.com/goharbor/harbor/blob/main/SECURITY.md) | 28 | 32 | 3 |
| [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | Python/Django | GPL-3.0 | [v3.2.1](https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.2.1) (2026-09-20) | 2026-10-05 | [compose](https://github.com/paperless-ngx/paperless-ngx/blob/main/docker/compose/docker-compose.postgres.yml) | [SECURITY.md](https://github.com/paperless-ngx/paperless-ngx/blob/main/SECURITY.md), [advisories](https://github.com/paperless-ngx/paperless-ngx/security/advisories) | 16 | 2 | 5 |
| [Immich](https://github.com/immich-app/immich) | TS/Node | AGPL-3.0 | [v3.2.4](https://github.com/immich-app/immich/releases/tag/v3.2.4) (2026-09-28) | 2026-10-05 | [compose](https://github.com/immich-app/immich/blob/main/docker/docker-compose.yml), [docs](https://immich.app/docs/install/docker-compose) | [security.txt](https://immich.app/.well-known/security.txt), [policy](https://github.com/immich-app/.github/blob/main/SECURITY.md) | 13 | 10 | 4 |
| [Plane](https://github.com/makeplane/plane) | TS/Node | AGPL-3.0 | [v1.4.2](https://github.com/makeplane/plane/releases/tag/v1.4.2) (2026-08-23) | 2026-10-05 | [README](https://github.com/makeplane/plane) | [SECURITY.md](https://github.com/makeplane/plane/blob/master/SECURITY.md) | 84 | 0* | 3 |
| [OpenProject](https://github.com/opf/openproject) | Ruby/Rails | GPL-3.0 | [v17.9.1](https://github.com/opf/openproject/releases/tag/v17.9.1) (2026-10-01) | 2026-10-05 | [compose](https://github.com/opf/openproject/blob/dev/docker-compose.yml), [docs](https://www.openproject.org/docs/installation-and-operations/installation/docker/) | [security statement](https://www.openproject.org/docs/security-and-privacy/statement-on-security/) | 91 | 58 | 4 |
| [ERPNext](https://github.com/frappe/erpnext) | Python/Frappe | GPL-3.0 | [v15.121.6](https://github.com/frappe/erpnext/releases/tag/v15.121.6) (2026-09-30) | 2026-10-05 | [frappe_docker](https://github.com/frappe/frappe_docker) | [SECURITY.md](https://github.com/frappe/erpnext/blob/develop/SECURITY.md) | 89 | 69 | 4 |
| [n8n](https://github.com/n8n-io/n8n) | TS/Node | Sustainable Use (source-available) | [n8n@2.41.7](https://github.com/n8n-io/n8n/releases/tag/n8n%402.41.7) (2026-10-05) | 2026-10-05 | [docs](https://docs.n8n.io/hosting/installation/docker/) | [SECURITY.md](https://github.com/n8n-io/n8n/blob/master/SECURITY.md) | 100+ | 216 | 3 |
| [Apache Airflow](https://github.com/apache/airflow) | Python | Apache-2.0 | [3.3.2](https://github.com/apache/airflow/releases/tag/3.3.2) (2026-09-17) | 2026-10-05 | [compose howto](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html) | [security docs](https://airflow.apache.org/docs/apache-airflow/stable/security/) | 0 (ASF process) | 185 | 2 |

`*` marks NVD keyword counts that match generic terms and therefore over-count (see the
uncertainty register). "0 (own process)" means the project publishes advisories outside
GitHub (project bulletins or ASF/NVD process), not that it has no vulnerabilities.

Also screened and rejected for the shortlist: [Odoo](https://github.com/odoo/odoo)
([HackerOne](https://hackerone.com/odoo), 59 NVD, heavy ERP), Dify (modified Apache,
35 NVD, rapid churn), Flowise (100+ GHSA, source-available),
[Langflow](https://github.com/langflow-ai/langflow) (MIT,
[37 GHSA](https://github.com/langflow-ai/langflow/security/advisories) including an
explicit IDOR/BOLA stream, but RCE-heavy and fast-moving),
[Open WebUI](https://github.com/open-webui/open-webui) (100+ GHSA, custom license, churn),
LibreChat (MIT, 29 GHSA), [Jenkins](https://www.jenkins.io/security/) (1,933 NVD keyword
hits, plugin sprawl), Argo CD (Apache-2.0, 52 GHSA, GitOps deployment adds moving parts).

## 4. Ranked shortlist

| Rank | Project | Deploy effort | Maintenance | Disclosure | 2026 advisory velocity | Grant/authz fit | Reset/seed determinism | Saturation and public writeups |
|---|---|---|---|---|---|---|---|---|
| 1 | Vaultwarden | Single official container, SQLite volume | Monthly releases, daily pushes | GitHub advisories + SECURITY.md | 26 of 30 GHSAs in 2026 | 5/5: single-use Sends + org/collection ACLs | High: one bind-mounted data dir, scripted seed | Moderate: public PoCs for several classes; adjacent ACL/import logic still yielding Oct 2026 findings |
| 2 | Paperless-ngx | 3-container official compose (webserver/DB/broker) | Frequent releases, daily pushes | GitHub advisories + SECURITY.md | 10 of 16 GHSAs in 2026 | 4/5: strong object permissions and share links; no native single-use grant | High: Django REST API seeding | Low-moderate: several public disclosures, few third-party writeups |
| 3 | Immich | 3–4 container official compose | Monthly breaking releases | security.txt + GitHub policy | 12 of 13 GHSAs in 2026 | 4/5: album/partner sharing, API-key scopes | High with API/CLI seed | Moderate; huge user base means fast duplication |
| 4 | OpenProject | Official compose, Rails + Postgres | Frequent releases | Security statement; security@ | 91 GHSAs total, 2026 authz stream | 4/5: role/permission matrix, work packages | Medium: admin API plus Rails console | Moderate-high: 91 GHSAs, but business-logic surface is deep |
| 5 | Rocket.Chat | Official compose, Meteor + MongoDB | Very active | HackerOne VDP (no monetary reward) | 21 GHSAs total | 4/5: channels/teams/roles, invite logic | Medium: admin APIs, MongoDB seed | Moderate: recent BAC and OAuth findings |

### 4.1 Vaultwarden

Vaultwarden is an unofficial, Bitwarden-compatible server in Rust, AGPL-3.0, with 68,550
GitHub stars and a release cadence of roughly monthly patch releases
([repo](https://github.com/dani-garcia/vaultwarden), [1.37.3](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.3)).
The official image is `vaultwarden/server` on Docker Hub with 339,983,198 pulls as of
2026-10-05; the stable `1.37.3` tag was pushed 2026-09-13 and the `testing` tag 2026-10-05
([Docker Hub](https://hub.docker.com/r/vaultwarden/server)).

Its object model maps almost one-to-one onto Nidavellir's existing calibration classes:

- **Single-use grants.** Bitwarden Sends can carry a maximum access count; the server
  source models `max_access_count` and `expiration_date` on Sends
  ([`src/api/core/sends.rs`](https://github.com/dani-garcia/vaultwarden/blob/main/src/api/core/sends.rs)).
  GHSA-wc45-m6pv-rrf9 (2026-10-03) documents a Send access-limit bypass on the rewritten
  anonymous Send endpoints: the affected code was pre-release only between two commits and
  fixed in 1.37.0, but it proves the class and gives a ready-made calibration fixture
  ([GHSA](https://github.com/dani-garcia/vaultwarden/security/advisories/GHSA-wc45-m6pv-rrf9)).
- **Cross-account object authorization.** Organizations, collections, ciphers and
  attachments have server-side ACLs. Recent advisories include CVE-2026-26012 /
  GHSA-h265-g7rm-h337 (any org member could enumerate all org ciphers regardless of
  collection permissions; fixed in 1.35.3), GHSA-xwf8-pjh7-h589 (cross-organization cipher
  access via a full-access-group query; fixed in 1.37.0), and the 2026-10-03 import batch
  GHSA-f3qw-qg77-hmm4 (IDOR in organization import) and GHSA-jq2g-h4xr-4mcr (cipher
  ownership confusion) ([advisories](https://github.com/dani-garcia/vaultwarden/security/advisories)).

The 2026 advisory record is active but not exhausted: 26 of 30 published GHSAs are from
2026, split 19 medium / 11 high. There are public writeups and PoCs (the collection bypass
PoC, the SSO `email_verified` binding writeup, and a 2026-10-02 third-party writeup on
`X-Real-IP` rate-limit keying in 1.37.3), which is both a saturation signal and a source of
calibration material; that third-party issue is not a project advisory and was not
reproduced here ([Tom Ryan](https://tomryan.dev/writing/vaultwarden-sso-email-verified/),
[Abraxas Labs](https://abraxaslabs.tech/research/vaultwarden-ip-header-spoof)). The
disclosure path is GitHub private advisories plus the SECURITY.md channels; there is no
monetary bug bounty
([SECURITY.md](https://github.com/dani-garcia/vaultwarden/blob/main/SECURITY.md)).

### 4.2 Paperless-ngx (runner-up)

Paperless-ngx is a GPL-3.0 Django/Angular document management system with per-object
`owner`/`view`/`edit` permissions and expiring public share links, seeded easily through
its REST API ([usage docs](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/usage.md)).
The 2026 advisory stream is almost entirely authorization logic: IDOR in `GlobalSearchView`
over mail accounts/rules, IDOR plus Jinja2 sandbox escape in `storage_paths/test`, share
link creation without document-level authorization, superuser creation via `UserViewSet`,
owner reassignment through the update API, and read-only users uploading documents
([advisories](https://github.com/paperless-ngx/paperless-ngx/security/advisories)).
There are only 16 published GHSAs in total (10 in 2026), so the permission system looks
under-audited relative to its feature set. Two caveats: share links expire but are not
single-use, so the "single-use grant" class must come from elsewhere (e.g. one-shot
workflow or invitation semantics), and the project's security page explicitly excludes some
IDOR claims (for example attaching an object the caller cannot view to a document is
declared intentional), so scope must be checked before reporting
([security policy](https://github.com/paperless-ngx/paperless-ngx/security/policy)).

### 4.3 Immich

Immich (AGPL-3.0, 115,630 stars) has 13 published GHSAs, 12 in 2026, and simple official
Docker deployment ([compose](https://github.com/immich-app/immich/blob/main/docker/docker-compose.yml),
[security.txt](https://immich.app/.well-known/security.txt)). Its sharing model (albums,
shared links with passwords/expiry, partner sharing) and API-key permissions produced a
high-severity API-key privilege-escalation advisory in 2026 (CVE-2026-23896 /
GHSA-237r-x578-h5mv) and a shared-link password-transmission advisory (CVE-2026-25118 /
GHSA-78x4-6x83-jx75). Recent 2026 advisories skew toward XSS/open-redirect/SVG-RCE rather
than object authorization, and the user base is large enough that classes are duplicated
quickly. Strong fallback if Vaultwarden stalls.

### 4.4 OpenProject

OpenProject (GPL-3.0, Rails) offers a full role/permission matrix over projects and work
packages and is deployable with the repo's compose file. It has 91 published GHSAs,
including a steady 2026 stream of improper-access-control findings: private work-package
subjects leaking through shared representer caches and time/cost APIs, direct-upload policy
reuse, and `fileLinks` access control on work-package PATCH
([advisories](https://github.com/opf/openproject/security/advisories)). It is heavier to
seed and more heavily scrutinized than Paperless, but the business-logic depth (memberships,
meetings, direct uploads) is a good fit for patient logic research.

### 4.5 Rocket.Chat

Rocket.Chat (MIT core plus enterprise directories) runs a HackerOne VDP with no monetary
rewards and accepts email reports
([SECURITY.md](https://github.com/RocketChat/Rocket.Chat/blob/develop/SECURITY.md)). It has
21 published GHSAs, including 2026 access-control findings such as unauthorized conversion
of public channels to teams and critical Apple OAuth account-takeover paths
([advisories](https://github.com/RocketChat/Rocket.Chat/security/advisories)). The Meteor
and MongoDB stack makes deterministic seeding more work than Paperless or Vaultwarden, and
recent high-impact classes are being found quickly.

## 5. Recommendation

**Top pick: Vaultwarden. Runner-up: Paperless-ngx.**

The three strongest reasons for Vaultwarden:

1. **It exercises both existing calibration classes server-side.** Single-use Sends map to
   the single-use-grant validator, and organization/collection ACLs map to cross-account
   object authorization. Both effects are observable in plain JSON API responses without
   any client-side crypto, and both classes have recent, publicly documented instances
   (GHSA-wc45-m6pv-rrf9; CVE-2026-26012; GHSA-xwf8-pjh7-h589; 2026-10-03 import batch).
2. **It is the most reproducible target on the list.** One official container with a
   bind-mounted `/data` directory and SQLite by default, no external database or queue. A
   pinned tag and digest were recorded on 2026-10-05, the compose template is published in
   the project wiki, and reset is deleting one directory and re-running a seed script
   ([wiki compose](https://github.com/dani-garcia/vaultwarden/wiki/Using-Docker-Compose),
   [tags](https://hub.docker.com/r/vaultwarden/server/tags)).
3. **It is active but not saturated.** 30 published GHSAs with 26 in 2026 means the code is
   getting real audit attention, yet the October 2026 batch shows authorization logic still
   producing fresh findings; known classes have public PoCs we can use as calibration and
   deliberately avoid.

### Why not the obvious popular choices

- **Gitea/Forgejo**: 100+ published GHSAs for Gitea (97 NVD keyword matches) and a steady
  2026 permission-bypass stream (restricted users reading limited-visibility data, Actions
  approval-gate bypass). The classes are saturated and the forks share the same surface.
- **Grafana, Metabase, Superset**: heavily researched BI targets. Metabase's 2026 stream is
  dominated by critical SQLi/embedded-analytics issues, Grafana has 158 NVD keyword matches
  and a huge plugin surface, and Superset uses the ASF process with no project bounty.
- **Mattermost, Nextcloud, Keycloak**: large, long-audited codebases with bounty programs
  (655, 239 and 327 NVD keyword matches respectively). Keycloak is an authentication server;
  most classes are protocol/session/crypto rather than object-level business logic, which
  weakens validator fit.
- **n8n, Open WebUI, Flowise**: 100+ GHSAs each, high churn, and licenses that are not OSI
  open source (Sustainable Use License, custom Open WebUI license); most public classes are
  SSRF/credential-exposure/RCE rather than clean authorization effects.
- **Outline, Directus**: excellent authorization surfaces (Outline recently had API-key
  scope bypass and MCP document-leak advisories; Directus has 78 GHSAs), but both are
  source-available under non-OSI licenses (BSL 1.1, MSCL-1.0-GPL) and Outline needs an
  OIDC/SMTP path to create seed users. They remain the best watchlist additions.
- **MinIO**: latest official release is 2025-10-16 despite repository pushes into
  April 2026; maintenance signal is weaker than the rest of the list.
- **Jenkins**: 1,933 NVD keyword matches, plugin sprawl, and no single canonical compose,
  which hurts deterministic reproduction.

## 6. Vaultwarden onboarding plan for Nidavellir

### 6.1 Pin and deploy

- Image: `vaultwarden/server:1.37.3` with digest recorded from Docker Hub tags on
  2026-10-05: `sha256:1587c45feaa479f1f5e8af3b00eded36bff77bcf1880cf8dbf0541706dd470e0`
  (re-resolve the multi-arch digest at pin time;
  [tags](https://hub.docker.com/r/vaultwarden/server/tags)).
- Compose (lab-only values, ADMIN_TOKEN generated per arena and never committed):

```yaml
services:
  vaultwarden:
    image: vaultwarden/server:1.37.3@sha256:1587c45feaa479f1f5e8af3b00eded36bff77bcf1880cf8dbf0541706dd470e0
    environment:
      DOMAIN: "http://localhost:8080"
      SIGNUPS_ALLOWED: "true"      # seeding only; flip after seed if desired
      INVITATIONS_ALLOWED: "true"
      SENDS_ALLOWED: "true"
      ORG_CREATION_USERS: "all"
      ADMIN_TOKEN: "${VAULTWARDEN_ADMIN_TOKEN}"
    volumes:
      - ./vw-data:/data
    ports:
      - "8080:80"
```

- Reset: stop the container, delete `vw-data`, redeploy the pinned fixture, re-run the seed
  script, and snapshot `vw-data` for a deterministic starting digest. There is no external
  state (no Postgres/Redis) in the default configuration, so reset is a directory delete.
- Seeding path: Bitwarden clients are GPL-3.0/Bitwarden License
  ([clients license](https://github.com/bitwarden/clients/blob/main/LICENSE.txt)); pin a CLI
  version and point it at the arena (`bw config server http://localhost:8080`). For pure
  authorization tests, ciphers can also be created through the API with placeholder
  ciphertext, because the server performs ACL checks on stored objects rather than
  validating decryptability for this purpose.

### 6.2 Seed state (deterministic fixture)

1. Accounts: owner `owner@lab.invalid` (A) and member `member@lab.invalid` (B), created via
   client/API while `SIGNUPS_ALLOWED=true`.
2. Organization `nidavellir-lab` owned by A; collections `shared` (A and B) and `restricted`
   (A only).
3. Ciphers: at least one item in each collection (for example `secret-restricted-1` in
   `restricted`), plus one attachment on a restricted cipher.
4. B is an org user with `accessAll=false`, assigned only to `shared`; verify B's
   `GET /api/collections` excludes `restricted`.
5. Sends as A: `send-single-use` with `max_access_count=1`, and a control
   `send-two-use` with `max_access_count=2`, both with a future deletion date.
6. Snapshot the `vw-data` directory and record the starting-state digest.

### 6.3 First hypotheses

| ID | Class | Hypothesis | Control |
|---|---|---|---|
| H1 | Single-use grant | A `max_access_count=1` Send can be retrieved more than once through a race, a retry after a failed access-count write, or an adjacent access path (legacy/auth'd endpoint, attachment download, file Send v2) | The same probe against `send-two-use` and against a single-use Send after expiry must behave consistently |
| H2 | Cross-account object authorization | Member B can read a cipher (or attachment) in `restricted` through a direct-ID or alternate-sync path that skips collection filtering | B reading `shared` succeeds; B reading `restricted` through the documented paths is denied; A reading `restricted` succeeds |
| H3 | Ownership business logic | Organization import or collection/bulk-move handling lets a member with import/manage permissions cause cipher ownership/org confusion (object lands under a different owner or organization than the request scopes) | The same operation without the mismatched `organizationId`/ownership field stores the object correctly |

Calibration runs first on deliberately old fixtures (for H2, 1.35.2 is affected by
CVE-2026-26012; for H1, GHSA-wc45-m6pv-rrf9 only ever affected the pre-release `testing`
image between two commits, because its range `>1.36.0, <1.37.0` was never published as a
tag), then on pinned 1.37.3 for novel variants. This proves the harness before claiming new
findings.

### 6.4 Evidence the independent validator needs

- Two authenticated sessions with distinct Bearer tokens (A owner, B restricted) plus one
  anonymous session for Sends; raw request/response pairs with status codes and body
  hashes, object IDs, and the access-count/state after the probe.
- A control object or principal that must yield the opposite outcome, so the validator can
  distinguish a real authorization bypass from a misconfigured fixture.
- The starting-state digest of the seeded `vw-data` snapshot and the exported evidence
  before teardown (Nidavellir's target-local `authorization_effect` validator already
  proves `unauthorized_read` from HTTP effects; a grant-limit assertion is the only
  addition H1 needs).
- Replay against a freshly reset arena to show the effect is reproducible, not state drift.

### 6.5 Disclosure path

GitHub private vulnerability reporting on
[dani-garcia/vaultwarden](https://github.com/dani-garcia/vaultwarden/security/advisories)
(SECURITY.md also lists Matrix and a GPG key). No monetary bounty. Respect the stated
exclusions: no DoS, no client-side issues, no already-reported issues, and avoid duplicating
the public `X-Real-IP` writeup. Coordinate timing with the operator before any external
submission.

## 7. Uncertainty register

- **GHSA counts are lower bounds at 100.** The repository advisory endpoint ignores
  pagination (pages 1–3 return the same first GHSA), so Gitea, n8n, Flowise and Open WebUI
  show "100+" rather than exact totals. Counts are as of 2026-10-05.
- **NVD keyword counts are directional.** Generic names over-count: "Outline" returns 68
  matches dominated by unrelated products, "Plane" with a specific keyword returns 0, and
  Mattermost/Jenkins/Nextcloud/Keycloak match broad terms. Treat these as signals only; the
  per-repo GHSA data is the more precise number where the project uses GitHub advisories.
- **Disclosure-program verification is shallow.** HackerOne program pages for Mattermost,
  Nextcloud, Rocket.Chat, Odoo, Strapi and Harbor returned HTTP 200 on 2026-10-05; Grafana,
  Metabase, Directus, Appwrite, Gitea, OpenProject and Langflow returned 404, which may mean
  unlisted or moved programs. Reward ranges and scope were not verified.
- **Vaultwarden image digest** was read from the Docker Hub tags API for the `1.37.3` tag;
  multi-arch resolution should be repeated when the fixture is pinned.
- **The Abraxas Labs `X-Real-IP` issue (2026-10-02)** is third-party research claimed
  against 1.37.3, not a project advisory; it was not reproduced here and could duplicate a
  known report.
- **Immich's security.txt** lists `Expires: 2026-05-01`, already in the past at the time of
  writing; the GitHub-hosted policy is the durable reference.
- **Forgejo** development moved to Codeberg (the `forgejo/forgejo` GitHub mirror returns
  404); repository stats and advisory counts are not directly comparable to GitHub-hosted
  projects, and no SECURITY.md was found at the repo root.
- **License labels for mixed-license projects** (Strapi, Metabase, Mattermost, Directus,
  n8n, Open WebUI) were read from license files where present; Directus uses the
  Monospace Sustainable Core License (MSCL-1.0-GPL). These are source-available, not OSI
  open source, and any distribution or fixture publication must respect those terms.
- **Paperless-ngx docs pages** returned 403 to non-browser clients; the cited claims come
  from the repository's raw Markdown and compose files.

## 8. Primary sources

- Repository metadata, releases, advisories: GitHub REST API via `gh api` on 2026-10-05
  (per-project links in section 3).
- NVD CVE search API: `https://services.nvd.nist.gov/rest/json/cves/2.0` (keyword and CVE
  queries on 2026-10-05).
- Vaultwarden image tags and digests: `https://hub.docker.com/v2/repositories/vaultwarden/server/tags`.
- Docker Hub pull counts: `https://hub.docker.com/v2/repositories/vaultwarden/server/`,
  `https://hub.docker.com/v2/repositories/paperlessngx/paperless-ngx/`,
  `https://hub.docker.com/v2/repositories/gitea/gitea/`,
  `https://hub.docker.com/v2/repositories/rocketchat/rocket.chat/`,
  `https://hub.docker.com/v2/repositories/outlinewiki/outline/`.
- Nidavellir calibration context: `docs/JOURNAL.md` (NV-06 cross-account read and the
  `authorization_effect` validator) and `docs/verification/` manifests.
