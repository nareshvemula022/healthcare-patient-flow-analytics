"""Phase 2: clean and validate the SYNTHETIC CSV files, then load them into SQLite.

All data is fictional. Run this after generate_data.py (PowerShell):
    python prepare_data.py

Reads   data/raw/*.csv
Writes  data/processed/*.csv                       cleaned tables
        data/processed/healthcare_analytics.db     SQLite database
        data/output/phase2_data_quality.json       data-quality report

The only automatic fix is removing spaces around values. Any other problem
stops the pipeline with a clear message and a "failed" report. In that case,
data/processed is not changed.
"""

import argparse
import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

import config

# Tables in load order: each table comes after the tables it refers to.
TABLES = ["departments", "providers", "patients", "provider_schedules", "appointments"]

PRIMARY_KEYS = {
    "departments": ["department_id"],
    "providers": ["provider_id"],
    "patients": ["patient_id"],
    "provider_schedules": ["schedule_date", "provider_id"],
    "appointments": ["appointment_id"],
}

# (child table, child columns, parent table, parent columns)
FOREIGN_KEYS = [
    ("providers", ["department_id"], "departments", ["department_id"]),
    ("provider_schedules", ["provider_id"], "providers", ["provider_id"]),
    ("provider_schedules", ["department_id"], "departments", ["department_id"]),
    ("appointments", ["patient_id"], "patients", ["patient_id"]),
    ("appointments", ["provider_id"], "providers", ["provider_id"]),
    ("appointments", ["department_id"], "departments", ["department_id"]),
    ("appointments", ["appointment_date", "provider_id"],
     "provider_schedules", ["schedule_date", "provider_id"]),
]

# Raw appointment times that stay blank unless the visit was completed.
VISIT_TIME_COLUMNS = ["check_in_time", "seen_time", "checkout_time"]
VALID_STATUSES = ["Completed", "Cancelled", "No Show"]
VALID_TYPES = list(config.APPOINTMENT_TYPES)
MAX_AGE = 120
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Processed appointments: the raw HH:MM times become full datetimes plus durations.
PROCESSED_APPOINTMENT_COLUMNS = [
    "appointment_id", "patient_id", "provider_id", "department_id", "appointment_date",
    "scheduled_datetime", "check_in_datetime", "seen_datetime", "checkout_datetime",
    "wait_minutes", "visit_minutes", "appointment_type", "appointment_status",
]

DATA_NOTICE = ("All records are synthetic, created by generate_data.py. They do not describe "
               "real patients, providers, hospitals or clinics.")


class DataValidationError(Exception):
    """The raw data breaks a rule. The message lists every problem found."""


# --- Step 1: read -----------------------------------------------------------

def read_raw_tables(raw_dir):
    """Read the five raw CSV files as text, with surrounding spaces removed."""
    raw_dir = Path(raw_dir)
    missing = [f"{table}.csv" for table in TABLES if not (raw_dir / f"{table}.csv").exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing raw data file(s) in {raw_dir}: {', '.join(missing)}\n"
            "Create them first by running:\n"
            "    python generate_data.py --appointments 5000 --seed 42"
        )

    tables = {}
    for table in TABLES:
        # dtype=str and keep_default_na=False: every value is text, blank cells are "".
        df = pd.read_csv(raw_dir / f"{table}.csv", dtype=str, keep_default_na=False)
        df.columns = df.columns.str.strip()
        tables[table] = df.apply(lambda column: column.str.strip())
    return tables


def check_required_columns(tables):
    problems = []
    for table in TABLES:
        missing = [column for column in config.OUTPUT_COLUMNS[f"{table}.csv"]
                   if column not in tables[table].columns]
        if missing:
            problems.append(f"{table}.csv is missing required column(s): {', '.join(missing)}")
    if problems:
        raise DataValidationError("\n".join(problems))


# --- Step 2: build datetimes ---------------------------------------------------

def parse_datetime(dates, times):
    """Combine "YYYY-MM-DD" and "HH:MM" text into datetimes. Blank or invalid gives NaT."""
    return pd.to_datetime(dates + " " + times, format="%Y-%m-%d %H:%M", errors="coerce")


def add_appointment_datetimes(appointments):
    result = appointments.copy()
    dates = result["appointment_date"]
    result["scheduled_datetime"] = parse_datetime(dates, result["scheduled_time"])
    result["check_in_datetime"] = parse_datetime(dates, result["check_in_time"])
    result["seen_datetime"] = parse_datetime(dates, result["seen_time"])
    result["checkout_datetime"] = parse_datetime(dates, result["checkout_time"])
    return result


# --- Step 3: validate -------------------------------------------------------

def to_whole_numbers(values):
    """Convert text such as "12" to numbers. Blank, "-3", "2.5" or "abc" become NaN."""
    is_whole_number = values.str.fullmatch(r"\d+")
    return pd.to_numeric(values.where(is_whole_number), errors="coerce")


