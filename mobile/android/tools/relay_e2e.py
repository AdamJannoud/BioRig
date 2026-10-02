"""Serve the real relay over HTTP and drive it with :core's SubmissionQueue.

    .venv/bin/python mobile/android/tools/relay_e2e.py

relay.service.Relay is constructed exactly as relay/tests/conftest.py does it: the relay suite's FakeBroadcaster
stands in for the chain and its TEST_KEY (a scalar that is a key to nothing) satisfies the config loader, so nothing
is signed and no network is touched. Limits are the relay's defaults. The store lives in a throwaway directory under
/var/tmp. Exit status is the Kotlin driver's.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ANDROID = Path(__file__).resolve().parent.parent
REPO = ANDROID.parent.parent
sys.path.insert(0, str(REPO))

from relay.config import load_config  # noqa: E402
from relay.service import Relay, make_server  # noqa: E402
from relay.store import Store  # noqa: E402
from relay.tests.conftest import FakeBroadcaster, base_env  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="biorig-e2e-") as tmp:
        config = load_config(base_env(Path(tmp)))
        store = Store(config.db_path)
        store.bind_chain(config.chain_id)
        relay = Relay(config, store, FakeBroadcaster())
        server = make_server(relay, "127.0.0.1", 0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"relay.service.Relay serving on http://127.0.0.1:{port} (FakeBroadcaster, default limits)", flush=True)
        try:
            return subprocess.run(["./gradlew", "-q", "--console=plain", ":core:relayE2e",
                                   f"-Prelay=http://127.0.0.1:{port}"], cwd=ANDROID).returncode
        finally:
            server.shutdown()
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
