"""Fixed runner entrypoint with a worker-visible collection rendezvous."""
import os
import subprocess
import time

deadline = time.monotonic() + 15
while not os.path.isfile("/workspace/.ready"):
    if time.monotonic() >= deadline:
        raise SystemExit("worker did not supply PoC input")
    time.sleep(0.02)
result = subprocess.run(  # nosec B603 - fixed trusted interpreter and path
    ["/usr/local/bin/python3", "-E", "/workspace/main.py"], check=False
)
with open("/workspace/.nidavellir-exit.tmp", "w", encoding="ascii") as handle:
    handle.write(str(result.returncode))
os.replace("/workspace/.nidavellir-exit.tmp", "/workspace/.nidavellir-exit")
# Keep tmpfs mounted until the worker has collected artifacts and logs. The
# worker then kills this parent and records the child exit code above.
while True:
    time.sleep(60)
