"""Checks that the synthetic data is complete, consistent and repeatable."""

import pandas as pd
import pytest

import generate_data
from conftest import TEST_APPOINTMENTS, TEST_SEED

EXPECTED_COLUMNS = {
    "departments.csv": ["department_id", "department_name"],
    "providers.csv": ["provider_id", "department_id", "provider_name", "specialty",
                      "daily_slot_capacity"],
    "patients.csv": ["patient_id", "age", "age_group", "gender", "city", "insurance_type"],
    "appointments.csv": ["appointment_id", "patient_id", "provider_id", "department_id",
                         "appointment_date", "scheduled_time", "check_in_time", "seen_time",
                         "checkout_time", "appointment_type", "appointment_status"],
    "provider_schedules.csv": ["schedule_date", "provider_id", "department_id",
                               "available_slots"],
}
TIME_COLUMNS = ["check_in_time", "seen_time", "checkout_time"]


def to_datetime(appointments, column):
    """Combine appointment_date with a HH:MM time column."""
    return pd.to_datetime(appointments["appointment_date"] + " " + appointments[column],
                          format="%Y-%m-%d %H:%M")


# --- Files and columns -----------------------------------------------------

def test_expected_files_are_created(output_dir):
    created = sorted(path.name for path in output_dir.glob("*.csv"))
    assert created == sorted(EXPECTED_COLUMNS)


@pytest.mark.parametrize("file_name", sorted(EXPECTED_COLUMNS))
def test_required_columns_exist(tables, file_name):
    assert list(tables[file_name].columns) == EXPECTED_COLUMNS[file_name]


def test_requested_number_of_appointments(tables):
    assert len(tables["appointments.csv"]) == TEST_APPOINTMENTS


# --- Keys ------------------------------------------------------------------

@pytest.mark.parametrize("file_name, key", [
    ("departments.csv", "department_id"),
    ("providers.csv", "provider_id"),
    ("patients.csv", "patient_id"),
    ("appointments.csv", "appointment_id"),
])
def test_primary_ids_are_unique_and_present(tables, file_name, key):
    ids = tables[file_name][key]
    assert ids.notna().all()
    assert ids.is_unique


def test_one_schedule_row_per_provider_per_day(tables):
    schedules = tables["provider_schedules.csv"]
    assert not schedules.duplicated(["schedule_date", "provider_id"]).any()


@pytest.mark.parametrize("child_file, column, parent_file", [
    ("providers.csv", "department_id", "departments.csv"),
    ("appointments.csv", "patient_id", "patients.csv"),
    ("appointments.csv", "provider_id", "providers.csv"),
    ("appointments.csv", "department_id", "departments.csv"),
    ("provider_schedules.csv", "provider_id", "providers.csv"),
    ("provider_schedules.csv", "department_id", "departments.csv"),
])
def test_foreign_keys_match_parent_table(tables, child_file, column, parent_file):
    child_values = set(tables[child_file][column])
    parent_values = set(tables[parent_file][column])
    assert child_values <= parent_values


@pytest.mark.parametrize("file_name", ["appointments.csv", "provider_schedules.csv"])
def test_department_matches_provider_department(tables, file_name):
    provider_department = tables["providers.csv"].set_index("provider_id")["department_id"]
    rows = tables[file_name]
    assert (rows["provider_id"].map(provider_department) == rows["department_id"]).all()


# --- Appointments fit the provider schedules -------------------------------

def test_appointments_fit_within_available_slots(tables):
    appointments = tables["appointments.csv"]
    schedules = tables["provider_schedules.csv"].copy()
    schedules["available_slots"] = schedules["available_slots"].astype(int)

    booked = (appointments.groupby(["appointment_date", "provider_id"]).size()
              .rename("booked").reset_index()
              .rename(columns={"appointment_date": "schedule_date"}))
    merged = booked.merge(schedules, on=["schedule_date", "provider_id"], how="left")

    assert merged["available_slots"].notna().all(), "appointment on a day the provider is off"
    assert (merged["booked"] <= merged["available_slots"]).all()


