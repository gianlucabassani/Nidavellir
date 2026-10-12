#!/usr/bin/env python3
"""Variant-hunt probe round: twelve retained hypotheses against pinned Paperless.

Each hypothesis carries provenance (advisory + fix commit), an expected
observable, and controls in the established shape. Results classify as
confirmed / refuted / by-design / infrastructure-failure. Synthetic lab
credentials only; local lab target only.

Usage: python3 scripts/probe-paperless-variants.py --require-prereg <sha>
       --round-tag <tag>
(builds a keep-alive seeded stack, probes, tears everything down, prints
a JSON result table)

RESEARCH-R1/R4: --require-prereg names an ancestor commit containing a structured
manifest at docs/research/registrations/<tag>.json. Its target, IDs, executable
request/control definitions and script/fixture/gate hashes must match this run.
Journal substrings are only a hint. Results retain both identities. This gate
proves correspondence, not control validity or historical pre-registration.
Generate a candidate with --round-tag <tag> --write-registration <path>, review
its executable definitions, then commit it before probing. No probe runs in
candidate mode.
"""
from __future__ import annotations

import argparse
import importlib.util
import hashlib
import types
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LOADED_PROBE_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_spec = importlib.util.spec_from_file_location(
    "research_registration", ROOT / "scripts/research_registration.py")
registration = importlib.util.module_from_spec(_spec)
_registration_source = (ROOT / "scripts/research_registration.py").read_bytes()
_LOADED_GATE_DIGEST = hashlib.sha256(_registration_source).hexdigest()
exec(compile(_registration_source,
             str(ROOT / "scripts/research_registration.py"), "exec"),
     registration.__dict__)  # nosec B102 - trusted local gate; bypass stale pyc


def registration_candidate(tag: str, root=ROOT) -> dict:
    return registration.candidate(tag, root)


def finalize_results(results: list[dict], receipt: dict) -> dict:
    return registration.finalize(results, receipt)


def status_of(call):
    try:
        return call()
    except RuntimeError as exc:
        text = str(exc)
        if "HTTP" not in text:
            return None, {"error_type": "transport"}
        status, _, raw = text.split("HTTP", 1)[1].strip().partition(" ")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error_type": "non-json-http-error"}
        return int(status), body
    except (ValueError, OSError) as exc:
        # Non-JSON/empty body on a 2xx: unexpected shape, record, don't crash.
        return None, {"error": f"unparsable response: {type(exc).__name__}"}


def check_prereg(prereg: str, tag: str, root=ROOT) -> dict:
    """Verify a committed structured registration before importing the fixture."""
    return registration.check(
        prereg, tag, root, loaded_probe_digest=_LOADED_PROBE_DIGEST,
        loaded_gate_digest=_LOADED_GATE_DIGEST,
        loaded_functions={fn.__name__: fn.__code__ for fn in
                          (main, status_of, finalize_results, registration_candidate, check_prereg)})


