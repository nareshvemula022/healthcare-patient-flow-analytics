"""Phase 4A: export a stable Power BI data snapshot from the SYNTHETIC SQLite database.

All data is fictional. Run this after prepare_data.py (PowerShell):
    python prepare_powerbi_data.py

Steps:
  1. Run the Phase 3 SQL analytics (analyze_data.py) so the KPI views exist and
     reconcile.
  2. Read the five database tables and build a calendar Date table.
  3. Check primary keys and foreign keys. Any problem stops the script before
     anything is written.
  4. Write six CSV files to powerbi/data/ and powerbi/expected_kpis.json.
  5. Read the CSV files back and confirm row counts and headline KPIs match SQLite.

The Power BI report itself (.pbix) is built by hand in Power BI Desktop; see
powerbi/POWER_BI_BUILD_GUIDE.md.
"""

import argparse
import csv
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import analyze_data
import config

# Power BI file -> query. Fixed sort orders keep the files identical between runs.
TABLE_QUERIES = {
    "departments.csv": """
        SELECT department_id, department_name
        FROM departments ORDER BY department_id""",
    "providers.csv": """
        SELECT provider_id, department_id, provider_name, specialty, daily_slot_capacity
        FROM providers ORDER BY provider_id""",
    "patients.csv": """
        SELECT patient_id, age, age_group, gender, city, insurance_type
        FROM patients ORDER BY patient_id""",
    "provider_schedules.csv": """
        SELECT schedule_date, provider_id, department_id, available_slots
        FROM provider_schedules ORDER BY schedule_date, provider_id""",
    "appointments.csv": """
        SELECT appointment_id, patient_id, provider_id, department_id, appointment_date,
               scheduled_datetime, check_in_datetime, seen_datetime, checkout_datetime,
               wait_minutes, visit_minutes, appointment_type, appointment_status
        FROM appointments ORDER BY appointment_id""",
}
DATE_FILE = "date.csv"
DATE_COLUMNS = ["date", "year", "quarter", "month_number", "month_name", "year_month",
                "year_month_sort", "weekday_number", "weekday_name", "is_weekend"]
POWERBI_FILES = [*TABLE_QUERIES, DATE_FILE]

# Written out in English so the result does not depend on the computer's language.
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                 "Sunday"]

PRIMARY_KEYS = {
    "departments.csv": ["department_id"],
    "providers.csv": ["provider_id"],
    "patients.csv": ["patient_id"],
    "provider_schedules.csv": ["schedule_date", "provider_id"],
    "appointments.csv": ["appointment_id"],
    DATE_FILE: ["date"],
}
# (child file, child column, parent file, parent column)
FOREIGN_KEYS = [
    ("providers.csv", "department_id", "departments.csv", "department_id"),
    ("appointments.csv", "patient_id", "patients.csv", "patient_id"),
    ("appointments.csv", "provider_id", "providers.csv", "provider_id"),
    ("appointments.csv", "department_id", "departments.csv", "department_id"),
    ("appointments.csv", "appointment_date", DATE_FILE, "date"),
    ("provider_schedules.csv", "provider_id", "providers.csv", "provider_id"),
    ("provider_schedules.csv", "department_id", "departments.csv", "department_id"),
    ("provider_schedules.csv", "schedule_date", DATE_FILE, "date"),
]

# KPI name (same as the DAX measure) -> (column in vw_overall_kpis, kind of value).
EXPECTED_KPIS = [
    ("Total Appointments", "total_appointments", "count"),
    ("Unique Patients", "unique_patients", "count"),
    ("Completed Appointments", "completed_appointments", "count"),
    ("Cancelled Appointments", "cancelled_appointments", "count"),
    ("No Show Appointments", "no_show_appointments", "count"),
    ("Completion Rate", "completion_rate", "rate"),
    ("Cancellation Rate", "cancellation_rate", "rate"),
    ("No Show Rate", "no_show_rate", "rate"),
    ("Average Wait Minutes", "avg_wait_minutes", "minutes"),
    ("Average Visit Minutes", "avg_visit_minutes", "minutes"),
    ("Available Slots", "available_slots", "count"),
    ("Booking Rate", "booking_rate", "rate"),
    ("Completed Slot Utilization", "completed_slot_utilization", "rate"),
]
POWERBI_FORMATS = {"count": "Whole number, thousands separator (#,0)",
                   "rate": "Percentage, 1 decimal (0.0%)",
                   "minutes": "Decimal number, 1 decimal (0.0)"}


class PowerBIExportError(Exception):
    """The snapshot failed a check. The message lists every problem found."""


# --- Step 2: read the tables and build the Date table ---------------------------------

def read_tables(database_path):
    """Each file name -> {"columns": [...], "rows": [tuple, ...]} straight from SQLite."""
    tables = {}
    with closing(sqlite3.connect(database_path)) as connection:
        for file_name, query in TABLE_QUERIES.items():
            cursor = connection.execute(query)
            tables[file_name] = {"columns": [d[0] for d in cursor.description],
                                 "rows": cursor.fetchall()}
    return tables


