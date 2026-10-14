"""Shared test setup: generate one small synthetic dataset for all tests."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Let the tests import config.py and generate_data.py from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import generate_data  # noqa: E402

TEST_APPOINTMENTS = 2000
TEST_SEED = 7


@pytest.fixture(scope="session")
def output_dir(tmp_path_factory):
    """Run the command-line script once into a temporary folder."""
    folder = tmp_path_factory.mktemp("raw")
    generate_data.main(["--appointments", str(TEST_APPOINTMENTS),
                        "--seed", str(TEST_SEED),
                        "--output-dir", str(folder)])
    return folder


@pytest.fixture(scope="session")
def tables(output_dir):
    """Read every generated CSV back in, with all values as text."""
    return {path.name: pd.read_csv(path, dtype=str) for path in output_dir.glob("*.csv")}
