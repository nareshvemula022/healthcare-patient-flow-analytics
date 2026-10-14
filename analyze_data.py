"""Phase 3: run the SQL analytics on the SYNTHETIC SQLite database and export CSV files.

All data is fictional. Run this after prepare_data.py (PowerShell):
    python analyze_data.py

Steps:
  1. Create (or re-create) the views in sql/02_create_analytics_views.sql.
  2. Query every view. All KPI calculations happen in SQL.
  3. Check that overall, monthly, department, provider, weekday and appointment-type
     results add up to the same totals. Any mismatch stops the script with an error.
  4. Export one CSV file per view to data/output/analytics/.
"""

import argparse
import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

import config

# CSV file -> (view, ORDER BY). Each export has a fixed sort order.
EXPORTS = {
    "overall_kpis.csv": ("vw_overall_kpis", None),
    "monthly_trends.csv": ("vw_monthly_trends", "month"),
    "department_performance.csv": ("vw_department_performance", "department_id"),
    "provider_performance.csv": ("vw_provider_performance", "department_id, provider_id"),
    "appointment_type_performance.csv": ("vw_appointment_type_performance",
                                         "total_appointments DESC, appointment_type"),
    "weekday_activity.csv": ("vw_weekday_activity", "weekday_number"),
}

# Short names for each result, e.g. "monthly_trends".
RESULT_NAMES = [Path(file_name).stem for file_name in EXPORTS]
BREAKDOWNS = [name for name in RESULT_NAMES if name != "overall_kpis"]

STATUS_COUNT_COLUMNS = ["total_appointments", "completed_appointments",
                        "cancelled_appointments", "no_show_appointments"]
DURATION_COLUMNS = ["avg_wait_minutes", "avg_visit_minutes"]

# KPI name -> definition. Used in the Excel report and matches the SQL comments.
KPI_DEFINITIONS = {
    "Total Appointments": "All appointment records (every status).",
    "Unique Patients": "Distinct patients with at least one appointment.",
    "Completed Appointments": "Appointments with status Completed.",
    "Cancelled Appointments": "Appointments with status Cancelled.",
    "No Show Appointments": "Appointments with status No Show.",
    "Completion Rate": "Completed Appointments / Total Appointments.",
    "Cancellation Rate": "Cancelled Appointments / Total Appointments.",
    "No Show Rate": "No Show Appointments / Total Appointments.",
    "Average Wait Minutes": "Average wait_minutes (check-in to seen), Completed only.",
    "Average Visit Minutes": "Average visit_minutes (seen to checkout), Completed only.",
    "Available Slots": "Sum of provider_schedules.available_slots.",
    "Booking Rate": "Total Appointments / Available Slots (every status uses a slot).",
    "Completed Slot Utilization": "Completed Appointments / Available Slots.",
}


class AnalyticsError(Exception):
    """The analytical results do not add up. The message lists every mismatch."""


def check_database_exists(database_path):
    database_path = Path(database_path)
    if not database_path.exists():
        raise FileNotFoundError(
            f"Database not found: {database_path}\n"
            "Create it first by running:\n"
            "    python generate_data.py --appointments 5000 --seed 42\n"
            "    python prepare_data.py"
        )


def create_views(connection, views_sql_path):
    connection.executescript(Path(views_sql_path).read_text(encoding="utf-8"))


def query_views(connection):
    """Read every analytical view into a DataFrame, using the fixed sort order."""
    results = {}
    for file_name, (view, order_by) in EXPORTS.items():
        sql = f"SELECT * FROM {view}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        results[Path(file_name).stem] = pd.read_sql_query(sql, connection)
    return results


def values_match(expected, actual, tolerance=0.0):
    """True if both numbers are equal (within tolerance) or both are missing."""
    expected_missing = expected is None or (isinstance(expected, float) and math.isnan(expected))
    actual_missing = actual is None or (isinstance(actual, float) and math.isnan(actual))
    if expected_missing or actual_missing:
        return expected_missing and actual_missing
    return abs(expected - actual) <= tolerance


