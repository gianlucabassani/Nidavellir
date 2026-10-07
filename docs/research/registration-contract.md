# Research registration / execution contract (RESEARCH-R1/R4)

Implemented for the standalone Paperless adapter in Phase 2, 2026-10-07.
This is correspondence machinery, not a validator of hypothesis quality, control
health, novelty, isolation or historical chronology. Phase 3 remains required.

## Operator and agent workflow

1. Finish editing the probe and fixture before registration. Choose a round tag.
2. Generate a candidate without importing the fixture or starting a target:

   ```bash
   python3 scripts/probe-paperless-variants.py --round-tag paperless-next \
     --write-registration docs/research/registrations/paperless-next.json
   ```

3. Review its target pins and every executable hypothesis definition. The definitions
   include request/control syntax, expected conditions, classifier and local setup/error
   alternatives; source hashes also bind shared setup and helper code. These are canonical
   Python statements, not a natural-language interpretation. A misleading comment or
   classifier remains a research defect even when the program matches its registration.
4. Commit the reviewed manifest before execution. Record that commit's SHA. Do not edit
   the probe, fixture or gate after this point; changes require a new registration.
5. Execute with that SHA:

   ```bash
   python3 scripts/probe-paperless-variants.py --require-prereg <commit-sha> \
     --round-tag paperless-next
   ```

6. Retain stdout as a new dated evidence artifact. Do not overwrite historical results.
   Do not claim a refutation until healthy controls isolate the intended protection.

The round tag names a manifest; it does **not** select a subset. The current adapter
executes all H1–H6 and M1–M6. The candidate exposes that exact ordered ID set. Target or
probe changes, including a future mail-only adapter, require a new reviewed registration.
No valid empirical registration is committed by the Phase 2 implementation itself.

## Admission

The fixed manifest location is `docs/research/registrations/<tag>.json` **at the supplied
commit**, never the working-tree copy. SHA-only commits must resolve to an ancestor of
HEAD. JSON has an exact schema, rejects duplicate keys and is byte-bounded. Git reads
reuse Phase 1's helper/transport suppression, output caps and timeout.

`nidavellir/research-registration/v1` contains exactly:

- `schema`, `round_tag`;
- `target`: declared fixture version and digest-pinned images;
- `sources`: SHA-256 of probe, fixture, registration helper and Git runner;
- `hypotheses`: ordered IDs and canonical executable `definitions` derived from source.

Admission compares the entire manifest with one captured source snapshot. It also
checks loaded probe/helper identities and compares all five actual probe functions,
including the gate wrapper, to compilation of the same probe snapshot. This rejects
stale timestamp-cache code even if its startup `__file__` hash is fresh. Gate/Git helper
imports compile captured bytes; fixture import occurs only after admission, hashes a
captured fixture against the receipt, then compiles those same bytes.

The old journal substring condition survives only as `journal_marker_hint`. Its absence
never refuses a valid manifest; its presence never admits an invalid one. No retrospective
journal text or historical result is certified by a new registration.

Known synthetic fixture passwords are replaced with SHA-256 references inside canonical
definitions. Target metadata contains no passwords/tokens; executable files themselves
are represented only by their hashes. This is a narrowly scoped adapter, not a general
source-secret scanner. New secret-bearing adapters need reviewed export handling.

## Results and limits

`nidavellir/research-probe-results/v2` retains a registration receipt with commit/path,
canonical registration/execution digests, target, source hashes, ordered hypothesis IDs,
per-definition digests and the advisory journal hint. Every result row carries its bound
definition digest. Finalization refuses missing, duplicate, extra or reordered IDs.

`recorded_hypothesis_ids` means rows were recorded, **not** that every probe completed:
setup failures still produce infrastructure-failure rows. Existing classifiers and their
control-validity gaps are intentionally unchanged. This gate binds a trusted local Python
adapter; it does not sandbox a malicious operator-modified program or attest Python,
Docker, OS and upstream dependencies. Actual runtime isolation/reset/cleanup remain
separate acceptance work.

M6 was able to diverge because its prose registration and hardcoded implementation were
independent: both kept the string M6, while trash operations became account-detail access.
The structured gate rejects a registration containing the trash definition even when its
ID set and all current executable hashes are otherwise correct. Both the definition and
the executable identity are load-bearing; IDs or script hashes alone are insufficient.
