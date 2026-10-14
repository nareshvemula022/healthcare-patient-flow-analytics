"""Phase 2 checks: validation, cleaning, the SQLite database and the quality report.

Every test works in its own temporary folders, never in the project's data/ folder.
"""

import json
import shutil
import sqlite3
from contextlib import closing

import pandas as pd
import pytest

import config
import generate_data
import prepare_data
from prepare_data import DataValidationError

TABLES = ["departments", "providers", "patients", "provider_schedules", "appointments"]
TIME_COLUMNS = ["check_in_datetime", "seen_datetime", "checkout_datetime"]
DATETIME_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"


# --- Helpers and fixtures ------------------------------------------------------

@pytest.fixture(scope="session")
def clean_raw_dir(tmp_path_factory):
    """A small, valid synthetic raw dataset (generated once, never modified)."""
    folder = tmp_path_factory.mktemp("clean_raw")
    generate_data.write_csvs(generate_data.generate_all(n_appointments=800, seed=11), folder)
    return folder


@pytest.fixture
def raw_dir(clean_raw_dir, tmp_path):
    """A fresh copy of the raw data that a test may edit."""
    folder = tmp_path / "raw"
    shutil.copytree(clean_raw_dir, folder)
    return folder


def run(raw_dir, tmp_path):
    """Run the pipeline with all outputs inside tmp_path."""
    return prepare_data.run_pipeline(raw_dir, tmp_path / "processed", tmp_path / "output")


@pytest.fixture(scope="session")
def pipeline(clean_raw_dir, tmp_path_factory):
    """Run the pipeline once on valid data; tests below read its outputs."""
    base = tmp_path_factory.mktemp("pipeline")
    report = run(clean_raw_dir, base)
    return {"report": report,
            "processed": base / "processed",
            "database": base / "processed" / config.DATABASE_FILE_NAME,
            "report_file": base / "output" / config.QUALITY_REPORT_FILE_NAME}


@pytest.fixture(scope="session")
def processed_appointments(pipeline):
    return pd.read_csv(pipeline["processed"] / "appointments.csv", dtype=str)


def edit_raw(raw_dir, table, change):
    """Read a raw CSV as text, apply change(df), and save it again."""
    path = raw_dir / f"{table}.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = change(df)
    df.to_csv(path, index=False)


def first_row(df, column, value):
    """Index of the first row where column == value."""
    return df.index[df[column] == value][0]


def query(database, sql):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(sql).fetchall()


# --- Missing files and columns ---------------------------------------------

def test_missing_raw_files_give_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        prepare_data.run_pipeline(tmp_path / "empty", tmp_path / "processed", tmp_path / "out")
    message = str(error.value)
    assert "appointments.csv" in message
    assert "python generate_data.py" in message


def test_one_missing_raw_file_is_named(raw_dir, tmp_path):
    (raw_dir / "patients.csv").unlink()
    with pytest.raises(FileNotFoundError, match="patients.csv"):
        run(raw_dir, tmp_path)


def test_missing_required_column_is_rejected(raw_dir, tmp_path):
    edit_raw(raw_dir, "patients", lambda df: df.drop(columns=["age_group"]))
    with pytest.raises(DataValidationError, match="patients.csv is missing required column"):
        run(raw_dir, tmp_path)


# --- Rejected records ----------------------------------------------------------

def make_duplicate_appointment_id(df):
    df.loc[1, "appointment_id"] = df.loc[0, "appointment_id"]
    return df


def make_unknown_patient(df):
    df.loc[0, "patient_id"] = "PAT99999"
    return df


def make_department_mismatch(df):
    other_department = "DEP06" if df.loc[0, "department_id"] != "DEP06" else "DEP05"
    df.loc[0, "department_id"] = other_department
    return df


def make_wrong_age_group(df):
    df.loc[first_row(df, "age_group", "0-17"), "age_group"] = "65+"
    return df


def make_invalid_status(df):
    df.loc[0, "appointment_status"] = "Done"
    return df


