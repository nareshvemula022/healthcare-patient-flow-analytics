"""Phase 3 checks for the SQL views and analyze_data.py.

Every test uses a small synthetic database in a temporary folder.
"""

import shutil
import sqlite3
from contextlib import closing

import pandas as pd
import pytest

import analyze_data
from analyze_data import AnalyticsError

VIEWS = ["vw_overall_kpis", "vw_monthly_trends", "vw_department_performance",
         "vw_provider_performance", "vw_appointment_type_performance", "vw_weekday_activity"]
COUNTS = ["total_appointments", "completed_appointments", "cancelled_appointments",
          "no_show_appointments"]
STATUS_RATES = ["completion_rate", "cancellation_rate", "no_show_rate"]
CAPACITY_RATES = ["booking_rate", "completed_slot_utilization"]
CAPACITY_BREAKDOWNS = ["monthly_trends", "department_performance", "provider_performance",
                       "weekday_activity"]

EXPECTED_COLUMNS = {
    "overall_kpis.csv": ["period_start", "period_end", "total_appointments", "unique_patients",
                         *COUNTS[1:], *STATUS_RATES, "avg_wait_minutes", "avg_visit_minutes",
                         "available_slots", *CAPACITY_RATES],
    "monthly_trends.csv": ["month", *COUNTS, *STATUS_RATES, "avg_wait_minutes",
                           "avg_visit_minutes", "available_slots", *CAPACITY_RATES],
    "department_performance.csv": ["department_id", "department_name", *COUNTS, *STATUS_RATES,
                                   "avg_wait_minutes", "avg_visit_minutes", "available_slots",
                                   *CAPACITY_RATES],
    "provider_performance.csv": ["provider_id", "provider_name", "specialty", "department_id",
                                 "department_name", "daily_slot_capacity", *COUNTS,
                                 *STATUS_RATES, "avg_wait_minutes", "avg_visit_minutes",
                                 "available_slots", *CAPACITY_RATES],
    "appointment_type_performance.csv": ["appointment_type", *COUNTS, *STATUS_RATES,
                                         "avg_wait_minutes", "avg_visit_minutes"],
    "weekday_activity.csv": ["weekday_number", "weekday_name", *COUNTS, *STATUS_RATES,
                             "avg_wait_minutes", "avg_visit_minutes", "available_slots",
                             *CAPACITY_RATES],
}