def column_values(table, column):
    index = table["columns"].index(column)
    return [row[index] for row in table["rows"]]


def build_date_table(tables):
    """One row per calendar day, from 1 January of the first year used by appointments
    or schedules to 31 December of the last year (whole years suit Power BI's time
    intelligence functions such as DATEADD)."""
    used_dates = (column_values(tables["appointments.csv"], "appointment_date")
                  + column_values(tables["provider_schedules.csv"], "schedule_date"))
    first_year = date.fromisoformat(min(used_dates)).year
    last_year = date.fromisoformat(max(used_dates)).year

    rows = []
    day = date(first_year, 1, 1)
    while day <= date(last_year, 12, 31):
        rows.append((
            day.isoformat(),                       # date
            day.year,                              # year
            (day.month - 1) // 3 + 1,              # quarter (1-4)
            day.month,                             # month_number
            MONTH_NAMES[day.month - 1],            # month_name
            f"{MONTH_NAMES[day.month - 1][:3]} {day.year}",   # year_month, e.g. "Jan 2025"
            day.year * 100 + day.month,            # year_month_sort, e.g. 202501
            day.isoweekday(),                      # weekday_number: Monday = 1 ... Sunday = 7
            WEEKDAY_NAMES[day.weekday()],          # weekday_name
            day.isoweekday() >= 6,                 # is_weekend
        ))
        day += timedelta(days=1)
    return {"columns": DATE_COLUMNS, "rows": rows}


# --- Step 3: validate --------------------------------------------------------------------

def validate(tables):
    """Check keys before anything is written. Raises PowerBIExportError on any problem."""
    problems = []

    for file_name, key_columns in PRIMARY_KEYS.items():
        table = tables[file_name]
        if not table["rows"]:
            problems.append(f"{file_name} has no rows")
        indexes = [table["columns"].index(column) for column in key_columns]
        keys = [tuple(row[i] for i in indexes) for row in table["rows"]]
        duplicates = len(keys) - len(set(keys))
        if duplicates:
            problems.append(f"{file_name}: {duplicates} duplicate {'/'.join(key_columns)}")

    for child, child_column, parent, parent_column in FOREIGN_KEYS:
        parent_values = set(column_values(tables[parent], parent_column))
        missing = [v for v in column_values(tables[child], child_column)
                   if v not in parent_values]
        if missing:
            problems.append(f"{child}.{child_column}: {len(missing)} value(s) not found in "
                            f"{parent}.{parent_column}, e.g. {missing[:3]}")

    # Power BI filters department through Providers, so each appointment and schedule
    # row must carry the same department as its provider.
    provider_department = dict(zip(column_values(tables["providers.csv"], "provider_id"),
                                   column_values(tables["providers.csv"], "department_id")))
    for file_name in ["appointments.csv", "provider_schedules.csv"]:
        table = tables[file_name]
        pairs = zip(column_values(table, "provider_id"), column_values(table, "department_id"))
        mismatched = sum(1 for provider, department in pairs
                         if provider in provider_department
                         and provider_department[provider] != department)
        if mismatched:
            problems.append(f"{file_name}: {mismatched} row(s) whose department_id differs "
                            "from the provider's department")

    if problems:
        raise PowerBIExportError("The Power BI snapshot was not written:\n- "
                                 + "\n- ".join(problems))


# --- Step 4: write ---------------------------------------------------------------------

def write_csv(path, table):
    """Plain CSV with "\\n" line endings. Missing values (NULL) become empty cells."""
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(table["columns"])
        writer.writerows(table["rows"])


def display_value(value, kind):
    """How the value should look on a Power BI card with the documented format."""
    if value is None:
        return "(blank)"
    if kind == "count":
        return f"{value:,}"
    if kind == "rate":
        return f"{value:.1%}"
    return f"{value:.1f}"


def build_expected_kpis(overall, tables):
    """Reference values for the dashboard with no slicers applied, taken from SQL."""
    kpis = {}
    for name, column, kind in EXPECTED_KPIS:
        value = analyze_data.plain_number(overall[column])
        kpis[name] = {"value": value, "display": display_value(value, kind),
                      "power_bi_format": POWERBI_FORMATS[kind]}
    return {
        "synthetic_data": True,
        "description": ("Reference KPI values for checking the Power BI dashboard with no "
                        "slicers or filters applied. Calculated by the SQL view "
                        "vw_overall_kpis (sql/02_create_analytics_views.sql). All data is "
                        "synthetic."),
        "dataset": {
            "note": ("Values come from the database that was current when "
                     "prepare_powerbi_data.py ran. The README workflow creates it with: "
                     "python generate_data.py --appointments 5000 --seed 42"),
            "row_counts": {name: len(tables[name]["rows"]) for name in POWERBI_FILES},
        },
        "reporting_period": {"start": overall["period_start"], "end": overall["period_end"]},
        "kpis": kpis,
    }