def test_provider_is_never_double_booked(tables):
    appointments = tables["appointments.csv"]
    key = ["appointment_date", "scheduled_time", "provider_id"]
    assert not appointments.duplicated(key).any()


def test_appointment_dates_cover_one_year(tables):
    dates = pd.to_datetime(tables["appointments.csv"]["appointment_date"])
    assert dates.min() >= pd.Timestamp("2025-01-01")
    assert dates.max() <= pd.Timestamp("2025-12-31")
    assert dates.dt.month.nunique() == 12
    assert (dates.dt.weekday < 5).all(), "clinic is closed on weekends"


# --- Status and timestamps -------------------------------------------------

def test_statuses_and_types_are_valid(tables):
    appointments = tables["appointments.csv"]
    assert set(appointments["appointment_status"]) == {"Completed", "Cancelled", "No Show"}
    assert set(appointments["appointment_type"]) <= {
        "Follow-Up", "New Patient", "Consultation", "Procedure"}


def test_completed_timestamps_are_logically_ordered(tables):
    appointments = tables["appointments.csv"]
    completed = appointments[appointments["appointment_status"] == "Completed"]
    assert len(completed) > 0
    assert completed[TIME_COLUMNS].notna().all().all()

    scheduled = to_datetime(completed, "scheduled_time")
    check_in = to_datetime(completed, "check_in_time")
    seen = to_datetime(completed, "seen_time")
    checkout = to_datetime(completed, "checkout_time")

    assert (check_in <= seen).all()
    assert (scheduled <= seen).all()
    assert (seen < checkout).all()


@pytest.mark.parametrize("status", ["Cancelled", "No Show"])
def test_cancelled_and_no_show_have_no_visit_times(tables, status):
    appointments = tables["appointments.csv"]
    rows = appointments[appointments["appointment_status"] == status]
    assert len(rows) > 0
    assert rows["scheduled_time"].notna().all()
    assert rows[TIME_COLUMNS].isna().all().all()


# --- Patients --------------------------------------------------------------

def test_age_group_matches_age(tables):
    patients = tables["patients.csv"]
    expected = patients["age"].astype(int).map(generate_data.age_to_group)
    assert (patients["age_group"] == expected).all()


def test_pediatrics_only_sees_children(tables):
    departments = tables["departments.csv"]
    pediatrics_id = departments.loc[departments["department_name"] == "Pediatrics",
                                    "department_id"].iloc[0]
    ages = tables["patients.csv"].set_index("patient_id")["age"].astype(int)
    appointments = tables["appointments.csv"]
    pediatric_patients = appointments.loc[appointments["department_id"] == pediatrics_id,
                                          "patient_id"]
    assert (pediatric_patients.map(ages) < 18).all()


# --- Repeatability ---------------------------------------------------------

def test_same_seed_gives_identical_files(output_dir, tmp_path):
    generate_data.main(["--appointments", str(TEST_APPOINTMENTS), "--seed", str(TEST_SEED),
                        "--output-dir", str(tmp_path)])
    for file_name in EXPECTED_COLUMNS:
        first_run = (output_dir / file_name).read_bytes()
        second_run = (tmp_path / file_name).read_bytes()
        assert first_run == second_run, f"{file_name} changed between runs"


def test_different_seed_gives_different_data(output_dir, tmp_path):
    generate_data.main(["--appointments", str(TEST_APPOINTMENTS), "--seed", str(TEST_SEED + 1),
                        "--output-dir", str(tmp_path)])
    first = (output_dir / "appointments.csv").read_bytes()
    second = (tmp_path / "appointments.csv").read_bytes()
    assert first != second


def test_too_many_appointments_gives_clear_error():
    with pytest.raises(ValueError, match="open slots"):
        generate_data.generate_all(n_appointments=1_000_000, seed=1, n_patients=50)
