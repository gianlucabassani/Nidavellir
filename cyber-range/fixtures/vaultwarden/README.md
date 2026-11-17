# Vaultwarden fixture

Pinned, pre-seeded Vaultwarden images for Docker-local calibration. The first
use is CVE-2026-26012 (`GHSA-h265-g7rm-h337`): a regular organization member
could enumerate every organization cipher through
`GET /api/ciphers/organization-details`, ignoring collection permissions
(fixed in 1.35.3).

`build_fixture.py`:

1. pulls the pinned upstream image by digest (`1.35.2` and `1.37.3` in `PINS`);
2. starts it on loopback with a throwaway data directory;
3. registers two synthetic accounts (`owner@lab.invalid`, `member@lab.invalid`)
   and creates the `nidavellir-lab` organization through the product's own API;
4. stops the container and applies one bounded SQLite seed: adds the member to
   the organization with `access_all=false`, creates a second `restricted`
   collection the member cannot access, links the member to the default
   `shared` collection, and inserts one cipher in each collection with fixed
   UUIDs;
5. restarts, mints the two access tokens used by the validator plan, stops, and
   builds a derived image (`FROM <pinned digest>` + `COPY data /data`) whose
   local image ID the scenario pins.

Notes:

- The upstream image declares `VOLUME /data`, so the seeded directory is copied
  into the container's anonymous volume at creation. The derived image sets
  `I_REALLY_WANT_VOLATILE_STORAGE=true`; an arena is replaced wholesale, so
  volatile storage is intentional.
- `scripts/verify-vaultwarden-live.py` runs the fixture on an isolated
  Nidavellir stack and asserts the platform's `http_access_control` validator
  confirms the effect on 1.35.2 and refutes it on 1.37.3.
- Synthetic lab credentials only. Never point the seed at a real instance.
- Re-resolve the digests and re-check the advisory range before reusing a pin
  after an upstream release.
