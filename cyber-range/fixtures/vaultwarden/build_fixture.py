#!/usr/bin/env python3
"""Build a pinned, pre-seeded Vaultwarden fixture image for Nidavellir.

The seed uses only the pinned upstream image, the product's own HTTP API for
account/organization creation, and one bounded SQLite insert for organization
membership, a restricted collection and two ciphers. Synthetic lab credentials
only; never point this at a real Vaultwarden instance.

The output is a local image ID (like the synthetic fixtures) that the scenario
pins. The seed recipe is deterministic; server-generated identifiers are
captured in the returned metadata and in the produced image.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Immutable upstream digests resolved on 2026-10-05 (Docker Hub tags API).
PINS = {
    "1.35.2": "vaultwarden/server@sha256:d89a6d21e361254670c24a4272b4b5f245e402c284f2f55de2c379fdbcfa1fa5",
    "1.37.3": "vaultwarden/server@sha256:1587c45feaa479f1f5e8af3b00eded36bff77bcf1880cf8dbf0541706dd470e0",
}
REGISTER_PATH = {
    "1.35.2": "/api/accounts/register",
    "1.37.3": "/identity/accounts/register",
}
CLIENT_HEADERS = {"Bitwarden-Client-Version": "2026.10.0", "Device-Type": "10"}
PASSWORDS = {"A": "lab-owner-a", "B": "lab-member-b"}
EMAILS = {"A": "owner@lab.invalid", "B": "member@lab.invalid"}

RESTRICTED_COLLECTION = "c0000000-0000-4000-8000-000000000001"
RESTRICTED_CIPHER = "c1000000-0000-4000-8000-000000000001"
SHARED_CIPHER = "c1000000-0000-4000-8000-000000000002"
MEMBER_ROW = "b0000000-0000-4000-8000-000000000001"

SEED_SQL = '''
import base64, sqlite3
db = sqlite3.connect("/data/db.sqlite3")
db.execute("PRAGMA busy_timeout=5000")
users = dict(db.execute("SELECT email, uuid FROM users").fetchall())
org = db.execute("SELECT uuid FROM organizations").fetchone()[0]
shared = db.execute("SELECT uuid FROM collections WHERE org_uuid=?", (org,)).fetchone()[0]
now = "2026-01-01 00:00:00"
db.execute(
    "INSERT OR REPLACE INTO users_organizations "
    "(uuid,user_uuid,org_uuid,access_all,akey,status,atype) VALUES (?,?,?,?,?,?,?)",
    ("b0000000-0000-4000-8000-000000000001", users["member@lab.invalid"], org, 0,
     base64.b64encode(b"o" * 47).decode(), 2, 2))
db.execute("INSERT OR REPLACE INTO collections (uuid,org_uuid,name,external_id) "
           "VALUES (?,?,?,NULL)",
           ("c0000000-0000-4000-8000-000000000001", org,
            base64.b64encode(b"restricted").decode()))
db.execute("INSERT OR REPLACE INTO users_collections "
           "(user_uuid,collection_uuid,read_only,hide_passwords,manage) VALUES (?,?,0,0,0)",
           (users["member@lab.invalid"], shared))
for cid, name, collection in (
        ("c1000000-0000-4000-8000-000000000001", b"restricted-secret",
         "c0000000-0000-4000-8000-000000000001"),
        ("c1000000-0000-4000-8000-000000000002", b"shared-secret", shared)):
    db.execute(
        "INSERT OR REPLACE INTO ciphers (uuid,created_at,updated_at,user_uuid,"
        "organization_uuid,atype,name,notes,fields,data,password_history,deleted_at,"
        "reprompt,key) VALUES (?,?,?,NULL,?,1,?,NULL,NULL,'{}',NULL,NULL,0,NULL)",
        (cid, now, now, org, base64.b64encode(name).decode()))
    db.execute("INSERT OR REPLACE INTO ciphers_collections (cipher_uuid,collection_uuid) "
               "VALUES (?,?)", (cid, collection))
db.commit()
print("seeded %s" % org)
'''


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stdout[-1200:]} {result.stderr[-1200:]}")
    return result


def _material(password: str, email: str, iterations: int = 600000) -> str:
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), email.lower().encode(),
                              iterations)
    return base64.b64encode(
        hashlib.pbkdf2_hmac("sha256", key, password.encode(), 1)).decode()


def _call(base: str, method: str, path: str, body=None, token=None, form=False):
    headers = dict(CLIENT_HEADERS)
    if body is not None:
        headers["Content-Type"] = ("application/x-www-form-urlencoded" if form
                                   else "application/json")
    if token:
        headers["Authorization"] = "Bearer " + token
    data = (urllib.parse.urlencode(body).encode() if form
            else json.dumps(body).encode()) if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310 - loopback
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path}: HTTP {exc.code} {payload[:200]}") from exc


def _host_base(name: str) -> str:
    """The current loopback URL for a started container (the ephemeral host
    port is re-allocated on every start, so it must be re-resolved)."""
    port = run("docker", "port", name, "80").stdout.strip().rsplit(":", 1)[1]
    return f"http://127.0.0.1:{port}"


def _wait_alive(base: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/alive", timeout=3):  # nosec B310
                return
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise RuntimeError("vaultwarden fixture did not become alive")


def _register(base: str, version: str, who: str) -> None:
    email = EMAILS[who]
    status, _ = _call(base, "POST", REGISTER_PATH[version], {
        "email": email, "name": who,
        "masterPasswordHash": _material(PASSWORDS[who], email),
        "key": base64.b64encode(b"k" * 64).decode(), "kdf": 0, "kdfIterations": 600000,
        "keys": {"publicKey": base64.b64encode(b"p" * 16).decode(),
                 "encryptedPrivateKey": base64.b64encode(b"e" * 64).decode()},
    })
    if status != 200:
        raise RuntimeError(f"register {email}: HTTP {status}")


def _login(base: str, who: str) -> str:
    email = EMAILS[who]
    _, body = _call(base, "POST", "/identity/connect/token", {
        "grant_type": "password", "username": email,
        "password": _material(PASSWORDS[who], email), "scope": "api offline_access",
        "client_id": "web", "deviceType": "10",
        "deviceIdentifier": str(uuid.uuid4()), "deviceName": "nidavellir-fixture",
    }, form=True)
    return body["access_token"]


def build(version: str) -> dict:
    """Build the fixture image and return its pinned ID plus seed metadata."""
    base_ref = PINS[version]
    run("docker", "pull", base_ref)
    digest = run("docker", "image", "inspect", base_ref,
                 "--format", "{{index .RepoDigests 0}}").stdout.strip()
    name = f"nidavellir-vw-seed-{version.replace('.', '')}-{uuid.uuid4().hex[:6]}"
    workdir = Path(tempfile.mkdtemp(prefix="nidavellir-vw-fixture-"))
    data = workdir / "data"
    data.mkdir()
    tokens = {}
    try:
        run("docker", "run", "-d", "--name", name, "-p", "127.0.0.1::80",
            "-v", f"{data}:/data", "-e", "SIGNUPS_ALLOWED=true",
            "-e", "DOMAIN=http://localhost", base_ref)
        base = _host_base(name)
        _wait_alive(base)
        for who in ("A", "B"):
            _register(base, version, who)
        token_a = _login(base, "A")
        _, org = _call(base, "POST", "/api/organizations", {
            "name": "nidavellir-lab", "billingEmail": EMAILS["A"], "planType": 0,
            "key": base64.b64encode(b"o" * 47).decode(),
            "collectionName": base64.b64encode(b"Default collection").decode(),
        }, token=token_a)
        run("docker", "stop", name)
        seed = SEED_SQL
        seeded = subprocess.run(
            ["docker", "run", "--rm", "-i", "-v", f"{data}:/data",
             "python:3.11.14-alpine", "python", "-"],
            input=seed, text=True, capture_output=True, check=False, cwd=ROOT)
        if seeded.returncode:
            raise RuntimeError(f"fixture seed failed: {seeded.stderr[-800:]}")
        run("docker", "start", name)
        base = _host_base(name)
        _wait_alive(base)
        tokens = {"A": _login(base, "A"), "B": _login(base, "B")}
        run("docker", "stop", name)
        context = workdir / "context"
        context.mkdir()
        shutil.copytree(data, context / "data")
        # The upstream image declares VOLUME /data, so the seeded directory is
        # copied into the container's anonymous volume at creation. Vaultwarden
        # refuses anonymous volumes unless this lab-only flag is set; an arena
        # is replaced wholesale, so volatile storage is intentional.
        (context / "Dockerfile").write_text(
            f"FROM {base_ref}\nENV I_REALLY_WANT_VOLATILE_STORAGE=true\nCOPY data /data\n")
        run("docker", "build", "-t", f"nidavellir/vaultwarden-fixture:{version}", str(context))
        image_id = run("docker", "image", "inspect",
                       f"nidavellir/vaultwarden-fixture:{version}",
                       "--format", "{{.Id}}").stdout.strip()
        return {
            "version": version, "base_ref": base_ref, "resolved_digest": digest,
            "image_id": image_id, "org_id": org["id"], "tokens": tokens,
            "restricted_collection": RESTRICTED_COLLECTION,
            "restricted_cipher": RESTRICTED_CIPHER, "shared_cipher": SHARED_CIPHER,
        }
    finally:
        run("docker", "rm", "-f", name, check=False)
        shutil.rmtree(workdir, ignore_errors=True)
