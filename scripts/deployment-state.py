#!/usr/bin/env python3
"""Private deployment receipts and durable rollback image references.

With Docker's containerd image store, rebuilding a tag can make the previous
image ID unresolvable: only a tag keeps an image alive. The snapshot therefore
pins ``nidavellir-rollback/<service>:<stamp>`` tags, never raw image IDs.

The snapshot pins exactly the image each container runs, or refuses. A service
tag may name a different image from the running one, so it is used only when
the operator opts in through ``NIDAVELLIR_ROLLBACK_ACCEPT_TAG``.
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
ROLLBACK_REF = re.compile(rf"{ROLLBACK_REPO}/({SERVICE.pattern}):({STAMP.pattern})")
RUNNER_SERVICE = "poc-runner-image"
RUNNER_ENV = "NIDAVELLIR_POC_RUNNER_IMAGE"
RUNNER_DEFAULT = "nidavellir/poc-runner:py311"  # scenario-orchestrator config.py default
ACCEPT_TAG = "NIDAVELLIR_ROLLBACK_ACCEPT_TAG"
SERVICE_LABEL = "com.docker.compose.service"


class Refused(Exception):
    pass


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


def service_label(container):
    labels = (container.get("Config") or {}).get("Labels") or {}
    return labels.get(SERVICE_LABEL)


def rollback_reference(reference):
    """(service, stamp) for an exact nidavellir-rollback/<service>:<stamp> reference, else None."""
    match = ROLLBACK_REF.fullmatch(reference.removeprefix("docker.io/"))
    return match.groups() if match else None


def list_rollback_tags():
    listing = subprocess.check_output(
        ["docker", "image", "ls", "--filter", f"reference={ROLLBACK_REPO}/*",
         "--format", "{{.Repository}}:{{.Tag}}"], text=True, stderr=subprocess.DEVNULL)
    return [line.strip() for line in listing.splitlines() if rollback_reference(line.strip())]


def runner_reference(container):
    for value in (container.get("Config") or {}).get("Env") or []:
        if value.startswith(RUNNER_ENV + "="):
            return value.split("=", 1)[1]
    return RUNNER_DEFAULT


def choose(name, container, accepted):
    """Exact image of a running service, or the opted-in tag; never a silent fallback."""
    image_id = container.get("Image")
    if resolve(image_id):
        return {"source": "image_id", "reference": image_id}
    config_image = (container.get("Config") or {}).get("Image")
    if name in accepted:
        current = resolve(config_image)
        if current is None:
            raise Refused(f"service {name}: neither its image {image_id!r} nor its tag "
                          f"{config_image!r} resolves")
        return {"source": "accepted_tag", "reference": config_image,
                "container_image": image_id, "resolved_image_id": current.get("Id")}
    raise Refused(
        f"service {name}: its running image {image_id!r} no longer resolves, and its tag "
        f"{config_image!r} may name a different image. Either recreate {name} from its "
        f"current tag before deploying, or set {ACCEPT_TAG}={name} to knowingly roll "
        f"{name} back to the image {config_image!r} names now")


def plan(ids, accepted):
    """Resolve every reference before anything is tagged."""
    chosen, runners, initializer = {}, set(), False
    for cid in ids:
        try:
            c = docker("inspect", cid)[0]
        except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
            raise Refused(f"cannot inspect container {cid}") from None
        name = service_label(c)
        if not name:
            raise Refused(f"container {cid} has no {SERVICE_LABEL} label")
        if not SERVICE.fullmatch(name):
            raise Refused(f"invalid service name {name!r} (container {cid})")
        if name == RUNNER_SERVICE:
            initializer = True
            continue  # one-shot initializer: its rollback image is the worker's runner
        if name == "worker":
            runners.add(runner_reference(c))
        choice = choose(name, c, accepted)
        previous = chosen.get(name)
        if previous and previous["reference"] != choice["reference"]:
            raise Refused(f"service {name} has containers on different images "
                          f"({previous['reference']!r}, {choice['reference']!r})")
        chosen[name] = choice
    if len(runners) > 1:
        raise Refused(f"worker containers use different {RUNNER_ENV} values: {sorted(runners)}")
    if runners:
        runner = runners.pop()
        if not resolve(runner):
            raise Refused(f"service {RUNNER_SERVICE}: the worker's runner {runner!r} does not resolve")
        chosen[RUNNER_SERVICE] = {"source": "worker_runner", "reference": runner}
    elif initializer:
        raise Refused(f"service {RUNNER_SERVICE}: no worker container names the runner to keep")
    return chosen


def tag_atomically(chosen, stamp):
    """Create every rollback tag of this stamp, or none of them."""
    try:
        existing = [t for t in list_rollback_tags() if rollback_reference(t)[1] == stamp]
    except (subprocess.CalledProcessError, OSError):
        raise Refused("cannot list existing rollback tags") from None
    existing += [f"{ROLLBACK_REPO}/{name}:{stamp}" for name in chosen
                 if resolve(f"{ROLLBACK_REPO}/{name}:{stamp}")]
    if existing:
        raise Refused(f"rollback tags for stamp {stamp} already exist: {sorted(set(existing))}")
    created = []
    for name, choice in chosen.items():
        tag = f"{ROLLBACK_REPO}/{name}:{stamp}"
        try:
            subprocess.run(["docker", "tag", choice["reference"], tag], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, OSError):
            leftover = [t for t in created if subprocess.run(
                ["docker", "rmi", t], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode]  # never -f
            detail = f"; could not remove {leftover}" if leftover else ""
            raise Refused(f"cannot tag {choice['reference']} as {tag} (service {name})"
                          f"{detail}") from None
        created.append(tag)
        choice["tag"] = tag


def snapshot(destination, ids):
    stamp = os.environ.get("NIDAVELLIR_ROLLBACK_STAMP") or (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    )
    if not STAMP.fullmatch(stamp):
        sys.exit(f"Invalid rollback stamp: {stamp!r}")
    accepted = {s.strip() for s in os.environ.get(ACCEPT_TAG, "").split(",") if s.strip()}
    try:
        chosen = plan(ids, accepted)
        tag_atomically(chosen, stamp)
    except Refused as error:
        sys.exit(f"Rollback snapshot refused: {error}")
    for name in sorted(accepted - {n for n, c in chosen.items() if c["source"] == "accepted_tag"}):
        print(f"Warning: {ACCEPT_TAG} names {name!r}, which needed no opt-in", file=sys.stderr)
    services = {}
    for name, choice in chosen.items():
        services[name] = {"image": choice["tag"], "pull_policy": "never"}
        if choice["source"] == "accepted_tag":
            print(f"Warning: rollback for {name} accepts tag {choice['reference']} "
                  f"({choice['resolved_image_id']}), not its running image "
                  f"{choice['container_image']}", file=sys.stderr)
    if RUNNER_SERVICE in chosen:
        for name in ("worker", "orchestrator"):
            if name in services:
                services[name]["environment"] = {RUNNER_ENV: chosen[RUNNER_SERVICE]["tag"]}
    overlay = {"services": services,
               "x-nidavellir-rollback": {"stamp": stamp, "services": chosen}}
    pathlib.Path(destination).write_text(json.dumps(overlay, indent=2) + "\n")


def manifest(destination, sha, previous, status, backup, ids):
    """Write the receipt; an unresolvable image is recorded, never fatal.

    The first container of a service is kept under ``images``; later ones go to
    ``duplicates`` and containers without a compose service label to
    ``unlabelled_containers``. Nothing is overwritten.
    """
    images, uninspectable, duplicates, unlabelled = {}, [], {}, []
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
        name = service_label(c)
        if not name:
            unlabelled.append({"container": cid, **entry})
        elif name in images:
            duplicates.setdefault(name, []).append({"container": cid, **entry})
        else:
            images[name] = entry
    record = {
        "schema": "nidavellir-deployment/v1",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sha": sha, "previous_sha": previous, "status": status,
        "backup": backup or None, "images": images,
    }
    if uninspectable:
        record["uninspectable_containers"] = uninspectable
    if duplicates:
        record["duplicates"] = duplicates
    if unlabelled:
        record["unlabelled_containers"] = unlabelled
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
