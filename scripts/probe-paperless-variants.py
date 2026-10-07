#!/usr/bin/env python3
"""Variant-hunt probe round: six sibling hypotheses against pinned Paperless.

Each hypothesis carries provenance (advisory + fix commit), an expected
observable, and controls in the established shape. Results classify as
confirmed / refuted / by-design / infrastructure-failure. Synthetic lab
credentials only; local lab target only.

Usage: python3 scripts/probe-paperless-variants.py --require-prereg <sha>
       --round-tag <tag>
(builds a keep-alive seeded stack, probes, tears everything down, prints
a JSON result table)

RESEARCH-R1/R4: the round's journal pre-registration must already be
committed; the script refuses to run unless <sha> is an ancestor of the
current HEAD *and* introduces the round's hypothesis block (matched by
<tag>) in docs/JOURNAL.md, so ordering and correspondence are provable
from history, not prose.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "paperless_build_fixture",
    ROOT / "cyber-range/fixtures/paperless/build_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def status_of(call):
    try:
        return call()
    except RuntimeError as exc:
        text = str(exc)
        code = int(text.split("HTTP")[1].split()[0]) if "HTTP" in text else None
        return code, {"error": text[:200]}
    except (ValueError, OSError) as exc:
        # Non-JSON/empty body on a 2xx: unexpected shape, record, don't crash.
        return None, {"error": f"unparsable response: {type(exc).__name__}"}


def check_prereg(prereg: str, tag: str, root=ROOT) -> None:
    """Refuse to probe unless the pre-registration binds ordering AND content.

    Ordering: <prereg> resolves and is an ancestor of HEAD. Content: the
    commit must introduce the round's hypothesis block in docs/JOURNAL.md —
    added lines containing the round tag plus a hypothesis marker — so an
    unrelated ancestor sha cannot satisfy the gate.
    """
    import re as _re

    if not prereg or len(prereg) > 64:
        raise SystemExit("refusing to probe: --require-prereg <commit> is mandatory")
    if not tag or not _re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", tag):
        raise SystemExit("refusing to probe: --round-tag must match [a-z0-9-]{1,32}")
    resolved = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", prereg],
        capture_output=True, text=True, check=False)
    if resolved.returncode:
        raise SystemExit(f"refusing to probe: unknown pre-registration {prereg!r}")
    sha = resolved.stdout.strip()
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"],
        capture_output=True, check=False)
    if ancestor.returncode:
        raise SystemExit(
            f"refusing to probe: {prereg!r} is not an ancestor of HEAD "
            "(commit the pre-registration first)")
    shown = subprocess.run(
        ["git", "-C", str(root), "show", sha, "--", "docs/JOURNAL.md"],
        capture_output=True, text=True, check=False)
    added = [line[1:] for line in shown.stdout.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    blob = "\n".join(added)
    if tag not in blob or "hypothes" not in blob.lower():
        raise SystemExit(
            f"refusing to probe: {sha[:12]} does not introduce a hypothesis "
            f"block for round {tag!r} in docs/JOURNAL.md")
    print(f"pre-registration {sha[:12]} verified (ancestor, round {tag!r} block present)",
          flush=True)


def main(prereg: str, tag: str) -> None:
    check_prereg(prereg, tag)
    manifest = fixture.build(keep=True)
    base, tokens = manifest["base_url"], manifest["tokens"]
    A, B = tokens["A"], tokens["B"]
    call = fixture._call
    results = []

    def record(hid, provenance, expected, actor_call, control_calls, classify):
        # RESEARCH-R2: a control carries assertive=true only when it asserts
        # an expected value; observational controls record observed status
        # with no verdict (no `held` key at all — never `held: false`).
        try:
            status, body = status_of(actor_call)
            controls = {}
            for label, fn, want in control_calls:
                got, _ = status_of(fn)
                if want is None:
                    controls[label] = {"status": got, "expected": None,
                                       "assertive": False}
                else:
                    controls[label] = {"status": got, "expected": want,
                                       "assertive": True, "held": got == want}
            verdict = classify(status, body, controls)
        except Exception as exc:  # noqa: BLE001 - one bad probe must not kill the round
            status, controls, verdict = None, {}, "infrastructure-failure"
            body = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        results.append({"id": hid, "provenance": provenance,
                        "expected": expected, "actor_status": status,
                        "controls": controls, "verdict": verdict})

    rid, sid = manifest["restricted_document"], manifest["shared_document"]
    teardown = ["docker", "rm", "-f", "paperless-fixture-web",
                "paperless-fixture-db", "paperless-fixture-redis"]
    volumes = [f"paperless-fixture-{v}" for v in
               ("pgdata", "data", "media", "consume", "export")]
    try:
        _, links = call(base, "GET", "/api/share_links/?page_size=10", token=A)
        admin_link = links["results"][0]["id"]
    except Exception as exc:  # noqa: BLE001 - record and continue without H1
        results.append({"id": "H1", "provenance": "setup failed",
                        "expected": "", "actor_status": None, "controls": {},
                        "verdict": "infrastructure-failure",
                        "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
        admin_link = None

    # H1 (F1 sibling — b010f65ae fixed CREATE): member reads admin's share link.
    if admin_link is not None:
        record("H1", "GHSA-386h-chg4-cfw9 / b010f65ae (detail vs fixed create)",
               "denied 403/404 (PaperlessObjectPermissions on ShareLink.owner)",
               lambda: call(base, "GET", f"/api/share_links/{admin_link}/", token=B),
               [("owner_read_link", lambda: call(
                   base, "GET", f"/api/share_links/{admin_link}/", token=A), 200)],
               lambda s, b, c: "refuted" if s in (403, 404) and c["owner_read_link"]["held"]
               else "confirmed" if s == 200 else "infrastructure-failure")

    # H2 (F6 sibling — 8aab34ea7 added global check on versions): member WITH
    # global change_document but no object grant reads restricted versions.
    try:
        fixture.run("docker", "exec", "paperless-fixture-web", "python3",
                    "/usr/src/paperless/src/manage.py", "shell", "-c",
                    "from django.contrib.auth.models import User, Permission\n"
                    "u = User.objects.get(username='member')\n"
                    "u.user_permissions.add(Permission.objects.get(codename='change_document'))\n"
                    "print('granted')")
        h2_ready = True
    except Exception as exc:  # noqa: BLE001
        results.append({"id": "H2", "provenance": "setup failed", "expected": "",
                        "actor_status": None, "controls": {},
                        "verdict": "infrastructure-failure",
                        "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
        h2_ready = False
    if h2_ready:
        _, detail = call(base, "GET", f"/api/documents/{rid}/", token=A)
        vid = (detail.get("versions") or [{}])[0].get("id", rid)
        record("H2", "8aab34ea7 versions global-check (object branch untested)",
               "denied 403 (object gate after global gate)",
               lambda: call(base, "DELETE", f"/api/documents/{rid}/versions/{vid}/",
                            token=B),
               [("owner_versions_intact", lambda: call(
                   base, "GET", f"/api/documents/{rid}/", token=A), 200)],
               lambda s, b, c: "refuted" if s in (403, 404) else
               ("confirmed" if s in (200, 204) else "infrastructure-failure"))

    # H3 (F7/GHSA-w47q sibling — bulk set_permissions escalation): member with
    # object-level CHANGE grant (non-owner) on the shared doc tries to grant
    # itself view on the restricted doc via bulk set_permissions.
    try:
        call(base, "PATCH", f"/api/documents/{sid}/", token=A, body={
            "set_permissions": {"view": {"users": [manifest["member_id"]], "groups": []},
                                "change": {"users": [manifest["member_id"]], "groups": []}}})
        h3_ready = True
    except Exception as exc:  # noqa: BLE001
        results.append({"id": "H3", "provenance": "setup failed", "expected": "",
                        "actor_status": None, "controls": {},
                        "verdict": "infrastructure-failure",
                        "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
        h3_ready = False
    if h3_ready:
        record("H3", "GHSA-w47q-3m69-84v8 class via bulk path (ownership check)",
               "denied 403 and restricted perms unchanged",
               lambda: call(base, "POST", "/api/documents/bulk_edit/", token=B, body={
                   "documents": [rid], "method": "set_permissions",
                   "parameters": {"set_permissions": {"view": {"users": [manifest["member_id"]]}}}}),
               [("restricted_unmoved", lambda: call(
                   base, "GET", f"/api/documents/{rid}/", token=A), 200)],
               lambda s, b, c: "refuted" if s == 403 else
               ("confirmed" if s == 200 else "infrastructure-failure"))

    # H4 (F7 sibling — bulk delete without delete perm): member bulk-deletes
    # the shared doc it may only view.
    record("H4", "8aab34ea7 delete-perm gating (documents bulk path)",
           "denied 403 and document survives",
           lambda: call(base, "POST", "/api/documents/bulk_edit/", token=B, body={
               "documents": [sid], "method": "delete", "parameters": {}}),
           [("shared_survives", lambda: call(
               base, "GET", f"/api/documents/{sid}/", token=A), 200)],
           lambda s, b, c: "refuted" if s == 403 and c["shared_survives"]["held"]
           else ("confirmed" if s == 200 else "infrastructure-failure"))

    # H5 (F3 sibling — 06b2d5102 fixed is_superuser/is_staff): member edits
    # own groups / requests superuser.
    try:
        _, groups = call(base, "GET", "/api/groups/?page_size=10", token=A)
        gid = groups["results"][0]["id"] if groups.get("results") else 1
        s1, _ = status_of(lambda: call(
            base, "PATCH", f"/api/users/{manifest['member_id']}/", token=B,
            body={"groups": [gid]}))
        s2, _ = status_of(lambda: call(
            base, "PATCH", f"/api/users/{manifest['member_id']}/", token=B,
            body={"is_superuser": True}))
        results.append({"id": "H5",
                        "provenance": "GHSA-59xh-5vwx-4c4q / 06b2d5102 (groups vs fixed flags)",
                        "expected": "both denied 403; groups unchanged",
                        "actor_status": {"groups": s1, "is_superuser": s2},
                        "controls": {}, "verdict": "refuted" if s1 == 403 and s2 == 403
                        else ("confirmed" if 200 in (s1, s2) else "infrastructure-failure")})
    except Exception as exc:  # noqa: BLE001
        results.append({"id": "H5", "provenance": "setup failed", "expected": "",
                        "actor_status": None, "controls": {},
                        "verdict": "infrastructure-failure",
                        "note": f"{type(exc).__name__}: {str(exc)[:160]}"})

    # H6 (F9 sibling — 81795bc93 fixed autocomplete): system status content
    # for a restricted member.
    record("H6", "81795bc93 bare-auth views (system status content)",
           "member gated (403/404) or 200 with stats only, no user-scoped data",
           lambda: call(base, "GET", "/api/status/", token=B),
           [("admin_status", lambda: call(base, "GET", "/api/status/", token=A), 200)],
           lambda s, b, c: "refuted" if s in (403, 404) and c["admin_status"]["held"]
           else ("by-design" if s == 200 and not any(
               k in json.dumps(b) for k in ("member@lab.invalid", "lab-admin-only",
                                            "restricted-secret"))
           else ("confirmed" if s == 200 else "infrastructure-failure")))

    # --- mail round M1-M6 (needs manifest mail ids) -------------------------
    acct = manifest["mail_account_id"]
    # M1 (class 3; F5-sibling 65ca78e9e): member triggers processing on the
    # admin's mail account.
    record("M1", "GHSA-7qqc-wrcw-2fj9 / 65ca78e9e (process vs fixed update)",
           "denied 403/404; admin trigger not denied",
           lambda: call(base, "POST", f"/api/mail_accounts/{acct}/process/",
                        token=B),
           [("owner_process_not_denied", lambda: call(
               base, "POST", f"/api/mail_accounts/{acct}/process/",
               token=A), None)],
           lambda s, b, c: "refuted" if s in (403, 404) else
           ("confirmed" if s == 200 else "infrastructure-failure"))
    # M2 (class 4; rule->account FK): member creates a rule on admin's account.
    record("M2", "MailRuleSerializer.validate_account (change_mailaccount owner-aware)",
           "denied 403; admin rule create 201",
           lambda: call(base, "POST", "/api/mail_rules/", token=B, body={
               "name": "rogue-rule", "account": acct, "enabled": False,
               "folder": "INBOX"}),
           [("owner_rule_create", lambda: call(
               base, "POST", "/api/mail_rules/", token=A, body={
                   "name": "control-rule", "account": acct, "enabled": False,
                   "folder": "INBOX"}), 201)],
           lambda s, b, c: "refuted" if s in (403, 404) else
           ("confirmed" if s == 201 else "infrastructure-failure"))
    # M3 (class 5; processed-mail leakage): member lists processed mails.
    record("M3", "F2 class by another path (ProcessedMailViewSet filter)",
           "200 with no admin rows visible",
           lambda: call(base, "GET", "/api/processed_mail/?page_size=10", token=B),
           [("owner_processed_list", lambda: call(
               base, "GET", "/api/processed_mail/?page_size=10", token=A), 200)],
           lambda s, b, c: "refuted" if s == 200 and not (b.get("results") or [])
           else ("confirmed" if s == 200 and (b.get("results") or [])
                 else "infrastructure-failure"))
    # M4 (class 3; test-action sibling): member tests admin's account.
    record("M4", "MailAccountViewSet.test branch (change_mailaccount owner-aware)",
           "denied 403; admin test not denied",
           lambda: call(base, "POST", "/api/mail_accounts/test/", token=B, body={
               "name": "probe", "id": acct, "imap_server": "x",
               "imap_port": 143, "imap_security": 1,
               "username": "x", "password": "****"}),
           [("owner_test_not_denied", lambda: call(
               base, "POST", "/api/mail_accounts/test/", token=A, body={
                   "name": "probe", "id": acct, "imap_server": "x",
                   "imap_port": 143, "imap_security": 1,
                   "username": "x", "password": "****"}), None)],
           lambda s, b, c: "refuted" if s in (403, 404) else
           ("confirmed" if s == 200 else "infrastructure-failure"))
    # M5 (class 6; F8 regression c28c532be): mixed-batch bulk mail delete.
    try:
        _, _owned = call(base, "GET", "/api/processed_mail/?page_size=10", token=A)
        admin_pm = (_owned.get("results") or [{}])[0].get("id")
        if admin_pm is None:
            raise RuntimeError("no processed mail rows to target")
    except Exception as exc:  # noqa: BLE001
        results.append({"id": "M5", "provenance": "setup failed", "expected": "",
                        "actor_status": None, "controls": {},
                        "verdict": "infrastructure-failure",
                        "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
        admin_pm = None
    if admin_pm is not None:
        record("M5", "c28c532be whole-batch atomic reject",
               "atomic 403 and admin row survives",
               lambda: call(base, "POST", "/api/processed_mail/bulk_delete/", token=B,
                            body={"mail_ids": [admin_pm]}),
               [("admin_row_survives", lambda: call(
                   base, "GET", "/api/processed_mail/?page_size=10",
                   token=A), 200)],
               lambda s, b, c: "refuted" if s in (403, 404) else
               ("confirmed" if s == 200 else "infrastructure-failure"))
    # M6 (class 3 detail; account read): member reads admin's mail account.
    record("M6", "MailAccountViewSet detail (PaperlessObjectPermissions)",
           "denied 403/404; owner reads 200",
           lambda: call(base, "GET", f"/api/mail_accounts/{acct}/", token=B),
           [("owner_read_account", lambda: call(
               base, "GET", f"/api/mail_accounts/{acct}/", token=A), 200)],
           lambda s, b, c: "refuted" if s in (403, 404) and c["owner_read_account"]["held"]
           else ("confirmed" if s == 200 else "infrastructure-failure"))

    teardown = ["docker", "rm", "-f", "paperless-fixture-web",
                "paperless-fixture-db", "paperless-fixture-redis",
                "paperless-fixture-sink", "paperless-fixture-gotenberg"]
    volumes = [f"paperless-fixture-{v}" for v in
               ("pgdata", "data", "media", "consume", "export")]
    try:
        print(json.dumps({"hypotheses": results}, indent=2, sort_keys=True))
    finally:
        subprocess.run(teardown, capture_output=True, check=False)
        for volume in volumes:
            subprocess.run(["docker", "volume", "rm", "-f", volume],
                           capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", "paperless-fixture-net"],
                       capture_output=True, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-prereg", required=True,
                        help="pre-registration commit sha (must predate this run)")
    parser.add_argument("--round-tag", required=True,
                        help="round tag the pre-registration commit must introduce")
    args = parser.parse_args()
    sys.exit(main(args.require_prereg, args.round_tag))
