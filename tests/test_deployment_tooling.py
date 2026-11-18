"""Exercise real shell entrypoints in a disposable Git repo with a fake daemon.

No host containers, ports, networks or refs are mutated by these tests.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "0123456789abcdef0123456789abcdef"
STAMP = "20261118T120000-42"
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
a=sys.argv[1:]; root=pathlib.Path(os.environ["FIXTURE_STATE"])
with (root/"calls").open("a") as f: f.write(json.dumps(a)+"\n")
if a[0]=="compose":
 if "config" in a: print((root/"config.json").read_text())
 elif "ps" in a:
  if a[-1]=="postgres":
   if os.environ.get("FAIL_POSTGRES_PS")=="1": sys.exit(1)
   print("old-postgres")
  elif os.environ.get("NO_OLD_IDS")!="1": print("old-orchestrator\nold-postgres\nold-poc-runner-image\nold-worker")
 elif "up" in a and os.environ.get("FAIL_UP")=="1" and "--no-build" not in a: sys.exit(1)
 elif "run" in a and "tar" in a:
  # Stand-in for the one-off root container: map its mount back to the host path
  # and, as root would, read files whatever their mode says.
  import subprocess
  if os.environ.get("FAIL_FILES")=="1": sys.exit(2)
  host, inside = a[a.index("-v")+1].split(":")[:2]
  for path in pathlib.Path(host).rglob("*"):
   if path.is_file() and not os.access(path, os.R_OK): path.chmod(0o600)
  args=[host if x==inside else x for x in a[a.index("tar")+2:]]
  sys.exit(subprocess.run(["tar", *args]).returncode)
 elif "exec" in a:
  if "orchestrator" in a and os.environ.get("FAIL_API")=="1" and not (root/"api-failed").exists():
   (root/"api-failed").touch(); sys.exit(1)
  if "pg_dump" in a:
   if os.environ.get("FAIL_DUMP")=="1": sys.exit(1)
   print("SELECT 1;")
  elif "psql" in a:
   if os.environ.get("FAIL_PSQL")=="1" and a[-1]=="nidavellir": sys.exit(1)
   sql=sys.stdin.read()
   if "SELECT 1;" not in sql: sys.exit(3)
elif a[0]=="inspect":
 # Container "old-<service>[@<image>]": a replica of <service> running sha256:old-<image>.
 if a[1] in os.environ.get("UNINSPECTABLE","").split(","): sys.exit(1)
 name,_,image=a[1].removeprefix("old-").partition("@")
 labels={} if a[1] in os.environ.get("NO_LABEL","").split(",") else {"com.docker.compose.service":name}
 env=["NIDAVELLIR_POC_RUNNER_IMAGE="+os.environ.get("RUNNER","nidavellir/poc-runner:py311")] if name=="worker" else []
 print(json.dumps([{"Image":"sha256:old-"+(image or name),"Config":{"Image":"nidavellir/"+name+":latest","Labels":labels,"Env":env}}]))
elif a[:2]==["image","inspect"]:
 # UNRESOLVABLE models the containerd store: a rebuilt tag orphans the old image ID.
 if a[2] in os.environ.get("UNRESOLVABLE","").split(","): sys.exit(1)
 tags=root/"tags"
 if a[2].startswith("nidavellir-rollback") and a[2] not in (tags.read_text().splitlines() if tags.exists() else []): sys.exit(1)
 ident=a[2] if a[2].startswith("sha256:") else "sha256:now-"+a[2].replace("/","-").replace(":","-")
 print(json.dumps([{"RepoDigests":[],"Id":ident}]))
elif a[0] in ("tag","rmi") or a[:2]==["image","ls"]:
 tags=root/"tags"; known=tags.read_text().splitlines() if tags.exists() else []
 if a[0]=="tag":
  if a[2].split(":")[0].rsplit("/",1)[-1] in os.environ.get("FAIL_TAG","").split(","): sys.exit(1)
  known.append(a[2])
 elif a[0]=="rmi":
  if os.environ.get("FAIL_RMI")=="1" or "-f" in a or a[1] not in known: sys.exit(1)
  known.remove(a[1])
 else: print("\n".join(known))
 tags.write_text("".join(t+"\n" for t in known))
else: sys.exit(2)
'''


@unittest.skipUnless(shutil.which("docker"), "Compose CLI required (no daemon used)")
class DeploymentToolingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nidavellir-deploy-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "scripts").mkdir()
        for name in ("deploy.sh", "backup.sh", "deployment-common.sh", "deployment-state.py"):
            shutil.copy(ROOT / "scripts" / name, self.repo / "scripts" / name)
        for name in ("docker-compose.yml", "docker-compose.prod.yml", ".gitignore"):
            shutil.copy(ROOT / name, self.repo / name)
        self.env = os.environ | {"HOME": str(self.root / "home"), "FIXTURE_STATE": str(self.root)}
        self.env.pop("DATABASE_URL", None)
        # Compose prefers the process environment to --env-file, even when the
        # value is empty. tests/conftest.py blanks this key for the whole pytest
        # run, which hid the fixture's .env value and failed every compose call.
        self.env.pop("SECRETS_ENCRYPTION_KEY", None)
        (self.repo / ".env").write_text(
            "\n".join(f"{k}={SECRET}" for k in (
                "NIDAVELLIR_API_KEY", "WEBUI_PASSWORD", "SECRET_KEY", "POSTGRES_PASSWORD",
                "REDIS_PASSWORD",
            )) + "\nSECRETS_ENCRYPTION_KEY=1Lyp1COmA9ijy52VmSMGEO25u6INm-Slggk0cgcCP4o=\n"
            f"DATABASE_URL=postgresql+psycopg://nidavellir:{SECRET}@postgres:5432/nidavellir\n"
        )
        config = subprocess.check_output([
            "docker", "compose", "--env-file", str(self.repo / ".env"),
            "-f", str(self.repo / "docker-compose.yml"), "-f", str(self.repo / "docker-compose.prod.yml"),
            "--profile", "postgres", "--profile", "agent-gateway", "config", "--format", "json"
        ], env=self.env)
        (self.root / "config.json").write_bytes(config)
        binaries = self.root / "bin"
        binaries.mkdir()
        for name, content in (("docker", FAKE_DOCKER), ("make", "#!/bin/sh\nexit ${FAIL_GATE:-0}\n"), ("curl", "#!/bin/sh\nexit 0\n")):
            path = binaries / name
            path.write_text(content)
            path.chmod(0o755)
        self.env["PATH"] = str(binaries) + os.pathsep + self.env["PATH"]
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Deployment fixture")
        self.git("add", ".")
        self.git("commit", "-qm", "Previous release")
        self.previous = self.git("rev-parse", "HEAD").strip()
        (self.repo / "release-marker").write_text("throwaway target release\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Throwaway target")
        self.git("tag", "v-test")
        self.target = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "--detach", self.previous)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, env=self.env, stderr=subprocess.DEVNULL, text=True)

    def invoke(self, script, *args, **variables):
        return subprocess.run(["bash", f"scripts/{script}.sh", *args], cwd=self.repo,
                              env=self.env | variables, text=True, capture_output=True, timeout=30)

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]

    def receipts(self):
        return [json.loads(p.read_text()) for p in (self.repo / "deployments").glob("*.json")]

    def test_compose_exposure_and_limits(self):
        services = json.loads((self.root / "config.json").read_text())["services"]
        ports = {(n, p["host_ip"], p["published"], p["target"]) for n, s in services.items() for p in s.get("ports", [])}
        self.assertEqual(ports, {("webui", "127.0.0.1", "5000", 5000), ("orchestrator", "127.0.0.1", "8000", 8000), ("agent-gateway", "127.0.0.1", "9001", 9000)})
        for service in services.values():
            self.assertGreater(int(service["mem_limit"]), 0)
            self.assertEqual(service["logging"]["options"], {"max-file": "3", "max-size": "10m"})

    def test_dry_run_has_no_daemon_calls_or_mutations(self):
        r = self.invoke("deploy", "--dry-run", "v-test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"schema":"nidavellir-deployment/v1"', r.stdout)
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        self.assertTrue(all("config" in c for c in self.calls()))
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertFalse((self.repo / "deployments").exists())
        r = self.invoke("backup", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pg_dump", r.stdout)
        self.assertIn("createdb", r.stdout)
        self.assertFalse((self.root / "home").exists())

    def test_dirty_tree_aborts_even_dry_run(self):
        (self.repo / "untracked").touch()
        r = self.invoke("deploy", "--dry-run", "v-test")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Dirty tree", r.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_failed_upgrade_restores_previous_ref_database_and_images(self):
        r = self.invoke("deploy", "v-test", FAIL_UP="1")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        receipt = self.receipts()[0]
        self.assertEqual(receipt["status"], "rolled_back")
        self.assertEqual(receipt["sha"], self.target)
        self.assertEqual(receipt["previous_sha"], self.previous)
        self.assertTrue((Path(receipt["backup"]) / "complete").is_file())
        calls = self.calls()
        restart = next(c for c in calls if "up" in c and "--no-build" in c and "never" in c)
        overlay = json.loads(Path(restart[restart.index("up") - 1]).read_text())
        stamp = next((self.repo / "deployments").glob("*.json")).stem
        self.assertEqual(overlay["x-nidavellir-rollback"]["stamp"], stamp)
        for name, service in overlay["services"].items():
            self.assertEqual(service["image"], f"nidavellir-rollback/{name}:{stamp}")
            source = "nidavellir/poc-runner:py311" if name == "poc-runner-image" else f"sha256:old-{name}"
            self.assertIn(["tag", source, service["image"]], calls)
        self.assertEqual(overlay["services"]["worker"]["environment"]["NIDAVELLIR_POC_RUNNER_IMAGE"],
                         f"nidavellir-rollback/poc-runner-image:{stamp}")
        self.assertFalse(any(c[0] == "rmi" for c in calls))
        self.assertTrue(any("dropdb" in c and "nidavellir" == c[-1] for c in calls))
        self.assertNotIn(SECRET, r.stdout + r.stderr)

    def test_postgres_status_error_aborts_without_changing_stack(self):
        result = self.invoke("deploy", "v-test", FAIL_POSTGRES_PS="1", NO_OLD_IDS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unable to determine PostgreSQL status", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertFalse(any(any(op in call for op in ("build", "run", "exec", "up", "stop"))
                             for call in self.calls()))
        self.assertEqual(self.receipts()[0]["status"], "failed")

    def test_deploy_does_not_require_ripgrep(self):
        ripgrep = self.root / "bin" / "rg"
        ripgrep.write_text("#!/bin/sh\nexit 127\n")
        ripgrep.chmod(0o755)
        result = self.invoke("deploy", "v-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.receipts()[0]["status"], "success")
        self.assertTrue((Path(self.receipts()[0]["backup"]) / "complete").is_file())

    def test_success_and_repeat_are_clean_and_recorded(self):
        for _ in range(2):
            r = self.invoke("deploy", "v-test")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.target)
        self.assertEqual(len(self.receipts()), 2)
        self.assertTrue(all(r["status"] == "success" for r in self.receipts()))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_gate_failure_restarts_old_stack(self):
        r = self.invoke("deploy", "v-test", FAIL_GATE="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.receipts()[0]["status"], "rolled_back")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)

    def test_failed_dump_never_marks_complete(self):
        r = self.invoke("backup", FAIL_DUMP="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(list((self.root / "home").rglob("complete")), [])
        self.assertTrue(any("start" in c for c in self.calls()))

    def test_api_smoke_failure_rolls_back(self):
        r = self.invoke("deploy", "v-test", FAIL_API="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.receipts()[0]["status"], "rolled_back")

    def test_failed_destructive_restore_stays_offline(self):
        r = self.invoke("backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        backup = next((self.root / "home").rglob("complete")).parent
        count = len(self.calls())
        r = self.invoke("backup", "--restore", str(backup), FAIL_PSQL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("start" in c for c in self.calls()[count:]))

    def test_backup_reads_files_the_host_user_cannot(self):
        """Services write as root under data/; the 2026-11-11 deploy failed on 28 such files."""
        import tarfile

        private = self.repo / "data" / "http-transactions" / "arena"
        private.mkdir(parents=True)
        (private / "payload.json").write_text('{"written": "by a container"}')
        (private / "payload.json").chmod(0)
        if os.geteuid() != 0:  # what the old host-side tar did with this tree
            # (GNU tar skips reading when the archive is /dev/null, so use a real file.)
            old = subprocess.run(["tar", "-czf", str(self.root / "old.tar.gz"), "data"],
                                 cwd=self.repo, capture_output=True)
            self.assertNotEqual(old.returncode, 0)
        r = self.invoke("backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        backup = next((self.root / "home").rglob("complete")).parent
        with tarfile.open(backup / "files.tar.gz") as archive:
            names = archive.getnames()
        self.assertIn("data/http-transactions/arena/payload.json", names)
        self.assertIn(".env", names)
        # The archive was made inside the one-off container, from a read-only mount.
        archive_call = next(c for c in self.calls() if "run" in c and "tar" in c)
        self.assertIn(f"{self.repo}:/backup-src:ro", archive_call)
        self.assertIn("--no-deps", archive_call)
        self.assertEqual(archive_call[archive_call.index("--entrypoint") + 1:][:2],
                         ["tar", "orchestrator"])
        self.assertNotIn(SECRET, r.stdout + r.stderr)

        # Restore replaces the files through the same container.
        (private / "payload.json").chmod(0o600)
        (private / "payload.json").write_text("changed after the backup")
        count = len(self.calls())
        r = self.invoke("backup", "--restore", str(backup))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((private / "payload.json").read_text(), '{"written": "by a container"}')
        restore_call = next(c for c in self.calls()[count:] if "run" in c and "tar" in c)
        self.assertIn(f"{self.repo}:/backup-dst", restore_call)
        self.assertIn("-xzf", restore_call)

    def test_failed_file_archive_never_marks_complete(self):
        r = self.invoke("backup", FAIL_FILES="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(list((self.root / "home").rglob("complete")), [])
        self.assertTrue(any("start" in c for c in self.calls()))
        self.assertIn("File archive failed", r.stderr)

    def test_failed_file_restore_stays_offline(self):
        r = self.invoke("backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        backup = next((self.root / "home").rglob("complete")).parent
        count = len(self.calls())
        r = self.invoke("backup", "--restore", str(backup), FAIL_FILES="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("start" in c for c in self.calls()[count:]))

    def test_retention_preserves_incomplete_sets(self):
        base = self.root / "home/.local/share/nidavellir/backups"
        for index in range(16):
            path = base / f"20000101T0000{index:02d}-1"
            path.mkdir(parents=True)
            (path / "complete").touch()
        incomplete = base / "20000101T000000-2"
        incomplete.mkdir()
        r = self.invoke("backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(list(base.rglob("complete"))), 14)
        self.assertTrue(incomplete.is_dir())

    def state(self, *args, check=True, **variables):
        return subprocess.run(["python3", "scripts/deployment-state.py", *args], cwd=self.repo,
                              env=self.env | {"NIDAVELLIR_ROLLBACK_STAMP": STAMP} | variables,
                              text=True, capture_output=True, check=check, timeout=30)

    def tag_calls(self):
        return [c for c in self.calls() if c[0] == "tag"]

    def tags(self):
        path = self.root / "tags"
        return path.read_text().splitlines() if path.exists() else []

    def test_rollback_pins_runtime_runner_from_worker_env(self):
        """The one-shot initializer's own image is ignored; the worker's runner is pinned."""
        output = self.root / "images.json"
        self.state("snapshot", str(output), "old-orchestrator", "old-worker", "old-poc-runner-image",
                   RUNNER="registry.local/runner:v7", UNRESOLVABLE="sha256:old-poc-runner-image")
        overlay = json.loads(output.read_text())
        runner = f"nidavellir-rollback/poc-runner-image:{STAMP}"
        for name in ("worker", "orchestrator"):
            self.assertEqual(overlay["services"][name]["environment"]["NIDAVELLIR_POC_RUNNER_IMAGE"], runner)
        self.assertEqual(overlay["services"]["poc-runner-image"], {"image": runner, "pull_policy": "never"})
        self.assertIn(["tag", "registry.local/runner:v7", runner], self.tag_calls())
        self.assertFalse(any("sha256:old-poc-runner-image" in c for c in self.tag_calls()))
        self.assertEqual(overlay["x-nidavellir-rollback"]["services"]["poc-runner-image"],
                         {"source": "worker_runner", "reference": "registry.local/runner:v7", "tag": runner})
        # The worker's runner must resolve, whatever the initializer container runs.
        output.unlink()
        r = self.state("snapshot", str(output), "old-worker", "old-poc-runner-image", check=False,
                       NIDAVELLIR_ROLLBACK_STAMP="20261118T120001-42", UNRESOLVABLE="nidavellir/poc-runner:py311")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("poc-runner-image", r.stderr)
        self.assertFalse(output.exists())
        # An initializer without a worker gives no runner to keep: refuse.
        r = self.state("snapshot", str(output), "old-poc-runner-image", check=False,
                       NIDAVELLIR_ROLLBACK_STAMP="20261118T120002-42")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no worker container", r.stderr)

    def test_snapshot_pins_exact_image_ids(self):
        output = self.root / "images.json"
        self.state("snapshot", str(output), "old-orchestrator", "old-worker")
        overlay = json.loads(output.read_text())
        for name in ("orchestrator", "worker"):
            self.assertEqual(overlay["services"][name], {
                "image": f"nidavellir-rollback/{name}:{STAMP}", "pull_policy": "never",
                "environment": {"NIDAVELLIR_POC_RUNNER_IMAGE": f"nidavellir-rollback/poc-runner-image:{STAMP}"}})
            self.assertEqual(overlay["x-nidavellir-rollback"]["services"][name], {
                "source": "image_id", "reference": f"sha256:old-{name}",
                "tag": f"nidavellir-rollback/{name}:{STAMP}"})
        self.assertNotIn("sha256:", json.dumps(overlay["services"]))
        self.assertEqual(overlay["x-nidavellir-rollback"]["stamp"], STAMP)

    def test_identity_mismatch_needs_explicit_opt_in(self):
        """2026-11-18: webui ran an image whose record was gone; its tag named another image."""
        output = self.root / "images.json"
        ids = ("old-orchestrator", "old-webui", "old-worker")
        r = self.state("snapshot", str(output), *ids, check=False, UNRESOLVABLE="sha256:old-webui")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("service webui", r.stderr)
        self.assertIn("recreate webui", r.stderr)
        self.assertIn("NIDAVELLIR_ROLLBACK_ACCEPT_TAG=webui", r.stderr)
        self.assertEqual(self.tag_calls(), [])
        self.assertFalse(output.exists())
        # With the opt-in: accepted, recorded and warned about.
        r = self.state("snapshot", str(output), *ids, UNRESOLVABLE="sha256:old-webui",
                       NIDAVELLIR_ROLLBACK_ACCEPT_TAG="webui")
        overlay = json.loads(output.read_text())
        tag = f"nidavellir-rollback/webui:{STAMP}"
        self.assertEqual(overlay["services"]["webui"], {"image": tag, "pull_policy": "never"})
        self.assertEqual(overlay["x-nidavellir-rollback"]["services"]["webui"], {
            "source": "accepted_tag", "reference": "nidavellir/webui:latest",
            "container_image": "sha256:old-webui",
            "resolved_image_id": "sha256:now-nidavellir-webui-latest", "tag": tag})
        self.assertIn(["tag", "nidavellir/webui:latest", tag], self.tag_calls())
        self.assertEqual(overlay["x-nidavellir-rollback"]["services"]["worker"]["source"], "image_id")
        self.assertIn("Warning", r.stderr)
        self.assertIn("webui", r.stderr)
        # The opt-in never rescues a tag that does not resolve either.
        r = self.state("snapshot", str(self.root / "other.json"), *ids, check=False,
                       NIDAVELLIR_ROLLBACK_STAMP="20261118T120001-42",
                       UNRESOLVABLE="sha256:old-webui,nidavellir/webui:latest",
                       NIDAVELLIR_ROLLBACK_ACCEPT_TAG="webui")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("service webui", r.stderr)

    def test_snapshot_refuses_stamp_collision(self):
        existing = f"nidavellir-rollback/beat:{STAMP}"
        (self.root / "tags").write_text(existing + "\n")
        output = self.root / "images.json"
        r = self.state("snapshot", str(output), "old-orchestrator", "old-worker", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exist", r.stderr)
        self.assertEqual(self.tag_calls(), [])
        self.assertEqual(self.tags(), [existing])
        self.assertFalse(output.exists())

    def test_snapshot_tag_failure_removes_tags_of_this_run(self):
        unrelated = "nidavellir-rollback/worker:20261101T000000-1"
        (self.root / "tags").write_text(unrelated + "\n")
        output = self.root / "images.json"
        r = self.state("snapshot", str(output), "old-orchestrator", "old-beat", "old-worker",
                       check=False, FAIL_TAG="worker")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("service worker", r.stderr)
        self.assertEqual(len(self.tag_calls()), 3)  # orchestrator and beat made, worker failed
        removed = [c for c in self.calls() if c[0] == "rmi"]
        self.assertEqual(sorted(c[1] for c in removed), [f"nidavellir-rollback/beat:{STAMP}",
                                                         f"nidavellir-rollback/orchestrator:{STAMP}"])
        self.assertTrue(all(len(c) == 2 for c in removed))  # never -f
        self.assertEqual(self.tags(), [unrelated])
        self.assertFalse(output.exists())
        # A cleanup that fails is reported, never forced.
        r = self.state("snapshot", str(output), "old-orchestrator", "old-worker", check=False,
                       NIDAVELLIR_ROLLBACK_STAMP="20261118T120001-42", FAIL_TAG="worker", FAIL_RMI="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not remove", r.stderr)
        self.assertFalse(output.exists())

    def test_snapshot_refuses_label_less_and_divergent_replicas(self):
        output = self.root / "images.json"
        r = self.state("snapshot", str(output), "old-worker", "old-stray", check=False, NO_LABEL="old-stray")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("old-stray", r.stderr)
        self.assertIn("com.docker.compose.service", r.stderr)
        r = self.state("snapshot", str(output), "old-worker", "old-worker@other", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("service worker", r.stderr)
        self.assertEqual(self.tag_calls(), [])
        self.assertFalse(output.exists())
        # Identical replicas are one service with one tag.
        self.state("snapshot", str(output), "old-worker", "old-worker@worker")
        overlay = json.loads(output.read_text())
        self.assertEqual(overlay["services"]["worker"]["image"], f"nidavellir-rollback/worker:{STAMP}")
        self.assertEqual(sum(c[2] == f"nidavellir-rollback/worker:{STAMP}" for c in self.tag_calls()), 1)

    def test_snapshot_fails_closed_and_deploy_touches_nothing(self):
        r = self.invoke("deploy", "v-test", UNRESOLVABLE="sha256:old-worker,nidavellir/worker:latest")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("service worker", r.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertFalse(any(c[0] in ("tag", "rmi") or any(op in c for op in ("build", "run", "exec", "up", "stop"))
                             for c in self.calls()))
        self.assertFalse((self.repo / "deployments").exists())
        self.assertFalse((self.root / "home").exists())  # no backup was taken either
        # Same for the worker's runner when no initializer container exists.
        r = self.state("snapshot", str(self.root / "images.json"), "old-worker", check=False,
                       UNRESOLVABLE="nidavellir/poc-runner:py311")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("poc-runner-image", r.stderr)
        self.assertEqual(self.tag_calls(), [])
        self.assertFalse((self.root / "images.json").exists())

    def test_manifest_records_unresolvable_image_instead_of_raising(self):
        output = self.root / "receipt.json"
        self.state("manifest", str(output), "sha", "prev", "success", "", "old-orchestrator",
                   "old-poc-runner-image", "old-webui", "gone",
                   UNRESOLVABLE="sha256:old-poc-runner-image,sha256:old-webui,nidavellir/webui:latest",
                   UNINSPECTABLE="gone")
        receipt = json.loads(output.read_text())
        images = receipt["images"]
        self.assertEqual(images["orchestrator"], {"image_id": "sha256:old-orchestrator", "repo_digests": [],
                                                  "image_resolvable": True})
        self.assertEqual(images["poc-runner-image"], {
            "image_id": "sha256:old-poc-runner-image", "config_image": "nidavellir/poc-runner-image:latest",
            "resolved_image_id": "sha256:now-nidavellir-poc-runner-image-latest", "repo_digests": [],
            "image_resolvable": False})
        self.assertIsNone(images["webui"]["resolved_image_id"])
        self.assertFalse(images["webui"]["image_resolvable"])
        self.assertEqual(receipt["uninspectable_containers"], ["gone"])
        # End to end: the 2026-11-18 deploy succeeded but wrote no receipt.
        r = self.invoke("deploy", "v-test", UNRESOLVABLE="sha256:old-poc-runner-image")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        receipt = self.receipts()[0]
        self.assertEqual(receipt["status"], "success")
        self.assertFalse(receipt["images"]["poc-runner-image"]["image_resolvable"])

    def test_retention_keeps_newest_three_stamps_only(self):
        stamps = ["20261101T000000-9", "20261102T000000-1", "20261102T000000-10",
                  "20261103T000000-5", "20261104T000000-7"]
        rollback = [f"nidavellir-rollback/{svc}:{s}" for s in stamps for svc in ("worker", "webui")]
        others = ["nidavellir/worker:latest", "postgres:16-alpine",
                  "nidavellir-rollback-x/worker:20200101T000000-1", "nidavellir-rollback/worker:manual"]
        (self.root / "tags").write_text("".join(t + "\n" for t in rollback + others))
        self.state("prune-rollback", "3")
        kept = [t for t in rollback if t.rsplit(":", 1)[1] in stamps[2:]]
        self.assertEqual(sorted((self.root / "tags").read_text().splitlines()), sorted(kept + others))
        removed = [c for c in self.calls() if c[0] == "rmi"]
        self.assertEqual(sorted(c[1] for c in removed), sorted(set(rollback) - set(kept)))
        self.assertTrue(all(len(c) == 2 for c in removed))  # never -f
        self.assertFalse(any("prune" in c for c in self.calls()))

    def test_retention_runs_after_success_only_and_never_fails_deploy(self):
        old = [f"nidavellir-rollback/worker:2000010{d}T000000-1" for d in range(1, 5)]
        (self.root / "tags").write_text("".join(t + "\n" for t in old))
        r = self.invoke("deploy", "v-test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        remaining = set((self.root / "tags").read_text().splitlines())
        self.assertEqual(remaining & set(old), set(old[2:]))
        stamp = next((self.repo / "deployments").glob("*.json")).stem
        self.assertIn(f"nidavellir-rollback/orchestrator:{stamp}", remaining)
        # A retention failure is logged and changes neither status nor exit code.
        r = self.invoke("deploy", "v-test", FAIL_RMI="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("retention failed", r.stderr)
        self.assertEqual([x["status"] for x in self.receipts()], ["success", "success"])
        # A failed deploy never prunes.
        count = len(self.calls())
        r = self.invoke("deploy", "v-test", FAIL_GATE="1")
        self.assertNotEqual(r.returncode, 0)
        # (`image ls` now also runs in the snapshot's collision preflight; one per deploy.)
        self.assertFalse(any(c[0] == "rmi" for c in self.calls()[count:]))
        self.assertEqual(sum(c[:2] == ["image", "ls"] for c in self.calls()[count:]), 1)

    def test_corrupt_backup_does_not_drop_current_database(self):
        r = self.invoke("backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        backup = next((self.root / "home").rglob("complete")).parent
        (backup / "database.sql.gz").write_bytes(b"not a gzip dump")
        count = len(self.calls())
        r = self.invoke("backup", "--restore", str(backup))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("dropdb" in c and c[-1] == "nidavellir" for c in self.calls()[count:]))

    def test_runner_pin_without_initializer_container(self):
        output = self.root / "images.json"
        self.state("snapshot", str(output), "old-worker")
        overlay = json.loads(output.read_text())
        runner = f"nidavellir-rollback/poc-runner-image:{STAMP}"
        self.assertEqual(overlay["services"]["worker"]["environment"]["NIDAVELLIR_POC_RUNNER_IMAGE"], runner)
        self.assertEqual(overlay["services"]["poc-runner-image"]["image"], runner)
        self.assertIn(["tag", "nidavellir/poc-runner:py311", runner], self.tag_calls())
        self.assertEqual(overlay["x-nidavellir-rollback"]["services"]["poc-runner-image"]["source"],
                         "worker_runner")
