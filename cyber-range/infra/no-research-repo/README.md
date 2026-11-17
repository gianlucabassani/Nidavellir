# No research checkout provisioned

`docker-compose.yml` mounts this directory read-only at `/research/repo` when
`RESEARCH_REPO_HOST_DIR` is not set. It is deliberately not a Git repository, so the
research-code queries and source review answer "research repository is not
provisioned" until the operator points `RESEARCH_REPO_HOST_DIR` at a real checkout.
See `docs/OPERATIONS.md`, "Source review checkout".