def expected_age_group(age):
    """The age group an age belongs to, e.g. 40 -> "35-49" (None if age is missing)."""
    group_for_age = None
    for group, (_share, (lowest_age, _highest_age)) in config.AGE_GROUPS.items():
        if age >= lowest_age:
            group_for_age = group
    return group_for_age


def lookup(table, key_column, value_column):
    """A provider_id -> value lookup that ignores duplicate keys (reported separately)."""
    return table.drop_duplicates(key_column).set_index(key_column)[value_column]


def department_mismatch(rows, provider_department):
    """True where department_id differs from the provider's department.
    Unknown providers are skipped here because the foreign-key check reports them."""
    expected = rows["provider_id"].map(provider_department)
    return expected.notna() & (expected != rows["department_id"])


def row_labels(table, df, bad_rows, limit=5):
    """Primary-key values of the first few rows that break a rule, for error messages."""
    keys = df.loc[bad_rows, PRIMARY_KEYS[table]].head(limit)
    return ["/".join(values) for values in keys.itertuples(index=False, name=None)]


def run_checks(tables):
    """Apply every rule. Returns one result per rule, including rules with 0 problems."""
    results = []

    def record(section, table, rule, bad_rows, count=None):
        # bad_rows is True for each row that breaks the rule.
        results.append({
            "section": section,
            "table": table,
            "rule": rule,
            "count": int(bad_rows.sum()) if count is None else int(count),
            "examples": row_labels(table, tables[table], bad_rows),
        })

    # Unique primary keys.
    for table in TABLES:
        duplicated = tables[table].duplicated(PRIMARY_KEYS[table])
        record("duplicate_primary_keys", table, "primary key must be unique", duplicated)

    # Required values must not be blank (visit times may be blank, see below).
    for table in TABLES:
        required = [column for column in config.OUTPUT_COLUMNS[f"{table}.csv"]
                    if column not in VISIT_TIME_COLUMNS]
        blank_cells = tables[table][required] == ""
        record("missing_required_values", table, "required values must not be blank",
               blank_cells.any(axis=1), count=blank_cells.sum().sum())

    # Foreign keys: every value must exist in the parent table.
    for child, child_columns, parent, parent_columns in FOREIGN_KEYS:
        parent_keys = set(tables[parent][parent_columns].itertuples(index=False, name=None))
        child_keys = tables[child][child_columns].itertuples(index=False, name=None)
        not_found = pd.Series([key not in parent_keys for key in child_keys],
                              index=tables[child].index, dtype=bool)
        rule = (f"{child}.({', '.join(child_columns)}) -> "
                f"{parent}.({', '.join(parent_columns)})")
        record("foreign_key_violations", child, rule, not_found)

    providers = tables["providers"]
    patients = tables["patients"]
    schedules = tables["provider_schedules"]
    appointments = tables["appointments"]
    provider_department = lookup(providers, "provider_id", "department_id")

    # Providers.
    capacity = to_whole_numbers(providers["daily_slot_capacity"])
    record("rule_violations", "providers", "daily_slot_capacity must be a positive whole number",
           capacity.isna() | (capacity <= 0))

    # Patients.
    ages = to_whole_numbers(patients["age"])
    valid_age = ages.notna() & (ages <= MAX_AGE)
    record("rule_violations", "patients", f"age must be a whole number from 0 to {MAX_AGE}",
           ~valid_age)
    record("rule_violations", "patients", "age_group must match age",
           valid_age & (patients["age_group"] != ages.map(expected_age_group)))

    # Provider schedules.
    schedule_dates = pd.to_datetime(schedules["schedule_date"], format="%Y-%m-%d", errors="coerce")
    record("rule_violations", "provider_schedules", "schedule_date must be a YYYY-MM-DD date",
           schedule_dates.isna())
    slots = to_whole_numbers(schedules["available_slots"])
    record("rule_violations", "provider_schedules",
           "available_slots must be a whole number (0 or more)", slots.isna())
    provider_capacity = to_whole_numbers(lookup(providers, "provider_id", "daily_slot_capacity"))
    record("rule_violations", "provider_schedules",
           "available_slots must not exceed the provider's daily_slot_capacity",
           slots > schedules["provider_id"].map(provider_capacity))
    record("rule_violations", "provider_schedules",
           "department_id must match the provider's department",
           department_mismatch(schedules, provider_department))
    booked = (appointments.groupby(["appointment_date", "provider_id"]).size()
              .rename("booked").reset_index()
              .rename(columns={"appointment_date": "schedule_date"}))
    booked_per_day = schedules.merge(booked, on=["schedule_date", "provider_id"], how="left")
    record("rule_violations", "provider_schedules",
           "booked appointments must not exceed available_slots",
           pd.Series(booked_per_day["booked"].fillna(0).to_numpy() > slots.to_numpy(),
                     index=schedules.index))

    # Appointments.
    status = appointments["appointment_status"]
    record("rule_violations", "appointments",
           "appointment_date and scheduled_time must be a valid date and HH:MM time",
           appointments["scheduled_datetime"].isna())
    record("rule_violations", "appointments",
           f"appointment_status must be one of: {', '.join(VALID_STATUSES)}",
           ~status.isin(VALID_STATUSES))
    record("rule_violations", "appointments",
           f"appointment_type must be one of: {', '.join(VALID_TYPES)}",
           ~appointments["appointment_type"].isin(VALID_TYPES))
    record("rule_violations", "appointments",
           "department_id must match the provider's department",
           department_mismatch(appointments, provider_department))

    completed = status == "Completed"
    check_in = appointments["check_in_datetime"]
    seen = appointments["seen_datetime"]
    checkout = appointments["checkout_datetime"]
    record("rule_violations", "appointments",
           "Completed appointments need valid check-in, seen and checkout times (HH:MM)",
           completed & (check_in.isna() | seen.isna() | checkout.isna()))
    record("rule_violations", "appointments",
           "Completed appointments need check-in <= seen <= checkout",
           completed & ((check_in > seen) | (seen > checkout)))
    record("rule_violations", "appointments",
           "Cancelled and No Show appointments must have blank check-in, seen and checkout times",
           status.isin(["Cancelled", "No Show"])
           & (appointments[VISIT_TIME_COLUMNS] != "").any(axis=1))

    return results


