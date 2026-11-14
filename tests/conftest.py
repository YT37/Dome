"""Shared test setup.

Every test runs on Avishek's scenario stubs (DOME_STUBS=1), whatever the shell or .env
says, so the suite passes on machines with and without data keys. Tests marked
`@pytest.mark.real` run Yug's real data_tools instead (DOME_STUBS=0) and skip when the
CoStar kit, keys or caches are missing.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "real: uses real CoStar/Matterport/Vexcel data (skips if unavailable)")


@pytest.fixture(autouse=True)
def _stub_mode(request, monkeypatch):
    monkeypatch.setenv("DOME_STUBS", "0" if request.node.get_closest_marker("real") else "1")