@pytest.fixture(scope="session")
def analysis(prepared_data, tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("analytics")
    results, checks = analyze_data.run_analysis(prepared_data["database"], output_dir)
    return {"results": results, "checks": checks, "output_dir": output_dir}


@pytest.fixture(scope="session")
def overall(analysis):
    return analysis["results"]["overall_kpis"].iloc[0]


@pytest.fixture
def database_copy(prepared_data, tmp_path):
    """A copy of the test database that a test may change."""
    copy = tmp_path / "copy.db"
    shutil.copy(prepared_data["database"], copy)
    return copy


def query(database, sql):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(sql).fetchall()


def execute(database, statements):
    with closing(sqlite3.connect(database)) as connection, connection:
        for statement in statements:
            connection.execute(statement)


# --- Views -------------------------------------------------------------------------

def test_all_views_exist(prepared_data, analysis):
    names = {row[0] for row in query(prepared_data["database"],
                                     "SELECT name FROM sqlite_master WHERE type = 'view'")}
    assert set(VIEWS) <= names


def test_all_reconciliation_checks_passed(analysis):
    assert len(analysis["checks"]) > 0
    assert all(check["passed"] for check in analysis["checks"])


# --- Totals reconcile ----------------------------------------------------------------

def test_overall_status_counts_sum_to_total(overall):
    assert (overall["completed_appointments"] + overall["cancelled_appointments"]
            + overall["no_show_appointments"]) == overall["total_appointments"]


def test_overall_matches_database_tables(prepared_data, overall):
    database = prepared_data["database"]
    assert overall["total_appointments"] == query(database,
                                                  "SELECT COUNT(*) FROM appointments")[0][0]
    assert overall["unique_patients"] == query(
        database, "SELECT COUNT(DISTINCT patient_id) FROM appointments")[0][0]
    assert overall["available_slots"] == query(
        database, "SELECT SUM(available_slots) FROM provider_schedules")[0][0]


@pytest.mark.parametrize("name", ["monthly_trends", "department_performance",
                                  "provider_performance", "weekday_activity",
                                  "appointment_type_performance"])
def test_breakdown_totals_reconcile_to_overall(analysis, overall, name):
    breakdown = analysis["results"][name]
    for column in COUNTS:
        assert breakdown[column].sum() == overall[column], column
    if "available_slots" in breakdown.columns:
        assert breakdown["available_slots"].sum() == overall["available_slots"]


def test_every_department_provider_and_month_appears(prepared_data, analysis):
    database = prepared_data["database"]
    results = analysis["results"]
    assert len(results["department_performance"]) == query(
        database, "SELECT COUNT(*) FROM departments")[0][0]
    assert len(results["provider_performance"]) == query(
        database, "SELECT COUNT(*) FROM providers")[0][0]
    assert list(results["monthly_trends"]["month"]) == [f"2025-{m:02d}" for m in range(1, 13)]


def test_capacity_is_not_multiplied_by_joins(prepared_data, analysis):
    database = prepared_data["database"]
    results = analysis["results"]
    for name, key in [("department_performance", "department_id"),
                      ("provider_performance", "provider_id")]:
        direct_slots = dict(query(database, f"SELECT {key}, SUM(available_slots) "
                                            f"FROM provider_schedules GROUP BY {key}"))
        direct_counts = dict(query(database, f"SELECT {key}, COUNT(*) "
                                             f"FROM appointments GROUP BY {key}"))
        for row in results[name].itertuples():
            assert row.available_slots == direct_slots.get(getattr(row, key), 0)
            assert row.total_appointments == direct_counts.get(getattr(row, key), 0)


# --- KPI formulas ---------------------------------------------------------------------

@pytest.mark.parametrize("name", ["overall_kpis", *CAPACITY_BREAKDOWNS])
def test_rates_use_correct_numerators_and_denominators(analysis, name):
    df = analysis["results"][name]
    total, slots = df["total_appointments"], df["available_slots"]
    assert df["completion_rate"].tolist() == pytest.approx(
        (df["completed_appointments"] / total).tolist())
    assert df["cancellation_rate"].tolist() == pytest.approx(
        (df["cancelled_appointments"] / total).tolist())
    assert df["no_show_rate"].tolist() == pytest.approx(
        (df["no_show_appointments"] / total).tolist())
    # Booking Rate counts every status; utilization counts Completed only.
    assert df["booking_rate"].tolist() == pytest.approx((total / slots).tolist())
    assert df["completed_slot_utilization"].tolist() == pytest.approx(
        (df["completed_appointments"] / slots).tolist())


def test_overall_rates_are_not_averages_of_department_rates(analysis, overall):
    departments = analysis["results"]["department_performance"]
    assert overall["booking_rate"] == pytest.approx(
        departments["total_appointments"].sum() / departments["available_slots"].sum())


def test_average_durations_use_completed_appointments_only(prepared_data, overall):
    wait, visit = query(prepared_data["database"],
                        "SELECT AVG(wait_minutes), AVG(visit_minutes) FROM appointments "
                        "WHERE appointment_status = 'Completed'")[0]
    assert overall["avg_wait_minutes"] == pytest.approx(wait)
    assert overall["avg_visit_minutes"] == pytest.approx(visit)


def test_appointment_types_have_no_capacity_columns(analysis):
    columns = analysis["results"]["appointment_type_performance"].columns
    assert "available_slots" not in columns
    assert "booking_rate" not in columns


# --- Zero denominators -------------------------------------------------------------------

def test_zero_denominators_give_null_rates(database_copy):
    first_day = query(database_copy, "SELECT MIN(schedule_date) FROM provider_schedules")[0][0]
    execute(database_copy, [
        # A department with no providers, no capacity and no appointments.
        "INSERT INTO departments VALUES ('DEP98', 'Empty Department')",
        # A department whose provider has capacity but no appointments.
        "INSERT INTO departments VALUES ('DEP99', 'Capacity Only')",
        "INSERT INTO providers VALUES ('PRV998', 'DEP99', 'Dr. Test Away', 'Tester', 10)",
        "INSERT INTO providers VALUES ('PRV999', 'DEP99', 'Dr. Test Open', 'Tester', 10)",
        f"INSERT INTO provider_schedules VALUES ('{first_day}', 'PRV998', 'DEP99', 0)",
        f"INSERT INTO provider_schedules VALUES ('{first_day}', 'PRV999', 'DEP99', 10)",
    ])
    results, checks = analyze_data.load_analytics(database_copy)
    assert all(check["passed"] for check in checks)

    departments = results["department_performance"].set_index("department_id")
    empty = departments.loc["DEP98"]
    assert empty["total_appointments"] == 0 and empty["available_slots"] == 0
    assert pd.isna(empty["completion_rate"]) and pd.isna(empty["booking_rate"])
    assert pd.isna(empty["avg_wait_minutes"])

    capacity_only = departments.loc["DEP99"]
    assert capacity_only["available_slots"] == 10
    assert capacity_only["booking_rate"] == 0.0
    assert pd.isna(capacity_only["completion_rate"])

    providers = results["provider_performance"].set_index("provider_id")
    assert pd.isna(providers.loc["PRV998", "booking_rate"])
    assert providers.loc["PRV999", "booking_rate"] == 0.0


def test_database_without_appointments_is_safe(database_copy):
    execute(database_copy, ["DELETE FROM appointments"])
    results, checks = analyze_data.load_analytics(database_copy)
    assert all(check["passed"] for check in checks)
    overall = results["overall_kpis"].iloc[0]
    assert overall["total_appointments"] == 0
    assert pd.isna(overall["completion_rate"]) and pd.isna(overall["avg_wait_minutes"])
    assert overall["booking_rate"] == 0.0


def test_inconsistent_results_are_rejected(database_copy, monkeypatch):
    original_query_views = analyze_data.query_views

    def query_views_with_an_extra_appointment(connection):
        results = original_query_views(connection)
        results["department_performance"].loc[0, "total_appointments"] += 1
        return results

    monkeypatch.setattr(analyze_data, "query_views", query_views_with_an_extra_appointment)
    with pytest.raises(AnalyticsError, match="department_performance: sum of total_appointments"):
        analyze_data.load_analytics(database_copy)


# --- Exports and running ------------------------------------------------------------------

def test_csv_exports_have_expected_columns(analysis):
    for file_name, columns in EXPECTED_COLUMNS.items():
        exported = pd.read_csv(analysis["output_dir"] / file_name)
        assert list(exported.columns) == columns, file_name
        assert len(exported) == len(analysis["results"][file_name.removesuffix(".csv")])


def test_missing_database_gives_helpful_error(tmp_path, capsys):
    with pytest.raises(FileNotFoundError, match="python prepare_data.py"):
        analyze_data.load_analytics(tmp_path / "missing.db")
    assert analyze_data.main(["--database", str(tmp_path / "missing.db"),
                              "--output-dir", str(tmp_path / "out")]) == 1
    assert "prepare_data.py" in capsys.readouterr().err
    assert not (tmp_path / "missing.db").exists(), "no empty database should be created"


def test_rerunning_gives_identical_results(prepared_data, analysis, tmp_path):
    analyze_data.run_analysis(prepared_data["database"], tmp_path)
    analyze_data.run_analysis(prepared_data["database"], tmp_path)  # views are re-created
    for file_name in EXPECTED_COLUMNS:
        assert ((tmp_path / file_name).read_bytes()
                == (analysis["output_dir"] / file_name).read_bytes()), file_name
