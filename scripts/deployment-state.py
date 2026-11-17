#!/usr/bin/env python3
"""Private deployment receipts: immutable local image IDs and registry digests."""
import datetime
import json
import pathlib
import subprocess
import sys


def docker(*args):
    return json.loads(subprocess.check_output(["docker", *args], stderr=subprocess.DEVNULL))


mode, destination, *args = sys.argv[1:]
if mode == "snapshot":
    services = {}
    runner = None
    worker_runner = "nidavellir/poc-runner:py311"
    for cid in args:
        c = docker("inspect", cid)[0]
        name = c["Config"]["Labels"]["com.docker.compose.service"]
        image = c["Image"]
        services[name] = {"image": image, "pull_policy": "never"}
        if name == "worker":
            for value in c["Config"].get("Env", []):
                if value.startswith("NIDAVELLIR_POC_RUNNER_IMAGE="):
                    worker_runner = value.split("=", 1)[1]
        if name == "poc-runner-image":
            runner = image
    if runner is None and "worker" in services:
        runner = docker("image", "inspect", worker_runner)[0]["Id"]
    if runner:
        for name in ("worker", "orchestrator"):
            if name in services:
                services[name]["environment"] = {"NIDAVELLIR_POC_RUNNER_IMAGE": runner}
    pathlib.Path(destination).write_text(json.dumps({"services": services}, indent=2) + "\n")
elif mode == "manifest":
    sha, previous, status, backup, *ids = args
    images = {}
    for cid in ids:
        c = docker("inspect", cid)[0]
        image = docker("image", "inspect", c["Image"])[0]
        images[c["Config"]["Labels"]["com.docker.compose.service"]] = {
            "image_id": c["Image"], "repo_digests": image.get("RepoDigests") or []
        }
    record = {
        "schema": "nidavellir-deployment/v1",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sha": sha, "previous_sha": previous, "status": status,
        "backup": backup or None, "images": images,
    }
    path = pathlib.Path(destination)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)
else:
    sys.exit("Unknown deployment state operation")
