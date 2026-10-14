"""Shared test setup: generate small synthetic datasets in temporary folders."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Let the tests import the project scripts from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
import generate_data  # noqa: E402
import prepare_data  # noqa: E402

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


@pytest.fixture(scope="session")
def prepared_data(tmp_path_factory):
    """Phase 1 + Phase 2 on a small dataset: a SQLite database and a quality report."""
    base = tmp_path_factory.mktemp("prepared")
    tables = generate_data.generate_all(n_appointments=900, seed=5)
    generate_data.write_csvs(tables, base / "raw")
    prepare_data.run_pipeline(base / "raw", base / "processed", base / "output")
    return {"database": base / "processed" / config.DATABASE_FILE_NAME,
            "quality_report": base / "output" / config.QUALITY_REPORT_FILE_NAME}