def write_expected_kpis(path, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


# --- Step 5: reconcile the written files with SQLite ---------------------------------

def read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def reconcile(output_dir, database_path, overall, date_rows):
    """Read the CSV files back and compare them with the database. Returns the checks."""
    checks = []

    def add(check, expected, actual, tolerance=0.0):
        passed = (expected == actual if tolerance == 0
                  else math.isclose(expected, actual, abs_tol=tolerance))
        checks.append({"check": check, "expected": expected, "actual": actual,
                       "passed": passed})

    files = {name: read_csv_rows(output_dir / name) for name in POWERBI_FILES}
    with closing(sqlite3.connect(database_path)) as connection:
        for name in TABLE_QUERIES:
            table = Path(name).stem
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            add(f"{name} rows = SQLite {table} rows", count, len(files[name]))
    add(f"{DATE_FILE} rows = calendar days", date_rows, len(files[DATE_FILE]))

    # Headline KPIs worked out from the CSV files must equal the SQL view.
    appointments = files["appointments.csv"]
    completed = [row for row in appointments if row["appointment_status"] == "Completed"]
    add("Total Appointments", overall["total_appointments"], len(appointments))
    add("Unique Patients", overall["unique_patients"],
        len({row["patient_id"] for row in appointments}))
    for status, column in [("Completed", "completed_appointments"),
                           ("Cancelled", "cancelled_appointments"),
                           ("No Show", "no_show_appointments")]:
        add(f"{status} Appointments", overall[column],
            sum(row["appointment_status"] == status for row in appointments))
    for kpi, column, field in [("Average Wait Minutes", "avg_wait_minutes", "wait_minutes"),
                               ("Average Visit Minutes", "avg_visit_minutes", "visit_minutes")]:
        values = [int(row[field]) for row in completed]
        add(kpi, overall[column], sum(values) / len(values) if values else None, 1e-9)
    add("Available Slots", overall["available_slots"],
        sum(int(row["available_slots"]) for row in files["provider_schedules.csv"]))

    failed = [c for c in checks if not c["passed"]]
    if failed:
        raise PowerBIExportError("The written snapshot does not match SQLite:\n- " + "\n- ".join(
            f"{c['check']}: expected {c['expected']}, got {c['actual']}" for c in failed))
    return checks


# --- Putting it together ---------------------------------------------------------------

def build_package(database_path=config.DATABASE_FILE, output_dir=config.POWERBI_DATA_DIR,
                  expected_kpis_path=config.EXPECTED_KPIS_FILE):
    """Create the Power BI snapshot. Returns (tables, expected KPIs, reconciliation checks)."""
    results, _analytics_checks = analyze_data.load_analytics(database_path)
    overall = results["overall_kpis"].iloc[0].to_dict()

    tables = read_tables(database_path)
    tables[DATE_FILE] = build_date_table(tables)
    validate(tables)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in POWERBI_FILES:
        write_csv(output_dir / name, tables[name])
    expected = build_expected_kpis(overall, tables)
    write_expected_kpis(Path(expected_kpis_path), expected)

    checks = reconcile(output_dir, database_path, overall, len(tables[DATE_FILE]["rows"]))
    return tables, expected, checks


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export the synthetic data as a Power BI snapshot (CSV files).")
    parser.add_argument("--database", default=str(config.DATABASE_FILE),
                        help="SQLite database (default data/processed/healthcare_analytics.db)")
    parser.add_argument("--output-dir", default=str(config.POWERBI_DATA_DIR),
                        help="folder for the Power BI CSV files (default powerbi/data)")
    parser.add_argument("--expected-kpis", default=str(config.EXPECTED_KPIS_FILE),
                        help="reference KPI file (default powerbi/expected_kpis.json)")
    args = parser.parse_args(argv)

    try:
        tables, expected, checks = build_package(args.database, args.output_dir,
                                                 args.expected_kpis)
    except (FileNotFoundError, PowerBIExportError, analyze_data.AnalyticsError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    dates = column_values(tables[DATE_FILE], "date")
    print("Power BI snapshot created (SYNTHETIC data).")
    print(f"  Folder: {Path(args.output_dir).resolve()}")
    for name in POWERBI_FILES:
        print(f"    {name:<24} {len(tables[name]['rows']):>7,} rows")
    print(f"  Date table: {dates[0]} to {dates[-1]}")
    print(f"  Reconciliation with SQLite: {len(checks)} of {len(checks)} checks passed")
    print(f"  Reference KPIs: {Path(args.expected_kpis).resolve()}")
    print("  Next: build the dashboard by hand, following powerbi/POWER_BI_BUILD_GUIDE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
