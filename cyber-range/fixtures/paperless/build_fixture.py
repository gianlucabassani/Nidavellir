#!/usr/bin/env python3
"""Build a pinned, pre-seeded Paperless-ngx fixture for Nidavellir.

The seed uses only the pinned upstream images and the product's own HTTP
API: two users (admin owner, restricted member), two documents (one
restricted, one shared with the member), explicit object permissions, and
one admin-created share link on the shared document. Synthetic lab
credentials only; never point this at a real Paperless instance.

Auth notes learned during probing (2026-10-06, 3.3.0): tokens come from
POST /api/token/ (not /api/auth/token/); API calls use
`Authorization: Token <key>`; a member needs global view permissions
(e.g. view_document) for the list endpoint, while object-level denial is
a 404; share-link creation, bulk edit, notes, download, metadata, thumb
and versions endpoints all deny the member correctly on 3.3.0 (refuted
hypotheses H1–H4, recorded in docs/JOURNAL.md).

Reset is deleting the three data volumes and re-running this script; the
seed order is fixed so fresh databases yield identical object IDs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Immutable upstream digests resolved on 2026-10-06 (Docker Hub tags API).
PINS = {
    "paperless": "paperlessngx/paperless-ngx:3.3.0@sha256:"
                 "d70526917791fb99ee61b40a91f111d60c59914f36cfd481af494107054aed06",
    "redis": "redis:7-alpine@sha256:"
             "520775a41a63e77e06c73e35d2fd9cc15921a609516818796b4ecbb813078bc7",
    "postgres": "postgres:16@sha256:"
                "65b16a8b326e0cfbdf33fa7e783f2a0cb352a61448616ccccfd616ef42aa0f65",
    "greenmail": "greenmail/standalone:2.1.14@sha256:"
                 "2bcd0470f569af3c8b98509421b23f1ad11ebb2d58c3648f4233bf450f3b5e2b",
    "gotenberg": "gotenberg/gotenberg:8.37.0@sha256:"
                 "3fdee07e0dcd5005c3db4d81d1600d081fc6fb424da87e409e1c1f9624a249b8",
}
MAILBOX = {"login": "labmail", "password": "lab-mail-only",
           "email": "labmail@lab.invalid"}
MAIL_SUBJECT = "invoice q3 secret"
MAIL_MARKER = "body marker ALPHA-7"
VERSION = "3.3.0"
ADMIN = {"username": "admin", "password": "lab-admin-only", "email": "admin@lab.invalid"}
MEMBER = {"username": "member", "password": "lab-member-only", "email": "member@lab.invalid"}
MEMBER_GLOBAL_PERMS = ["view_document", "view_tag", "view_correspondent",
                       "view_documenttype", "view_storagepath", "view_savedview",
                       "view_sharelink", "view_task", "view_group", "view_user",
                       "view_processedmail", "view_mailrule", "view_mailaccount"]
DOCS = (("restricted-secret-1", "restricted secret alpha"),
        ("shared-note-1", "shared note bravo"))

PDF_TEMPLATE = (
    "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
    "/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    "4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (@@TEXT@@) Tj ET\n"
    "endstream\nendobj\n"
    "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    "trailer<</Root 1 0 R>>\n%%EOF"
)


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stdout[-1200:]} {result.stderr[-1200:]}")
    return result


def _call(base, method, path, token=None, body=None, files=None):
    if files is not None:
        boundary = "nidavellir" + uuid.uuid4().hex
        parts = []
        for key, value in (body or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                         f'name="{key}"\r\n\r\n{value}\r\n'.encode())
        for key, (filename, data) in files.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                         f'name="{key}"; filename="{filename}"\r\n'
                         f"Content-Type: application/pdf\r\n\r\n".encode() + data
                         + b"\r\n")
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    else:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Token " + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310 - loopback
            raw = response.read()
            return response.status, json.loads(raw.decode() or "{}") if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"{method} {path}: HTTP {exc.code} "
            f"{exc.read().decode('utf-8', 'replace')[:200]}") from exc


def _token(base, username, password):
    _, body = _call(base, "POST", "/api/token/",
                    body={"username": username, "password": password})
    return body["token"]


def _host_base(name):
    port = run("docker", "port", name, "8000").stdout.strip().rsplit(":", 1)[1]
    return f"http://127.0.0.1:{port}"


def _sink_bases():
    """Loopback ports for the sink (ephemeral host ports re-resolved)."""
    out = run("docker", "port", "paperless-fixture-sink").stdout.strip().splitlines()
    ports = {}
    for line in out:
        private, _, public = line.partition(" -> ")
        ports[int(private.rsplit("/", 1)[0])] = int(public.rsplit(":", 1)[1])
    return {"smtp": ports[3025], "imap": ports[3143], "api": ports[8080]}


def _seed_mail(sink_api, base, token_a):
    """Seed one mailbox, inject one message, wire account+rule, consume it."""
    import smtplib
    from email.message import EmailMessage

    _call(sink_api, "POST", "/api/user", body={
        "login": MAILBOX["login"], "password": MAILBOX["password"],
        "email": MAILBOX["email"]})
    message = EmailMessage()
    message["From"] = "sender@lab.invalid"
    message["To"] = MAILBOX["email"]
    message["Subject"] = MAIL_SUBJECT
    message.set_content(MAIL_MARKER)
    with smtplib.SMTP("127.0.0.1", _sink_bases()["smtp"], timeout=15) as sender:
        sender.send_message(message)
    _, account = _call(base, "POST", "/api/mail_accounts/", token=token_a, body={
        "name": "lab-inbox", "imap_server": "paperless-fixture-sink",
        "imap_port": 3143, "imap_security": 1,
        "username": MAILBOX["login"], "password": MAILBOX["password"]})
    _, rule = _call(base, "POST", "/api/mail_rules/", token=token_a, body={
        "name": "lab-consume", "account": account["id"], "enabled": True,
        "folder": "INBOX", "filter_subject": "invoice",
        "action": 3, "consumption_scope": 2, "assign_owner_from_rule": False})
    _call(base, "POST", f"/api/mail_accounts/{account['id']}/process/",
          token=token_a)
    consumed = None
    for _ in range(60):
        _, listing = _call(base, "GET", "/api/documents/?page_size=10", token=token_a)
        match = [d for d in listing.get("results", [])
                 if MAIL_SUBJECT in (d.get("title") or "")]
        if match:
            consumed = match[0]
            break
        time.sleep(5)
    if consumed is None:
        raise RuntimeError("mail-consumed document never appeared")
    return {"account_id": account["id"], "rule_id": rule["id"],
            "consumed_document": consumed["id"],
            "consumed_owner": consumed.get("owner")}


def _wait_ready(base, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = _call(base, "GET", "/api/documents/?page_size=1",
                              token=_admin_token[0])
            if status == 200:
                return
        except (RuntimeError, OSError, urllib.error.URLError):
            pass
        time.sleep(3)
    raise RuntimeError("paperless fixture did not become ready")


_admin_token = [None]


def _manage(*args):
    result = run("docker", "exec", "paperless-fixture-web",
                 "python3", "/usr/src/paperless/src/manage.py", *args)
    return result.stdout.strip()


def build(keep: bool = False) -> dict:
    """Deploy the pinned stack, seed it, snapshot the control matrix.

    With keep=True the stack is left running (containers, volumes,
    network) and its loopback base URL is returned as ``base_url`` for
    hypothesis probing; the caller owns teardown.
    """
    net = "paperless-fixture-net"
    run("docker", "network", "create", net, check=False)
    keep_alive = [False]
    containers = ["paperless-fixture-redis", "paperless-fixture-db",
                  "paperless-fixture-web", "paperless-fixture-sink",
                  "paperless-fixture-gotenberg"]
    volumes = {name: f"paperless-fixture-{name}"
               for name in ("pgdata", "data", "media", "consume", "export")}
    # Clean slate first: leftover volumes would silently unseat determinism.
    for name in containers:
        run("docker", "rm", "-f", name, check=False)
    for volume in volumes.values():
        run("docker", "volume", "rm", "-f", volume, check=False)
        run("docker", "volume", "create", volume, check=False)
    try:
        run("docker", "run", "-d", "--name", containers[0], "--network", net,
            PINS["redis"])
        run("docker", "run", "-d", "--name", containers[1], "--network", net,
            "-e", "POSTGRES_DB=paperless", "-e", "POSTGRES_USER=paperless",
            "-e", "POSTGRES_PASSWORD=paperless",
            "-v", f"{volumes['pgdata']}:/var/lib/postgresql/data", PINS["postgres"])
        run("docker", "run", "-d", "--name", containers[2], "--network", net,
            "-p", "127.0.0.1::8000",
            "-e", "PAPERLESS_REDIS=redis://paperless-fixture-redis:6379",
            "-e", "PAPERLESS_DBHOST=paperless-fixture-db",
            "-e", "PAPERLESS_DBNAME=paperless", "-e", "PAPERLESS_DBUSER=paperless",
            "-e", "PAPERLESS_DBPASS=paperless",
            "-e", "PAPERLESS_SECRET_KEY=nidavellir-lab-only-change-me",
            "-e", "PAPERLESS_TIKA_GOTENBERG_ENDPOINT=http://paperless-fixture-gotenberg:3000",
            "-e", "PAPERLESS_URL=http://localhost:8000",
            "-e", "PAPERLESS_ADMIN_USER=admin", "-e", "PAPERLESS_ADMIN_PASSWORD=lab-admin-only",
            "-e", "PAPERLESS_ADMIN_MAIL=admin@lab.invalid",
            "-v", f"{volumes['data']}:/usr/src/paperless/data",
            "-v", f"{volumes['media']}:/usr/src/paperless/media",
            "-v", f"{volumes['consume']}:/usr/src/paperless/consume",
            "-v", f"{volumes['export']}:/usr/src/paperless/export",
            PINS["paperless"])
        run("docker", "run", "-d", "--name", containers[3], "--network", net,
            "-p", "127.0.0.1::3025", "-p", "127.0.0.1::3143", "-p", "127.0.0.1::8080",
            PINS["greenmail"])
        run("docker", "run", "-d", "--name", containers[4], "--network", net,
            PINS["gotenberg"])
        base = _host_base(containers[2])
        _admin_token[0] = None
        deadline = time.monotonic() + 240
        token_a = None
        while time.monotonic() < deadline:
            try:
                token_a = _token(base, ADMIN["username"], ADMIN["password"])
                break
            except (RuntimeError, OSError, urllib.error.URLError):
                time.sleep(5)
        if token_a is None:
            raise RuntimeError("admin login never succeeded")
        _admin_token[0] = token_a
        _wait_ready(base)
        # Member with global view permissions (list works; objects gated per-object).
        _call(base, "POST", "/api/users/", token=token_a, body={
            "username": MEMBER["username"], "password": MEMBER["password"],
            "email": MEMBER["email"]})
        member_id = json.loads(run(
            "docker", "exec", containers[2], "python3",
            "/usr/src/paperless/src/manage.py", "shell", "-c",
            "from django.contrib.auth.models import User, Permission\n"
            "u = User.objects.get(username='member')\n"
            "u.user_permissions.add(*Permission.objects.filter("
            f"codename__in={MEMBER_GLOBAL_PERMS!r}))\n"
            "print(u.id)").stdout.strip().splitlines()[-1])
        token_b = _token(base, MEMBER["username"], MEMBER["password"])
        doc_ids = []
        for title, text in DOCS:
            pdf = PDF_TEMPLATE.replace("@@TEXT@@", text).encode()
            _, body = _call(base, "POST", "/api/documents/post_document/", token=token_a,
                            body={"title": title},
                            files={"document": (title + ".pdf", pdf)})
            task_id = body.strip('"') if isinstance(body, str) else body
            arrived = None
            for _ in range(60):
                _, listing = _call(base, "GET", "/api/documents/?page_size=10",
                                   token=token_a)
                match = [d for d in listing.get("results", []) if d["title"] == title]
                if match:
                    arrived = match[0]["id"]
                    break
                time.sleep(3)
            if arrived is None:
                raise RuntimeError(f"consumed document never appeared: {title} ({task_id})")
            doc_ids.append(arrived)
        restricted_id, shared_id = doc_ids
        _, users = _call(base, "GET", "/api/users/?page_size=10", token=token_a)
        admin_id = next(u["id"] for u in users["results"]
                        if u["username"] == ADMIN["username"])
        # Restricted: owner admin, no grants. Shared: view grant to the member.
        _call(base, "PATCH", f"/api/documents/{restricted_id}/", token=token_a, body={
            "owner": admin_id, "set_permissions": {"view": {"users": [], "groups": []},
                                                   "change": {"users": [], "groups": []}}})
        _call(base, "PATCH", f"/api/documents/{shared_id}/", token=token_a, body={
            "owner": admin_id,
            "set_permissions": {"view": {"users": [member_id], "groups": []},
                                "change": {"users": [], "groups": []}}})
        _, link = _call(base, "POST", "/api/share_links/", token=token_a,
                        body={"document": shared_id})
        sink_port = _sink_bases()["api"]
        mail = _seed_mail(f"http://127.0.0.1:{sink_port}", base, token_a)
        matrix = {}
        for label, tok, path, want in (
                ("owner_read_restricted", token_a, f"/api/documents/{restricted_id}/", 200),
                ("member_read_restricted", token_b, f"/api/documents/{restricted_id}/", 404),
                ("member_read_shared", token_b, f"/api/documents/{shared_id}/", 200),
                ("member_list", token_b, "/api/documents/", 200),
                ("owner_read_consumed", token_a,
                 f"/api/documents/{mail['consumed_document']}/", 200),
                ("member_read_consumed", token_b,
                 f"/api/documents/{mail['consumed_document']}/", 404),
                ("member_processed_list", token_b,
                 "/api/processed_mail/", 200)):
            try:
                status, _ = _call(base, "GET", path, token=tok)
            except RuntimeError as exc:
                status = int(str(exc).split("HTTP")[1].split()[0])
            matrix[label] = {"status": status, "expected": want}
            if status != want:
                raise RuntimeError(f"control matrix mismatch: {label} -> {status}, want {want}")
        manifest = {
            "schema": "nidavellir/paperless-fixture/v1", "version": VERSION,
            "pins": PINS, "admin": ADMIN["username"], "member": MEMBER["username"],
            "member_id": member_id, "restricted_document": restricted_id,
            "shared_document": shared_id, "share_slug": link["slug"],
            "mail_account_id": mail["account_id"], "mail_rule_id": mail["rule_id"],
            "mail_consumed_document": mail["consumed_document"],
            "mail_consumed_owner": mail["consumed_owner"],
            "control_matrix": matrix,
            "behavior_digest": "sha256:" + hashlib.sha256(
                json.dumps(matrix, sort_keys=True).encode()).hexdigest(),
            "tokens": {"A": token_a, "B": token_b},
        }
        if keep:
            manifest["base_url"] = base
            keep_alive[0] = True
        return manifest
    finally:
        if not keep_alive[0]:
            for name in reversed(containers):
                run("docker", "rm", "-f", name, check=False)
            for volume in volumes.values():
                run("docker", "volume", "rm", "-f", volume, check=False)
            run("docker", "network", "rm", net, check=False)


if __name__ == "__main__":
    manifest = build()
    # Tokens and the share slug authenticate against synthetic lab data only,
    # but manifests carry no auth material: verifiers re-derive them via the
    # lab passwords above, exactly like the Vaultwarden fixture flow.
    public = {k: v for k, v in manifest.items() if k not in ("tokens", "share_slug")}
    out = ROOT / "docs/verification" / f"paperless-fixture-{VERSION}.json"
    out.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
    print(json.dumps(public, indent=2, sort_keys=True))