def main(prereg: str, tag: str) -> None:
    receipt = check_prereg(prereg, tag, root=ROOT)
    fixture_path = ROOT / registration.FIXTURE
    fixture_source = registration.source_bytes(ROOT, registration.FIXTURE)
    if hashlib.sha256(fixture_source).hexdigest() != receipt["sources"][registration.FIXTURE]:
        raise SystemExit("refusing to probe: fixture changed after registration check")
    fixture = types.ModuleType("paperless_build_fixture")
    fixture.__file__ = str(fixture_path)
    exec(compile(fixture_source, str(fixture_path), "exec"),
         fixture.__dict__)  # nosec B102 - execute exactly the checked local fixture bytes
    manifest = fixture.build(keep=True)
    try:
        base, tokens = manifest["base_url"], manifest["tokens"]
        A, B = tokens["A"], tokens["B"]
        requests = []

        def call(base, method, path, **kwargs):
            body = kwargs.get("body") or {}
            # Keep concrete control inputs while excluding credentials and text.
            public_body = {key: body[key] for key in
                           ("id", "account", "documents", "mail_ids", "groups",
                            "is_superuser", "method", "parameters", "set_permissions") if key in body}
            requests.append({"method": method, "path": path,
                             "actor": "member" if kwargs.get("token") == B else "owner",
                             "body": public_body})
            return fixture._call(base, method, path, **kwargs)
        results = []

        def observation(body):
            if not isinstance(body, dict):
                return {"shape": type(body).__name__}
            # Retain identity/effect evidence, never tokens, mailbox passwords or text.
            return {key: body[key] for key in
                    ("id", "owner", "groups", "is_superuser", "is_staff", "success",
                     "deleted_mail_ids", "current_version_id", "permissions", "account") if key in body} | {
                        "row_ids": [row.get("id") for row in body.get("results", [])
                                    if isinstance(row, dict)],
                        "version_ids": [row.get("id") for row in body.get("versions", [])
                                        if isinstance(row, dict)]}

        def record(hid, provenance, expected, actor_call, control_calls, classify):
            try:
                status, body = status_of(actor_call)
                actor_request = requests[-1] if requests else None
                controls = {}
                for label, fn, want in control_calls:
                    got, control_body = status_of(fn)
                    predicate, kind = None, "prerequisite"
                    if isinstance(want, tuple):
                        want, predicate, *kinds = want
                        if kinds:
                            kind = kinds[0]
                    if want is None:
                        controls[label] = {"status": got, "expected": None, "assertive": False}
                    else:
                        controls[label] = {"status": got, "expected": want, "assertive": True,
                                           "held": got == want and (predicate(control_body) if predicate else True)}
                    controls[label]["observation"] = observation(control_body)
                    controls[label]["request"] = requests[-1] if requests else None
                    controls[label]["kind"] = kind
                prerequisites = [c for c in controls.values() if c["kind"] == "prerequisite"]
                healthy = any(c["assertive"] for c in prerequisites) and all(
                    c.get("held", c["status"] is not None and c["status"] < 400)
                    for c in prerequisites)
                verdict = classify(status, body, controls) if healthy else "infrastructure-failure"
                effects = [c for c in controls.values() if c["kind"] == "effect"]
                if verdict == "refuted" and not all(c.get("held") for c in effects):
                    verdict = "infrastructure-failure"
                elif verdict == "confirmed" and effects:
                    if any(c["status"] not in (c["expected"], 404) for c in effects):
                        verdict = "infrastructure-failure"
                    elif all(c["held"] for c in effects):
                        verdict = "inconclusive"
            except Exception as exc:  # noqa: BLE001 - retain one failed probe, continue the round
                status, controls, verdict = None, {}, "infrastructure-failure"
                body = {"error_type": type(exc).__name__}
                actor_request = None
            results.append({"id": hid, "provenance": provenance, "expected": expected,
                            "actor_status": status, "actor_request": actor_request,
                            "actor_observation": observation(body),
                            "controls": controls, "verdict": verdict})

        rid, sid = manifest["restricted_document"], manifest["shared_document"]
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
                        "u.user_permissions.add(Permission.objects.get(codename='change_document'), "
                        "Permission.objects.get(codename='delete_document'))\n"
                        "print('granted')")
            h2_ready = True
        except Exception as exc:  # noqa: BLE001
            results.append({"id": "H2", "provenance": "setup failed", "expected": "",
                            "actor_status": None, "controls": {},
                            "verdict": "infrastructure-failure",
                            "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
            h2_ready = False
        if h2_ready:
            vid = manifest["restricted_version"]
            record("H2", "8aab34ea7 versions global-check (object branch untested)",
                   "denied 403 (object gate after global gate)",
                   lambda: call(base, "DELETE", f"/api/documents/{rid}/versions/{vid}/",
                                token=B),
                   [("member_version_delete", lambda: call(
                       base, "DELETE", f"/api/documents/{manifest['member_document']}/versions/{manifest['member_version']}/",
                       token=B), 200),
                    ("owner_versions_intact", lambda: call(
                       base, "GET", f"/api/documents/{rid}/", token=A),
                     (200, lambda b: vid in [v["id"] for v in b.get("versions", [])], "effect"))],
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
            _, before_restricted = call(base, "GET", f"/api/documents/{sid}/?full_perms=true", token=A)
            record("H3", "GHSA-w47q-3m69-84v8 class via bulk path (ownership check)",
                   "denied 403 and restricted perms unchanged",
                   lambda: call(base, "POST", "/api/documents/bulk_edit/", token=B, body={
                       "documents": [sid], "method": "set_permissions",
                       "parameters": {"set_permissions": {"view": {"users": [], "groups": []},
                                                            "change": {"users": [], "groups": []}}}}),
                   [("member_owned_set_permissions", lambda: call(
                       base, "POST", "/api/documents/bulk_edit/", token=B, body={
                           "documents": [manifest["member_document"]], "method": "set_permissions",
                           "parameters": {"owner": manifest["member_id"], "set_permissions": {"view": {"users": [], "groups": []},
                                                                "change": {"users": [], "groups": []}}}}), 200),
                    ("member_control_owner_preserved", lambda: call(
                       base, "GET", f"/api/documents/{manifest['member_document']}/", token=A),
                     (200, lambda b: b.get("owner") == manifest["member_id"])),
                    ("restricted_unmoved", lambda: call(
                       base, "GET", f"/api/documents/{sid}/?full_perms=true", token=A),
                     (200, lambda b: isinstance(b.get("permissions"), dict)
                      and b.get("permissions") == before_restricted.get("permissions")
                      and b.get("owner") == before_restricted.get("owner"), "effect"))],
                   lambda s, b, c: "refuted" if s == 403 else
                   ("confirmed" if s == 200 else "infrastructure-failure"))

        fixture.run("docker", "exec", "paperless-fixture-web", "python3",
                    "/usr/src/paperless/src/manage.py", "shell", "-c",
                    "from django.contrib.auth.models import User, Permission\n"
                    "User.objects.get(username='member').user_permissions.remove("
                    "Permission.objects.get(codename='delete_document'))")
        # H4 (F7 sibling — bulk delete without delete perm): member bulk-deletes
        # the shared doc it may only view.
        record("H4", "8aab34ea7 delete-perm gating (documents bulk path)",
               "denied 403 and document survives",
               lambda: call(base, "POST", "/api/documents/bulk_edit/", token=B, body={
                   "documents": [manifest["member_document"]], "method": "delete", "parameters": {}}),
               [("owner_bulk_delete", lambda: call(
                   base, "POST", "/api/documents/bulk_edit/", token=A, body={
                       "documents": [manifest["delete_control_document"]], "method": "delete", "parameters": {}}), 200),
                ("member_document_survives", lambda: call(
                   base, "GET", f"/api/documents/{manifest['member_document']}/", token=A), (200, None, "effect"))],
               lambda s, b, c: "refuted" if s == 403
               else ("confirmed" if s == 200 else "infrastructure-failure"))

        # H5 (F3 sibling — 06b2d5102 fixed is_superuser/is_staff): member edits
        # own groups / requests superuser.
        try:
            gid = manifest["control_group"]
            own_path = f"/api/users/{manifest['member_id']}/"
            _, before = call(base, "GET", own_path, token=A)
            positive_status, _ = status_of(lambda: call(
                base, "PATCH", own_path, token=B, body={"first_name": "Quality control"}))
            s1, _ = status_of(lambda: call(
                base, "PATCH", f"/api/users/{manifest['member_id']}/", token=B,
                body={"groups": [gid]}))
            s2, _ = status_of(lambda: call(
                base, "PATCH", f"/api/users/{manifest['member_id']}/", token=B,
                body={"is_superuser": True}))
            _, after = call(base, "GET", own_path, token=A)
            flags_unchanged = all(after.get(k) == before.get(k) for k in ("is_superuser", "is_staff"))
            group_changed = after.get("groups") != before.get("groups")
            # change_user authorizes user/group management; group assignment under
            # that global permission needs policy review and is not an exploit proof.
            h5_verdict = "infrastructure-failure" if positive_status != 200 else (
                "confirmed" if not flags_unchanged else (
                    "by-design" if s1 == 200 and group_changed and s2 == 403 else (
                        "refuted" if s1 == 403 and s2 == 403 else "infrastructure-failure")))
            results.append({"id": "H5",
                            "provenance": "GHSA-59xh-5vwx-4c4q / 06b2d5102 (groups vs fixed flags)",
                            "expected": "privilege flags denied; globally authorized group management recorded separately",
                            "actor_status": {"groups": s1, "is_superuser": s2},
                            "controls": {"member_profile_mutation": {"status": positive_status,
                                "expected": 200, "assertive": True, "held": positive_status == 200}},
                            "before": observation(before), "after": observation(after),
                            "verdict": h5_verdict})
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
               [("member_owned_process", lambda: call(
                   base, "POST", f"/api/mail_accounts/{manifest['member_mail_account']}/process/",
                   token=B), (200, lambda b: b.get("result") == "OK"))],
               lambda s, b, c: "refuted" if s in (403, 404) else
               ("confirmed" if s == 200 else "infrastructure-failure"))
        # M2 (class 4; rule->account FK): member creates a rule on admin's account.
        record("M2", "MailRuleSerializer.validate_account (change_mailaccount owner-aware)",
               "foreign account is denied or excluded from relation choices; member-owned rule create 201",
               lambda: call(base, "POST", "/api/mail_rules/", token=B, body={
                   "name": "rogue-rule", "account": acct, "enabled": False,
                   "folder": "INBOX"}),
               [("member_owned_rule_create", lambda: call(
                   base, "POST", "/api/mail_rules/", token=B, body={
                       "name": "control-rule", "account": manifest["member_mail_account"], "enabled": False,
                       "folder": "INBOX"}), 201)],
               lambda s, b, c: "refuted" if s in (403, 404) or (
                   s == 400 and isinstance(b.get("account"), list) and any(
                       "Invalid pk" in error and "does not exist" in error
                       for error in b["account"] if isinstance(error, str))) else
               ("confirmed" if s == 201 else "infrastructure-failure"))
        # M3 (class 5; processed-mail leakage): member lists processed mails.
        record("M3", "F2 class by another path (ProcessedMailViewSet filter)",
               "200 with no admin rows visible",
               lambda: call(base, "GET", "/api/processed_mail/?page_size=10", token=B),
               [("owner_processed_list", lambda: call(
                   base, "GET", "/api/processed_mail/?page_size=100", token=A),
                 (200, lambda b: any(row.get("owner") != manifest["member_id"]
                                    for row in b.get("results", []))))],
               lambda s, b, c: "refuted" if s == 200 and all(
                   row.get("owner") == manifest["member_id"] for row in b.get("results", []))
               and all(row in [r.get("id") for r in b.get("results", [])]
                       for row in manifest["member_processed_rows"])
               else ("confirmed" if s == 200 and any(
                   row.get("owner") != manifest["member_id"] for row in b.get("results", []))
                     else "infrastructure-failure"))
        # M4 (class 3; test-action sibling): member tests admin's account.
        record("M4", "MailAccountViewSet.test branch (change_mailaccount owner-aware)",
               "denied 403; admin test not denied",
               lambda: call(base, "POST", "/api/mail_accounts/test/", token=B, body={
                   "name": "probe", "id": acct, "imap_server": "paperless-fixture-sink",
                   "imap_port": 3143, "imap_security": 1,
                   "username": fixture.MAILBOX["login"], "password": "****"}),
               [("member_owned_test", lambda: call(
                   base, "POST", "/api/mail_accounts/test/", token=B, body={
                       "name": "probe", "id": manifest["member_mail_account"], "imap_server": "paperless-fixture-sink",
                       "imap_port": 3143, "imap_security": 1,
                       "username": fixture.MAILBOX["login"], "password": "****"}),
                 (200, lambda b: b.get("success") is True))],
               lambda s, b, c: "refuted" if s in (403, 404) else
               ("confirmed" if s == 200 else "infrastructure-failure"))
        # M5 (class 6; F8 regression c28c532be): mixed-batch bulk mail delete.
        try:
            _, _owned = call(base, "GET", "/api/processed_mail/?page_size=10", token=A)
            admin_pm = next((row["id"] for row in _owned.get("results", [])
                             if row.get("owner") != manifest["member_id"]), None)
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
                   "atomic 403 and both mixed-batch rows survive; member-only deletion succeeds",
                   lambda: call(base, "POST", "/api/processed_mail/bulk_delete/", token=B,
                                body={"mail_ids": [manifest["member_processed_rows"][0], admin_pm]}),
                   [("admin_row_survives", lambda: call(
                       base, "GET", "/api/processed_mail/?page_size=100",
                   token=A), (200, lambda b: all(row in [r.get("id") for r in b.get("results", [])]
                           for row in [admin_pm, manifest["member_processed_rows"][0]]), "effect")),
                    ("member_owned_delete", lambda: call(
                       base, "POST", "/api/processed_mail/bulk_delete/", token=B,
                       body={"mail_ids": [manifest["member_processed_rows"][1]]}),
                     (200, lambda b: b.get("deleted_mail_ids") == [manifest["member_processed_rows"][1]])),
                    ("member_deleted_row_absent", lambda: call(
                       base, "GET", "/api/processed_mail/?page_size=100", token=A),
                     (200, lambda b: manifest["member_processed_rows"][1] not in [
                         r.get("id") for r in b.get("results", [])])),
                ("mixed_rows_survive_after_control", lambda: call(
                   base, "GET", "/api/processed_mail/?page_size=100", token=A),
                 (200, lambda b: all(row in [r.get("id") for r in b.get("results", [])]
                     for row in [admin_pm, manifest["member_processed_rows"][0]]), "effect"))],
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

        print(json.dumps(finalize_results(results, receipt), indent=2, sort_keys=True))
    finally:
        subprocess.run(["docker", "rm", "-f", "paperless-fixture-web",
                        "paperless-fixture-db", "paperless-fixture-redis",
                        "paperless-fixture-sink", "paperless-fixture-gotenberg"],
                       capture_output=True, check=False)
        for name in ("pgdata", "data", "media", "consume", "export"):
            subprocess.run(["docker", "volume", "rm", "-f", f"paperless-fixture-{name}"],
                           capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", "paperless-fixture-net"],
                       capture_output=True, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-prereg",
                        help="pre-registration commit sha (must predate this run)")
    parser.add_argument("--round-tag", required=True,
                        help="round tag the pre-registration commit must introduce")
    parser.add_argument("--write-registration", type=Path,
                        help="write a review candidate only; never builds or probes")
    args = parser.parse_args()
    if args.write_registration:
        if args.require_prereg:
            parser.error("candidate generation and execution are separate modes")
        candidate = registration_candidate(args.round_tag)
        args.write_registration.parent.mkdir(parents=True, exist_ok=True)
        args.write_registration.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    elif not args.require_prereg:
        parser.error("execution requires --require-prereg <commit SHA>")
    else:
        sys.exit(main(args.require_prereg, args.round_tag))
