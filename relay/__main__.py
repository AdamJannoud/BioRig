"""python -m relay: load config (fail-closed), assert the signer's role on chain, open the store, start the single
worker and serve the HTTP surface.

    python -m relay            serve
    python -m relay --check    boot assertion only: print the health payload and exit 0, or exit non-zero

Exit codes: 2 the environment is unusable (ConfigError), 3 the boot assertion failed (wrong chain, no
VERIFIER_ROLE, chain unreachable), 4 the store refuses (another chain's database).
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys

from .config import ConfigError, load_config
from .store import Store, StoreError


def main(argv: list[str] | None = None, env=None, broadcaster_factory=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m relay", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="run the boot assertion, print health, exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"relay: refusing to start: {exc}", file=sys.stderr)
        return 2

    from .service import BootError, Relay, boot, make_server

    if broadcaster_factory is None:
        from .broadcaster import ChainBroadcaster as broadcaster_factory
    broadcaster = broadcaster_factory(config)
    try:
        boot_facts = boot(config, broadcaster)
    except BootError as exc:
        print(f"relay: refusing to start: {exc}", file=sys.stderr)
        return 3

    try:
        store = Store(config.db_path)
        store.bind_chain(config.chain_id)
    except StoreError as exc:
        print(f"relay: refusing to start: {exc}", file=sys.stderr)
        return 4

    relay = Relay(config, store, broadcaster)
    if args.check:
        print(json.dumps({**boot_facts, "health": relay.health_payload()}, indent=2))
        return 0

    from .machine import Worker

    worker = Worker(relay.machine, config.retry.idle_poll_s)
    server = make_server(relay, config.host, config.port)

    def _stop(*_):
        worker.stop()
        server.shutdown()

    signal.signal(signal.SIGTERM, lambda *a: __import__("threading").Thread(target=_stop).start())
    worker.start()
    print(f"relay: chain {config.chain_id}, signer {broadcaster.signer}, dry_run={config.dry_run}, "
          f"paused={relay.machine.paused}, listening on http://{config.host}:{config.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        worker.join(timeout=10)
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