def describe_problems(results):
    """Turn every failed rule into a readable line for the error message."""
    lines = []
    for result in results:
        if result["count"] > 0:
            examples = ", ".join(result["examples"])
            lines.append(f"- {result['table']}.csv: {result['rule']} "
                         f"({result['count']} problem(s), e.g. {examples})")
    return lines


# --- Step 4: clean ----------------------------------------------------------

def build_clean_tables(tables):
    """Tables with proper number types, datetimes and durations, sorted by primary key."""
    clean = {}
    for table in ["departments", "providers", "patients", "provider_schedules"]:
        clean[table] = tables[table][config.OUTPUT_COLUMNS[f"{table}.csv"]].copy()
    clean["providers"]["daily_slot_capacity"] = pd.to_numeric(
        clean["providers"]["daily_slot_capacity"])
    clean["patients"]["age"] = pd.to_numeric(clean["patients"]["age"])
    clean["provider_schedules"]["available_slots"] = pd.to_numeric(
        clean["provider_schedules"]["available_slots"])

    raw = tables["appointments"]
    completed = raw["appointment_status"] == "Completed"
    appointments = raw[["appointment_id", "patient_id", "provider_id", "department_id",
                        "appointment_date", "appointment_type", "appointment_status"]].copy()
    for column in ["scheduled_datetime", "check_in_datetime", "seen_datetime",
                   "checkout_datetime"]:
        appointments[column] = raw[column].dt.strftime(DATETIME_FORMAT)  # missing stays blank

    # Durations in whole minutes, only for Completed appointments.
    wait = (raw["seen_datetime"] - raw["check_in_datetime"]).dt.total_seconds() / 60
    visit = (raw["checkout_datetime"] - raw["seen_datetime"]).dt.total_seconds() / 60
    appointments["wait_minutes"] = wait.where(completed).round().astype("Int64")
    appointments["visit_minutes"] = visit.where(completed).round().astype("Int64")
    clean["appointments"] = appointments[PROCESSED_APPOINTMENT_COLUMNS]

    for table in TABLES:
        clean[table] = clean[table].sort_values(PRIMARY_KEYS[table]).reset_index(drop=True)
    return clean


def write_processed_csvs(clean, processed_dir):
    processed_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        clean[table].to_csv(processed_dir / f"{table}.csv", index=False)


# --- Step 5: SQLite ----------------------------------------------------------

def load_csv_into_table(connection, table, csv_path):
    """Insert every row of a processed CSV file. Blank cells become NULL."""
    with open(csv_path, newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        columns = next(reader)
        rows = [[value if value != "" else None for value in row] for row in reader]
    placeholders = ", ".join("?" for _column in columns)
    connection.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows)
    return len(rows)