def make_zero_capacity(df):
    df.loc[0, "daily_slot_capacity"] = "0"
    return df


def make_seen_before_check_in(df):
    row = first_row(df, "appointment_status", "Completed")
    df.loc[row, "seen_time"] = "00:01"
    return df


def make_missing_checkout(df):
    df.loc[first_row(df, "appointment_status", "Completed"), "checkout_time"] = ""
    return df


def make_cancelled_with_check_in(df):
    df.loc[first_row(df, "appointment_status", "Cancelled"), "check_in_time"] = "09:00"
    return df


def make_no_show_with_seen_time(df):
    df.loc[first_row(df, "appointment_status", "No Show"), "seen_time"] = "09:00"
    return df


def make_blank_patient_city(df):
    df.loc[0, "city"] = ""
    return df


@pytest.mark.parametrize("table, change, expected_message", [
    ("appointments", make_duplicate_appointment_id, "primary key must be unique"),
    ("appointments", make_unknown_patient, r"appointments.\(patient_id\) -> patients"),
    ("appointments", make_department_mismatch, "department_id must match the provider"),
    ("patients", make_wrong_age_group, "age_group must match age"),
    ("appointments", make_invalid_status, "appointment_status must be one of"),
    ("providers", make_zero_capacity, "daily_slot_capacity must be a positive whole number"),
    ("appointments", make_seen_before_check_in, "check-in <= seen <= checkout"),
    ("appointments", make_missing_checkout, "need valid check-in, seen and checkout"),
    ("appointments", make_cancelled_with_check_in, "must have blank check-in"),
    ("appointments", make_no_show_with_seen_time, "must have blank check-in"),
    ("patients", make_blank_patient_city, "required values must not be blank"),
])
def test_invalid_records_are_rejected(raw_dir, tmp_path, table, change, expected_message):
    edit_raw(raw_dir, table, change)
    with pytest.raises(DataValidationError, match=expected_message):
        run(raw_dir, tmp_path)


def test_rejected_run_writes_failed_report_and_no_processed_files(raw_dir, tmp_path):
    edit_raw(raw_dir, "appointments", make_invalid_status)
    with pytest.raises(DataValidationError):
        run(raw_dir, tmp_path)

    assert not (tmp_path / "processed").exists()
    report = json.loads((tmp_path / "output" / config.QUALITY_REPORT_FILE_NAME).read_text())
    assert report["pipeline_status"] == "failed"
    assert report["synthetic_data"] is True
    assert any("appointment_status" in line for line in report["errors"])


def test_surrounding_spaces_are_removed(raw_dir, tmp_path):
    def add_spaces(df):
        df.loc[0, "appointment_status"] = f"  {df.loc[0, 'appointment_status']} "
        df.loc[0, "patient_id"] = f" {df.loc[0, 'patient_id']}"
        return df

    edit_raw(raw_dir, "appointments", add_spaces)
    run(raw_dir, tmp_path)
    cleaned = pd.read_csv(tmp_path / "processed" / "appointments.csv", dtype=str)
    original = pd.read_csv(raw_dir / "appointments.csv", dtype=str)
    row = first_row(cleaned, "appointment_id", original.loc[0, "appointment_id"])
    assert cleaned.loc[row, "appointment_status"] == original.loc[0, "appointment_status"].strip()
    assert cleaned.loc[row, "patient_id"] == original.loc[0, "patient_id"].strip()


# --- Processed CSV files ---------------------------------------------------------

def test_processed_csv_files_are_created(pipeline, clean_raw_dir):
    for table in TABLES:
        processed = pd.read_csv(pipeline["processed"] / f"{table}.csv", dtype=str)
        raw = pd.read_csv(clean_raw_dir / f"{table}.csv", dtype=str)
        assert len(processed) == len(raw), table


def test_processed_appointment_columns(processed_appointments):
    assert list(processed_appointments.columns) == prepare_data.PROCESSED_APPOINTMENT_COLUMNS


