"""`--chain-id N` (repeatable) narrows every chain-parameterised test to those chains; the default is every chain
in dashboard/chains.json, so a plain `pytest dashboard` proves both."""
from dashboard.config import CHAINS


def pytest_addoption(parser):
    parser.addoption("--chain-id", action="append", type=int, default=None,
                     help="run the chain-parameterised dashboard tests against this chain only")


def pytest_generate_tests(metafunc):
    if "chain_id" in metafunc.fixturenames:
        wanted = metafunc.config.getoption("chain_id") or sorted(CHAINS)
        unknown = [c for c in wanted if c not in CHAINS]
        if unknown:
            raise ValueError(f"--chain-id {unknown} is not in dashboard/chains.json ({sorted(CHAINS)})")
        metafunc.parametrize("chain_id", wanted, ids=[f"chain{c}" for c in wanted])
