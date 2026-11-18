#!/usr/bin/env python3
"""Private deployment receipts: immutable local image IDs and registry digests."""
import datetime
import json
import pathlib
import subprocess
import sys


def docker(*args):
    return json.loads(subprocess.check_output(["docker", *args], stderr=subprocess.DEVNULL))


def resolve(reference):
    """Return the image a reference resolves to now, or None."""
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
    services = {}
    runner = None
    worker_runner = "nidavellir/poc-runner:py311"
    for cid in ids:
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


def main(argv):
    if not argv:
        sys.exit("Unknown deployment state operation")
    mode, *args = argv
    if mode == "snapshot" and args:
        snapshot(args[0], args[1:])
    elif mode == "manifest" and len(args) >= 5:
        manifest(args[0], *args[1:5], args[5:])
    else:
        sys.exit("Unknown deployment state operation")


if __name__ == "__main__":
    main(sys.argv[1:])