def test_completed_timestamps_and_durations(processed_appointments):
    completed = processed_appointments[processed_appointments["appointment_status"] == "Completed"]
    assert len(completed) > 0
    for column in ["scheduled_datetime"] + TIME_COLUMNS:
        assert completed[column].str.fullmatch(DATETIME_PATTERN).all(), column
        assert (completed[column].str[:10] == completed["appointment_date"]).all(), column

    check_in = pd.to_datetime(completed["check_in_datetime"])
    seen = pd.to_datetime(completed["seen_datetime"])
    checkout = pd.to_datetime(completed["checkout_datetime"])
    wait = completed["wait_minutes"].astype(int)
    visit = completed["visit_minutes"].astype(int)

    assert (wait == (seen - check_in).dt.total_seconds() / 60).all()
    assert (visit == (checkout - seen).dt.total_seconds() / 60).all()
    assert (wait >= 0).all() and (visit >= 0).all()


def test_wait_starts_at_check_in_even_when_patient_is_early(processed_appointments):
    completed = processed_appointments[processed_appointments["appointment_status"] == "Completed"]
    scheduled = pd.to_datetime(completed["scheduled_datetime"])
    check_in = pd.to_datetime(completed["check_in_datetime"])
    seen = pd.to_datetime(completed["seen_datetime"])
    early = check_in < scheduled
    assert early.any(), "test data should contain early check-ins"
    expected_wait = (seen[early] - check_in[early]).dt.total_seconds() / 60
    assert (completed.loc[early, "wait_minutes"].astype(int) == expected_wait).all()


def test_non_completed_have_blank_times_and_durations(processed_appointments):
    for status in ["Cancelled", "No Show"]:
        rows = processed_appointments[processed_appointments["appointment_status"] == status]
        assert len(rows) > 0, status
        assert rows["scheduled_datetime"].str.fullmatch(DATETIME_PATTERN).all()
        assert rows[TIME_COLUMNS + ["wait_minutes", "visit_minutes"]].isna().all().all()


# --- SQLite database ---------------------------------------------------------