def plain_number(value):
    """numpy numbers -> plain Python int/float (NaN -> None) for reports and JSON."""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def reconcile(results, connection):
    """Check that every breakdown adds up to the overall totals.
    Returns one result per check: {"check", "expected", "actual", "passed"}."""
    checks = []
    overall = results["overall_kpis"].iloc[0]

    def add(check, expected, actual, tolerance=0.0):
        expected, actual = plain_number(expected), plain_number(actual)
        checks.append({"check": check, "expected": expected, "actual": actual,
                       "passed": values_match(expected, actual, tolerance)})

    # The overall view against the database tables themselves.
    appointment_rows = connection.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    schedule_slots = connection.execute(
        "SELECT COALESCE(SUM(available_slots), 0) FROM provider_schedules").fetchone()[0]
    add("overall: total_appointments = rows in appointments table",
        appointment_rows, overall["total_appointments"])
    add("overall: available_slots = sum of provider_schedules.available_slots",
        schedule_slots, overall["available_slots"])
    add("overall: completed + cancelled + no_show = total_appointments",
        overall["total_appointments"],
        overall["completed_appointments"] + overall["cancelled_appointments"]
        + overall["no_show_appointments"])

    # Every breakdown must add up to the overall numbers.
    for name in BREAKDOWNS:
        breakdown = results[name]
        columns = STATUS_COUNT_COLUMNS.copy()
        if "available_slots" in breakdown.columns:
            columns.append("available_slots")
        for column in columns:
            add(f"{name}: sum of {column} = overall", overall[column], breakdown[column].sum())

        # Averages: each row's average weighted by its completed appointments must
        # give back the overall average (allowing for tiny rounding differences).
        completed = breakdown["completed_appointments"]
        for column in DURATION_COLUMNS:
            weighted = ((breakdown[column] * completed).sum() / completed.sum()
                        if completed.sum() > 0 else None)
            add(f"{name}: completed-weighted {column} = overall", overall[column], weighted,
                tolerance=1e-9)
    return checks


def load_analytics(database_path=config.DATABASE_FILE, views_sql_path=config.ANALYTICS_VIEWS_FILE):
    """Create the views, query them and reconcile the totals.
    Returns (results, checks). Raises AnalyticsError if anything does not add up."""
    check_database_exists(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        create_views(connection, views_sql_path)
        results = query_views(connection)
        checks = reconcile(results, connection)

    failed = [check for check in checks if not check["passed"]]
    if failed:
        lines = [f"- {c['check']}: expected {c['expected']}, got {c['actual']}" for c in failed]
        raise AnalyticsError("Analytical results do not reconcile:\n" + "\n".join(lines))
    return results, checks


def export_csvs(results, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in RESULT_NAMES:
        results[name].to_csv(output_dir / f"{name}.csv", index=False)


def run_analysis(database_path=config.DATABASE_FILE, output_dir=config.ANALYTICS_OUTPUT_DIR,
                 views_sql_path=config.ANALYTICS_VIEWS_FILE):
    results, checks = load_analytics(database_path, views_sql_path)
    export_csvs(results, output_dir)
    return results, checks


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the SQL analytics on the synthetic database and export CSV files.")
    parser.add_argument("--database", default=str(config.DATABASE_FILE),
                        help="SQLite database (default data/processed/healthcare_analytics.db)")
    parser.add_argument("--output-dir", default=str(config.ANALYTICS_OUTPUT_DIR),
                        help="folder for the CSV exports (default data/output/analytics)")
    args = parser.parse_args(argv)

    try:
        results, checks = run_analysis(args.database, args.output_dir)
    except (FileNotFoundError, AnalyticsError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    overall = results["overall_kpis"].iloc[0]
    print("Phase 3 analytics finished (SYNTHETIC data).")
    print(f"  Reconciliation: {len(checks)} of {len(checks)} checks passed")
    print(f"  CSV exports:    {Path(args.output_dir).resolve()}")
    for name in RESULT_NAMES:
        print(f"    {name + '.csv':<36} {len(results[name]):>4} rows")
    print(f"  Total appointments:         {overall['total_appointments']:,}")
    print(f"  Completion rate:            {overall['completion_rate']:.1%}")
    print(f"  Booking rate:               {overall['booking_rate']:.1%}")
    print(f"  Completed slot utilization: {overall['completed_slot_utilization']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