def build_database(processed_dir, database_path, schema_path):
    """(Re)create the database from the schema file and load the processed CSV files."""
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(Path(schema_path).read_text(encoding="utf-8"))

        csv_row_counts = {}
        with connection:  # one transaction: commit if everything loads, otherwise undo
            for table in TABLES:
                csv_row_counts[table] = load_csv_into_table(
                    connection, table, processed_dir / f"{table}.csv")

        database_row_counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
        foreign_key_problems = connection.execute("PRAGMA foreign_key_check").fetchall()

    if database_row_counts != csv_row_counts:
        raise DataValidationError(
            f"Database row counts {database_row_counts} do not match CSV row counts "
            f"{csv_row_counts}")
    if foreign_key_problems:
        raise DataValidationError(
            f"SQLite foreign_key_check found {len(foreign_key_problems)} problem(s), "
            f"e.g. {foreign_key_problems[:5]}")
    return csv_row_counts, database_row_counts


# --- Step 6: report ---------------------------------------------------------

def minutes_summary(values):
    values = values.dropna()
    if values.empty:
        return {"min": None, "max": None, "average": None}
    return {"min": int(values.min()), "max": int(values.max()),
            "average": round(float(values.mean()), 2)}


def check_sections(results):
    """Group the rule results into the report sections."""
    sections = {"duplicate_primary_keys": {}, "missing_required_values": {},
                "foreign_key_violations": {}, "rule_violations": {}}
    for result in results:
        if result["section"] in ("duplicate_primary_keys", "missing_required_values"):
            name = result["table"]
        elif result["section"] == "foreign_key_violations":
            name = result["rule"]
        else:
            name = f"{result['table']}: {result['rule']}"
        sections[result["section"]][name] = result["count"]
    return sections


def write_report(report, report_path):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


# --- Putting it together ------------------------------------------------------

def run_pipeline(raw_dir=config.RAW_DATA_DIR, processed_dir=config.PROCESSED_DATA_DIR,
                 output_dir=config.OUTPUT_DATA_DIR, schema_path=config.SCHEMA_FILE):
    """Run every step and return the data-quality report (also saved as JSON)."""
    processed_dir = Path(processed_dir)
    report_path = Path(output_dir) / config.QUALITY_REPORT_FILE_NAME

    tables = read_raw_tables(raw_dir)
    report = {
        "pipeline_status": "failed",
        "synthetic_data": True,
        "data_notice": DATA_NOTICE,
        "raw_row_counts": {table: len(tables[table]) for table in TABLES},
    }

    try:
        check_required_columns(tables)
        tables["appointments"] = add_appointment_datetimes(tables["appointments"])
        results = run_checks(tables)
        report.update(check_sections(results))
        problems = describe_problems(results)
        if problems:
            raise DataValidationError(
                "The raw data failed validation, so no processed files were written.\n"
                + "\n".join(problems))

        clean = build_clean_tables(tables)
        write_processed_csvs(clean, processed_dir)
        csv_counts, database_counts = build_database(
            processed_dir, processed_dir / config.DATABASE_FILE_NAME, schema_path)
    except DataValidationError as error:
        report["errors"] = str(error).splitlines()
        write_report(report, report_path)
        raise

    appointments = clean["appointments"]
    completed = appointments[appointments["appointment_status"] == "Completed"]
    status_counts = appointments["appointment_status"].value_counts()
    report.update({
        "pipeline_status": "passed",
        "processed_csv_row_counts": csv_counts,
        "database_file": config.DATABASE_FILE_NAME,
        "database_row_counts": database_counts,
        "database_matches_csv_row_counts": database_counts == csv_counts,
        "sqlite_foreign_key_check": {"passed": True, "violations": 0},
        "appointment_status_counts": {s: int(status_counts.get(s, 0)) for s in VALID_STATUSES},
        "completed_appointments": len(completed),
        "wait_minutes": minutes_summary(completed["wait_minutes"]),
        "visit_minutes": minutes_summary(completed["visit_minutes"]),
        "errors": [],
    })
    write_report(report, report_path)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Clean and validate the synthetic CSV files and load them into SQLite.")
    parser.add_argument("--raw-dir", default=str(config.RAW_DATA_DIR),
                        help="folder with the raw CSV files (default data/raw)")
    parser.add_argument("--processed-dir", default=str(config.PROCESSED_DATA_DIR),
                        help="folder for cleaned CSV files and the database (default data/processed)")
    parser.add_argument("--output-dir", default=str(config.OUTPUT_DATA_DIR),
                        help="folder for the data-quality report (default data/output)")
    args = parser.parse_args(argv)

    try:
        report = run_pipeline(args.raw_dir, args.processed_dir, args.output_dir)
    except (FileNotFoundError, DataValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    processed_dir = Path(args.processed_dir).resolve()
    print("Phase 2 pipeline passed (SYNTHETIC data).")
    print(f"  Cleaned CSV files: {processed_dir}")
    print(f"  SQLite database:   {processed_dir / config.DATABASE_FILE_NAME}")
    print(f"  Quality report:    "
          f"{Path(args.output_dir).resolve() / config.QUALITY_REPORT_FILE_NAME}")
    for table, count in report["database_row_counts"].items():
        print(f"  {table:<20} {count:>7,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
