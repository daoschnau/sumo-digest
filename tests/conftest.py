from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read


@pytest.fixture(scope="session")
def sources_config() -> dict:
    path = Path(__file__).parent.parent / "config" / "sources.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))
