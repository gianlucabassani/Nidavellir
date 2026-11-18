#!/usr/bin/env python3
"""Private deployment receipts and durable rollback image references.

With Docker's containerd image store, rebuilding a tag can make the previous
image ID unresolvable: only a tag keeps an image alive. The snapshot therefore
pins ``nidavellir-rollback/<service>:<stamp>`` tags, never raw image IDs.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

ROLLBACK_REPO = "nidavellir-rollback"
STAMP = re.compile(r"\d{8}T\d{6}-\d+")
SERVICE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")
RUNNER_SERVICE = "poc-runner-image"


def docker(*args):
    return json.loads(subprocess.check_output(["docker", *args], stderr=subprocess.DEVNULL))


def resolve(reference):
    """Return the image a reference resolves to now (inspect record), or None."""
    if not reference:
        return None
    try:
        return docker("image", "inspect", reference)[0]
    except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
        return None


def service_name(container, fallback):
    labels = (container.get("Config") or {}).get("Labels") or {}
    return labels.get("com.docker.compose.service") or fallback


def snapshot(destination, ids):
    stamp = os.environ.get("NIDAVELLIR_ROLLBACK_STAMP") or (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    )
    if not STAMP.fullmatch(stamp):
        sys.exit(f"Invalid rollback stamp: {stamp!r}")
    # Resolve every reference before tagging anything: fail closed, touch nothing.
    chosen = {}
    worker_runner = "nidavellir/poc-runner:py311"
    for cid in ids:
        try:
            c = docker("inspect", cid)[0]
        except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
            sys.exit(f"Rollback snapshot refused: cannot inspect container {cid}")
        name = service_name(c, cid)
        if not SERVICE.fullmatch(name):
            sys.exit(f"Rollback snapshot refused: invalid service name {name!r}")
        config_image = (c.get("Config") or {}).get("Image")
        if resolve(c.get("Image")):
            chosen[name] = ("image_id", c["Image"])
        elif resolve(config_image):
            chosen[name] = ("config_image", config_image)
        else:
            sys.exit(f"Rollback snapshot refused: no resolvable image for service {name} "
                     f"(image ID {c.get('Image')!r}, config image {config_image!r})")
        if name == "worker":
            for value in (c.get("Config") or {}).get("Env") or []:
                if value.startswith("NIDAVELLIR_POC_RUNNER_IMAGE="):
                    worker_runner = value.split("=", 1)[1]
    if RUNNER_SERVICE not in chosen and "worker" in chosen:
        # No initializer container: pin what the worker actually runs PoCs with.
        if not resolve(worker_runner):
            sys.exit("Rollback snapshot refused: no resolvable image for service "
                     f"{RUNNER_SERVICE} (worker runner {worker_runner!r})")
        chosen[RUNNER_SERVICE] = ("worker_runner", worker_runner)

    services, record = {}, {}
    for name, (source, reference) in chosen.items():
        tag = f"{ROLLBACK_REPO}/{name}:{stamp}"
        try:
            subprocess.run(["docker", "tag", reference, tag], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, OSError):
            sys.exit(f"Rollback snapshot refused: cannot tag {reference} as {tag} (service {name})")
        record[name] = {"source": source, "reference": reference, "tag": tag}
        if source == "worker_runner":
            continue  # not a running service; only pinned through the environment
        services[name] = {"image": tag, "pull_policy": "never"}
        if source != "image_id":
            print(f"Rollback image for {name}: container image ID did not resolve; "
                  f"tagged {source} {reference}", file=sys.stderr)
    if RUNNER_SERVICE in record:
        for name in ("worker", "orchestrator"):
            if name in services:
                services[name]["environment"] = {
                    "NIDAVELLIR_POC_RUNNER_IMAGE": record[RUNNER_SERVICE]["tag"]}
    overlay = {"services": services,
               "x-nidavellir-rollback": {"stamp": stamp, "services": record}}
    pathlib.Path(destination).write_text(json.dumps(overlay, indent=2) + "\n")


def manifest(destination, sha, previous, status, backup, ids):
    """Write the receipt; an unresolvable image is recorded, never fatal."""
    images, uninspectable = {}, []
    for cid in ids:
        try:
            c = docker("inspect", cid)[0]
        except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
            uninspectable.append(cid)
            continue
        image = resolve(c.get("Image"))
        if image is not None:
            entry = {"image_id": c.get("Image"), "repo_digests": image.get("RepoDigests") or [],
                     "image_resolvable": True}
        else:
            config_image = (c.get("Config") or {}).get("Image")
            current = resolve(config_image) or {}
            entry = {"image_id": c.get("Image"), "config_image": config_image,
                     "resolved_image_id": current.get("Id"),
                     "repo_digests": current.get("RepoDigests") or [],
                     "image_resolvable": False}
        images[service_name(c, cid)] = entry
    record = {
        "schema": "nidavellir-deployment/v1",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sha": sha, "previous_sha": previous, "status": status,
        "backup": backup or None, "images": images,
    }
    if uninspectable:
        record["uninspectable_containers"] = uninspectable
    path = pathlib.Path(destination)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


def stamp_key(stamp):
    moment, pid = stamp.split("-")
    return moment, int(pid)


def prune_rollback(keep):
    """Untag rollback references outside the newest ``keep`` deploy stamps."""
    listing = subprocess.check_output(
        ["docker", "image", "ls", "--filter", f"reference={ROLLBACK_REPO}/*",
         "--format", "{{.Repository}}:{{.Tag}}"], text=True)
    tags = {}
    for line in listing.splitlines():
        reference = line.strip()
        repository, _, tag = reference.rpartition(":")
        if repository.removeprefix("docker.io/").split("/")[0] != ROLLBACK_REPO:
            continue  # never touch other repositories, whatever the filter returned
        if STAMP.fullmatch(tag):
            tags.setdefault(tag, set()).add(reference)
    stale = sorted(tags, key=stamp_key, reverse=True)[keep:]
    failed = False
    for stamp in stale:
        for reference in sorted(tags[stamp]):
            # rmi of a repo:tag removes the tag and any image left unused; never -f or prune.
            if subprocess.run(["docker", "rmi", reference], stdout=subprocess.DEVNULL).returncode:
                print(f"Rollback retention: could not remove {reference}", file=sys.stderr)
                failed = True
            else:
                print(f"Rollback retention: removed {reference}")
    return 1 if failed else 0


def main(argv):
    if not argv:
        sys.exit("Unknown deployment state operation")
    mode, *args = argv
    if mode == "snapshot" and args:
        snapshot(args[0], args[1:])
    elif mode == "manifest" and len(args) >= 5:
        manifest(args[0], *args[1:5], args[5:])
    elif mode == "prune-rollback" and len(args) == 1 and args[0].isdigit() and int(args[0]) >= 1:
        sys.exit(prune_rollback(int(args[0])))
    else:
        sys.exit("Unknown deployment state operation")


if __name__ == "__main__":
    main(sys.argv[1:])