def test_database_tables_are_created(pipeline):
    names = {row[0] for row in query(pipeline["database"],
                                     "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == set(TABLES)


def test_database_indexes_are_created(pipeline):
    names = {row[0] for row in query(pipeline["database"],
                                     "SELECT name FROM sqlite_master WHERE type = 'index'")}
    for column in ["date", "status", "department", "provider", "patient"]:
        assert f"idx_appointments_{column}" in names


def test_database_row_counts_match_csv(pipeline):
    for table in TABLES:
        csv_rows = len(pd.read_csv(pipeline["processed"] / f"{table}.csv"))
        database_rows = query(pipeline["database"], f"SELECT COUNT(*) FROM {table}")[0][0]
        assert database_rows == csv_rows, table


def test_database_foreign_keys_are_intact(pipeline):
    assert query(pipeline["database"], "PRAGMA foreign_key_check") == []
    foreign_keys = query(pipeline["database"], "PRAGMA foreign_key_list(appointments)")
    assert {row[2] for row in foreign_keys} == {
        "patients", "providers", "departments", "provider_schedules"}


def test_database_blank_values_are_null(pipeline):
    rows = query(pipeline["database"],
                 "SELECT COUNT(*) FROM appointments WHERE appointment_status <> 'Completed' "
                 "AND (check_in_datetime IS NOT NULL OR wait_minutes IS NOT NULL)")
    assert rows[0][0] == 0
    types = query(pipeline["database"],
                  "SELECT DISTINCT typeof(wait_minutes) FROM appointments "
                  "WHERE appointment_status = 'Completed'")
    assert types == [("integer",)]


@pytest.mark.parametrize("sql", [
    # Unknown patient (foreign key).
    "INSERT INTO appointments VALUES ('X1', 'PAT99999', 'PRV001', 'DEP01', '{date}', "
    "'{date} 08:00:00', NULL, NULL, NULL, NULL, NULL, 'Follow-Up', 'Cancelled')",
    # Negative wait (CHECK constraint).
    "INSERT INTO appointments VALUES ('X2', '{patient}', 'PRV001', 'DEP01', '{date}', "
    "'{date} 08:00:00', '{date} 08:00:00', '{date} 08:10:00', '{date} 08:30:00', -5, 20, "
    "'Follow-Up', 'Completed')",
    # Invalid status (CHECK constraint).
    "INSERT INTO appointments VALUES ('X3', '{patient}', 'PRV001', 'DEP01', '{date}', "
    "'{date} 08:00:00', NULL, NULL, NULL, NULL, NULL, 'Follow-Up', 'Done')",
    # Negative age (CHECK constraint).
    "INSERT INTO patients VALUES ('X4', -1, '0-17', 'Female', 'Riverton', 'Medicaid')",
])
def test_database_rejects_invalid_rows(pipeline, tmp_path, sql):
    database = tmp_path / "copy.db"
    shutil.copy(pipeline["database"], database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        date, = connection.execute("SELECT schedule_date FROM provider_schedules "
                                   "WHERE provider_id = 'PRV001' LIMIT 1").fetchone()
        patient, = connection.execute("SELECT patient_id FROM patients LIMIT 1").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql.format(date=date, patient=patient))


# --- Re-running ------------------------------------------------------------------

def database_contents(database):
    return {table: query(database, f"SELECT * FROM {table} ORDER BY 1, 2") for table in TABLES}


def test_rerunning_rebuilds_the_same_data(clean_raw_dir, tmp_path):
    first_report = run(clean_raw_dir, tmp_path)
    database = tmp_path / "processed" / config.DATABASE_FILE_NAME
    first_files = {t: (tmp_path / "processed" / f"{t}.csv").read_bytes() for t in TABLES}
    first_database = database_contents(database)
    first_json = (tmp_path / "output" / config.QUALITY_REPORT_FILE_NAME).read_bytes()

    second_report = run(clean_raw_dir, tmp_path)  # same folders: tables are rebuilt

    assert second_report == first_report
    assert database_contents(database) == first_database
    for table in TABLES:
        assert (tmp_path / "processed" / f"{table}.csv").read_bytes() == first_files[table]
    assert (tmp_path / "output" / config.QUALITY_REPORT_FILE_NAME).read_bytes() == first_json


# --- Data-quality report ----------------------------------------------------------

def test_quality_report_structure(pipeline):
    report = json.loads(pipeline["report_file"].read_text(encoding="utf-8"))
    assert report == pipeline["report"]
    for key in ["pipeline_status", "synthetic_data", "data_notice", "raw_row_counts",
                "duplicate_primary_keys", "missing_required_values", "foreign_key_violations",
                "rule_violations", "processed_csv_row_counts", "database_row_counts",
                "sqlite_foreign_key_check", "appointment_status_counts",
                "completed_appointments", "wait_minutes", "visit_minutes", "errors"]:
        assert key in report, key
    assert report["pipeline_status"] == "passed"
    assert report["synthetic_data"] is True
    assert "synthetic" in report["data_notice"].lower()
    assert report["errors"] == []


def test_quality_report_values(pipeline, processed_appointments):
    report = pipeline["report"]
    for section in ["duplicate_primary_keys", "missing_required_values",
                    "foreign_key_violations", "rule_violations"]:
        assert set(report[section].values()) == {0}, section
    assert report["sqlite_foreign_key_check"] == {"passed": True, "violations": 0}
    assert report["database_row_counts"] == report["processed_csv_row_counts"]
    assert report["database_row_counts"]["appointments"] == len(processed_appointments)

    statuses = processed_appointments["appointment_status"].value_counts().to_dict()
    assert report["appointment_status_counts"] == statuses
    assert report["completed_appointments"] == statuses["Completed"]

    completed = processed_appointments[processed_appointments["appointment_status"] == "Completed"]
    for column in ["wait_minutes", "visit_minutes"]:
        minutes = completed[column].astype(int)
        assert report[column] == {"min": minutes.min(), "max": minutes.max(),
                                  "average": round(minutes.mean(), 2)}
