"""Phase 4A checks for the Power BI data package, theme, DAX file and documents.

What Python can check: the CSV snapshot, the reference KPIs, and that the theme, DAX and
guides contain what they should. What it cannot check: opening the .pbix file, running
DAX or rendering visuals. Those are manual steps in
powerbi/POWER_BI_VERIFICATION_CHECKLIST.md.
"""

import calendar
import csv
import json
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import date, timedelta

import pytest

import analyze_data
import config
import prepare_powerbi_data
from conftest import PROJECT_ROOT
from prepare_powerbi_data import PowerBIExportError

POWERBI = PROJECT_ROOT / "powerbi"
EXPECTED_COLUMNS = {
    "appointments.csv": ["appointment_id", "patient_id", "provider_id", "department_id",
                         "appointment_date", "scheduled_datetime", "check_in_datetime",
                         "seen_datetime", "checkout_datetime", "wait_minutes",
                         "visit_minutes", "appointment_type", "appointment_status"],
    "provider_schedules.csv": ["schedule_date", "provider_id", "department_id",
                               "available_slots"],
    "providers.csv": ["provider_id", "department_id", "provider_name", "specialty",
                      "daily_slot_capacity"],
    "departments.csv": ["department_id", "department_name"],
    "patients.csv": ["patient_id", "age", "age_group", "gender", "city", "insurance_type"],
    "date.csv": ["date", "year", "quarter", "month_number", "month_name", "year_month",
                 "year_month_sort", "weekday_number", "weekday_name", "is_weekend"],
}
POWERBI_TABLES = {"appointments.csv": "Appointments",
                  "provider_schedules.csv": "ProviderSchedules",
                  "providers.csv": "Providers", "departments.csv": "Departments",
                  "patients.csv": "Patients", "date.csv": "Date"}
RELATIONSHIPS = ["`Date[date]` | `Appointments[appointment_date]`",
                 "`Date[date]` | `ProviderSchedules[schedule_date]`",
                 "`Departments[department_id]` | `Providers[department_id]`",
                 "`Providers[provider_id]` | `Appointments[provider_id]`",
                 "`Providers[provider_id]` | `ProviderSchedules[provider_id]`",
                 "`Patients[patient_id]` | `Appointments[patient_id]`"]
KPI_COLUMNS = {
    "Total Appointments": "total_appointments", "Unique Patients": "unique_patients",
    "Completed Appointments": "completed_appointments",
    "Cancelled Appointments": "cancelled_appointments",
    "No Show Appointments": "no_show_appointments", "Completion Rate": "completion_rate",
    "Cancellation Rate": "cancellation_rate", "No Show Rate": "no_show_rate",
    "Average Wait Minutes": "avg_wait_minutes", "Average Visit Minutes": "avg_visit_minutes",
    "Available Slots": "available_slots", "Booking Rate": "booking_rate",
    "Completed Slot Utilization": "completed_slot_utilization",
}
DAX_MEASURES = [*KPI_COLUMNS, "Previous Month Appointments", "Month over Month Change",
                "Month over Month Change Percent"]
DATE = r"\d{4}-\d{2}-\d{2}"
DATETIME = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
# Phase 4B artifacts, created by hand in Power BI Desktop.
PBIX = POWERBI / "healthcare_patient_flow_dashboard.pbix"
SCREENSHOTS = ["powerbi_operational_overview.png",
               "powerbi_capacity_provider_performance.png",
               "powerbi_patient_appointment_patterns.png"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"     # the IEND chunk type and its fixed checksum


# --- Fixtures and helpers -------------------------------------------------------------

@pytest.fixture(scope="session")
def package(prepared_data, tmp_path_factory):
    """The Power BI snapshot built from the small test database."""
    base = tmp_path_factory.mktemp("powerbi")
    tables, expected, checks = prepare_powerbi_data.build_package(
        prepared_data["database"], base / "data", base / "expected_kpis.json")
    files = {name: read_csv(base / "data" / name) for name in EXPECTED_COLUMNS}
    return {"base": base, "dir": base / "data", "expected": expected, "checks": checks,
            "files": files, "database": prepared_data["database"]}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def query(database, sql):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(sql).fetchall()


def git_is_ignored(relative_path):
    result = subprocess.run(["git", "check-ignore", "-q", relative_path], cwd=PROJECT_ROOT)
    return result.returncode == 0


def requires_git():
    if shutil.which("git") is None or not (PROJECT_ROOT / ".git").exists():
        pytest.skip("git repository not available")


def read_text(name):
    return (POWERBI / name).read_text(encoding="utf-8")


def dax_measures():
    """Measure name -> {"format": format comment, "body": expression without comments}."""
    lines = read_text("dax_measures.txt").splitlines()
    measures, name = {}, None
    for index, line in enumerate(lines):
        header = re.fullmatch(r"([A-Za-z][A-Za-z ]*[A-Za-z]) =", line.strip())
        if header and not line.startswith("//"):
            name = header.group(1)
            previous = lines[index - 1] if index else ""
            measures[name] = {"format": previous if previous.startswith("// Format:") else "",
                              "body": ""}
        elif name and line.strip() == "":
            name = None
        elif name and not line.strip().startswith("//"):
            measures[name]["body"] += line + "\n"
    return measures


# --- CSV snapshot -----------------------------------------------------------------------

def test_six_csv_files_are_created(package):
    assert sorted(path.name for path in package["dir"].glob("*.csv")) == sorted(EXPECTED_COLUMNS)


def test_required_columns(package):
    for name, columns in EXPECTED_COLUMNS.items():
        with open(package["dir"] / name, newline="", encoding="utf-8") as file:
            assert next(csv.reader(file)) == columns, name


def test_row_counts_match_sqlite(package):
    for name, rows in package["files"].items():
        if name == "date.csv":
            continue
        table = name.removesuffix(".csv")
        assert len(rows) == query(package["database"], f"SELECT COUNT(*) FROM {table}")[0][0]
    assert package["expected"]["dataset"]["row_counts"] == {
        name: len(rows) for name, rows in package["files"].items()}


def test_reconciliation_checks_passed(package):
    assert len(package["checks"]) > 0
    assert all(check["passed"] for check in package["checks"])


def test_foreign_keys_are_valid(package):
    files = package["files"]

    def keys(name, column):
        return {row[column] for row in files[name]}

    for child, column, parent, parent_column in prepare_powerbi_data.FOREIGN_KEYS:
        assert keys(child, column) <= keys(parent, parent_column), (child, column)
    provider_department = {row["provider_id"]: row["department_id"]
                           for row in files["providers.csv"]}
    for name in ["appointments.csv", "provider_schedules.csv"]:
        assert all(provider_department[row["provider_id"]] == row["department_id"]
                   for row in files[name]), name


def test_ids_are_text_and_dates_are_iso(package):
    files = package["files"]
    assert all(re.fullmatch(r"APT\d{6}", r["appointment_id"]) for r in files["appointments.csv"])
    assert all(re.fullmatch(r"PAT\d{5}", r["patient_id"]) for r in files["patients.csv"])
    assert all(re.fullmatch(r"PRV\d{3}", r["provider_id"]) for r in files["providers.csv"])
    assert all(re.fullmatch(r"DEP\d{2}", r["department_id"]) for r in files["departments.csv"])
    assert all(re.fullmatch(DATE, r["schedule_date"]) for r in files["provider_schedules.csv"])
    for row in files["appointments.csv"]:
        assert re.fullmatch(DATE, row["appointment_date"])
        assert re.fullmatch(DATETIME, row["scheduled_datetime"])


def test_blank_values_are_kept_for_non_completed_appointments(package):
    visit_fields = ["check_in_datetime", "seen_datetime", "checkout_datetime",
                    "wait_minutes", "visit_minutes"]
    for row in package["files"]["appointments.csv"]:
        if row["appointment_status"] == "Completed":
            assert all(row[f] != "" for f in visit_fields)
            assert re.fullmatch(DATETIME, row["check_in_datetime"])
            assert re.fullmatch(r"\d+", row["wait_minutes"])     # whole minutes, no ".0"
        else:
            assert all(row[f] == "" for f in visit_fields)


# --- Date table --------------------------------------------------------------------------

def test_date_table_has_one_row_per_day_without_gaps(package):
    dates = [date.fromisoformat(row["date"]) for row in package["files"]["date.csv"]]
    assert dates[0] == date(dates[0].year, 1, 1)
    assert dates[-1] == date(dates[-1].year, 12, 31)
    assert all(later - earlier == timedelta(days=1) for earlier, later in zip(dates, dates[1:]))

    used = ([row["appointment_date"] for row in package["files"]["appointments.csv"]]
            + [row["schedule_date"] for row in package["files"]["provider_schedules.csv"]])
    assert dates[0].isoformat() <= min(used) and max(used) <= dates[-1].isoformat()


def test_date_attributes(package):
    for row in package["files"]["date.csv"]:
        day = date.fromisoformat(row["date"])
        assert int(row["year"]) == day.year
        assert int(row["quarter"]) == (day.month + 2) // 3
        assert int(row["month_number"]) == day.month
        assert row["month_name"] == calendar.month_name[day.month]
        assert row["year_month"] == f"{calendar.month_abbr[day.month]} {day.year}"
        assert int(row["year_month_sort"]) == day.year * 100 + day.month
        assert int(row["weekday_number"]) == day.isoweekday()     # Monday = 1
        assert row["weekday_name"] == calendar.day_name[day.weekday()]
        assert row["is_weekend"] == str(day.isoweekday() >= 6)


def test_sort_columns_give_calendar_order(package):
    rows = package["files"]["date.csv"]
    months = sorted({(int(r["year_month_sort"]), r["year_month"]) for r in rows})
    assert [label for _sort, label in months][:3] == ["Jan 2025", "Feb 2025", "Mar 2025"]
    weekdays = dict(sorted({(int(r["weekday_number"]), r["weekday_name"]) for r in rows}))
    assert weekdays == {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
                        5: "Friday", 6: "Saturday", 7: "Sunday"}
    names = dict(sorted({(int(r["month_number"]), r["month_name"]) for r in rows}))
    assert names[1] == "January" and names[12] == "December"


# --- Determinism, Git, errors ----------------------------------------------------------

def test_snapshot_is_deterministic(package, tmp_path):
    prepare_powerbi_data.build_package(package["database"], tmp_path / "data",
                                       tmp_path / "expected_kpis.json")
    for name in EXPECTED_COLUMNS:
        assert (tmp_path / "data" / name).read_bytes() == (package["dir"] / name).read_bytes()
    assert ((tmp_path / "expected_kpis.json").read_bytes()
            == (package["base"] / "expected_kpis.json").read_bytes())


def test_powerbi_assets_are_not_ignored_by_git():
    requires_git()
    for path in [*(f"powerbi/data/{name}" for name in EXPECTED_COLUMNS),
                 "powerbi/expected_kpis.json", "powerbi/healthcare_patient_flow_dashboard.pbix",
                 *(f"screenshots/{name}" for name in SCREENSHOTS)]:
        assert not git_is_ignored(path), path


def test_invalid_foreign_key_stops_the_export(package, tmp_path):
    database = tmp_path / "broken.db"
    shutil.copy(package["database"], database)
    day, provider, department = query(
        database, "SELECT schedule_date, provider_id, department_id FROM provider_schedules "
                  "WHERE available_slots > 0 LIMIT 1")[0]
    with closing(sqlite3.connect(database)) as connection, connection:
        # Foreign keys are not enforced on this connection, so the bad row gets in.
        connection.execute(
            "INSERT INTO appointments VALUES ('APT999999', 'PAT99999', ?, ?, ?, ?, NULL, NULL, "
            "NULL, NULL, NULL, 'Follow-Up', 'Cancelled')",
            (provider, department, day, f"{day} 08:00:00"))
    output = tmp_path / "out"
    with pytest.raises(PowerBIExportError, match="patient_id"):
        prepare_powerbi_data.build_package(database, output, tmp_path / "kpis.json")
    assert not output.exists() or not any(output.iterdir())


def test_missing_database_gives_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="prepare_data.py"):
        prepare_powerbi_data.build_package(tmp_path / "missing.db", tmp_path / "out",
                                           tmp_path / "kpis.json")


# --- Phase 4B artifacts (built by hand) ----------------------------------------------------
# These check only that the files exist, are well-formed and are trackable. The .pbix
# format is proprietary, so its contents are not opened. Rendering and DAX results were
# checked by hand (powerbi/POWER_BI_VERIFICATION_CHECKLIST.md).

def project_files(pattern):
    """Files matching a pattern anywhere in the project, skipping .git and .venv."""
    return [path for path in PROJECT_ROOT.rglob(pattern)
            if not {".git", ".venv"} & set(path.relative_to(PROJECT_ROOT).parts)]


def test_pbix_exists_and_is_not_empty():
    assert PBIX.is_file(), f"missing {PBIX}"
    assert PBIX.stat().st_size > 0


def test_exactly_one_pbix_and_none_in_the_data_folder():
    assert project_files("*.pbix") == [PBIX]
    assert not list((POWERBI / "data").glob("*.pbix"))


@pytest.mark.parametrize("name", SCREENSHOTS)
def test_screenshot_is_a_valid_16_by_9_png(name):
    content = (PROJECT_ROOT / "screenshots" / name).read_bytes()
    assert content.startswith(PNG_SIGNATURE), name
    assert content[12:16] == b"IHDR", name                 # first chunk: image header
    width = int.from_bytes(content[16:20], "big")
    height = int.from_bytes(content[20:24], "big")
    assert width >= 1000 and height >= 560, (name, width, height)
    assert 1.70 <= width / height <= 1.85, (name, width, height)   # about 16:9
    assert content.endswith(PNG_END), name                 # complete file


def test_only_the_expected_screenshots_exist():
    assert sorted(path.name for path in (PROJECT_ROOT / "screenshots").glob("*.png")) == sorted(
        SCREENSHOTS)


# --- Reference KPIs -------------------------------------------------------------------------

def test_expected_kpis_match_sql(package):
    results, _checks = analyze_data.load_analytics(package["database"])
    overall = results["overall_kpis"].iloc[0]
    expected = package["expected"]
    assert expected["synthetic_data"] is True
    assert expected["reporting_period"] == {"start": overall["period_start"],
                                            "end": overall["period_end"]}
    assert list(expected["kpis"]) == list(KPI_COLUMNS)
    for name, column in KPI_COLUMNS.items():
        assert expected["kpis"][name]["value"] == pytest.approx(overall[column]), name
    assert expected["kpis"]["Total Appointments"]["display"] == f"{overall['total_appointments']:,}"
    assert expected["kpis"]["Booking Rate"]["display"] == f"{overall['booking_rate']:.1%}"
    assert expected["kpis"]["Average Wait Minutes"]["display"] == (
        f"{overall['avg_wait_minutes']:.1f}")


def test_committed_snapshot_matches_committed_expected_kpis():
    """The tracked powerbi/data files and powerbi/expected_kpis.json belong together."""
    if not (POWERBI / "expected_kpis.json").exists():
        pytest.skip("Power BI snapshot not generated yet")
    expected = json.loads(read_text("expected_kpis.json"))
    files = {name: read_csv(POWERBI / "data" / name) for name in EXPECTED_COLUMNS}
    assert expected["dataset"]["row_counts"] == {n: len(r) for n, r in files.items()}

    appointments = files["appointments.csv"]
    completed = [r for r in appointments if r["appointment_status"] == "Completed"]
    slots = sum(int(r["available_slots"]) for r in files["provider_schedules.csv"])
    kpis = {name: item["value"] for name, item in expected["kpis"].items()}
    assert kpis["Total Appointments"] == len(appointments)
    assert kpis["Unique Patients"] == len({r["patient_id"] for r in appointments})
    assert kpis["Completed Appointments"] == len(completed)
    assert kpis["Available Slots"] == slots
    assert kpis["Booking Rate"] == pytest.approx(len(appointments) / slots)
    assert kpis["Average Wait Minutes"] == pytest.approx(
        sum(int(r["wait_minutes"]) for r in completed) / len(completed))


# --- Theme ------------------------------------------------------------------------------------

def test_theme_is_valid_json_with_required_colors():
    theme = json.loads(read_text("healthcare_theme.json"))
    text = json.dumps(theme).upper()
    for color in ["#1B2A41",   # dark navy: titles
                  "#2F6DB5",   # medium blue: main chart colour
                  "#1A8A7D",   # teal: Completed
                  "#D97B29",   # orange: Cancelled
                  "#B4474F",   # muted red: No Show
                  "#F4F6F8",   # light grey background
                  "#252B33"]:  # dark body text
        assert color in text, color
    assert theme["dataColors"][0] == "#2F6DB5"
    assert theme["textClasses"]["title"]["color"] == "#1B2A41"
    assert all(item["fontFace"].startswith("Segoe UI") for item in theme["textClasses"].values())
    assert theme["background"] == "#FFFFFF"
    container = theme["visualStyles"]["*"]["*"]
    assert container["border"][0]["show"] is False
    assert container["dropShadow"][0]["show"] is False
    assert container["title"][0]["show"] is True
    assert "GRADIENT" not in text


# --- DAX -----------------------------------------------------------------------------------

def test_dax_has_every_required_measure():
    measures = dax_measures()
    assert list(measures) == DAX_MEASURES
    assert all(measure["body"].strip() for measure in measures.values())


def test_dax_uses_required_functions():
    text = "".join(m["body"] for m in dax_measures().values())
    for function in ["COUNTROWS", "DISTINCTCOUNT", "CALCULATE", "DIVIDE", "DATEADD"]:
        assert function in text, function


def test_dax_rates_use_divide_and_no_division_operator():
    for name, measure in dax_measures().items():
        assert "/" not in measure["body"], name
        if any(word in name for word in ["Rate", "Utilization", "Percent"]):
            assert "DIVIDE" in measure["body"], name


def test_dax_definitions_match_phase3():
    measures = {name: re.sub(r"\s+", " ", m["body"]).strip() for name, m in dax_measures().items()}
    assert measures["Total Appointments"] == "COUNTROWS ( Appointments )"
    assert measures["Unique Patients"] == "DISTINCTCOUNT ( Appointments[patient_id] )"
    assert measures["Completion Rate"] == "DIVIDE ( [Completed Appointments], [Total Appointments] )"
    assert measures["Booking Rate"] == "DIVIDE ( [Total Appointments], [Available Slots] )"
    assert measures["Completed Slot Utilization"] == (
        "DIVIDE ( [Completed Appointments], [Available Slots] )")
    assert measures["Available Slots"] == "SUM ( ProviderSchedules[available_slots] )"
    for name in ["Average Wait Minutes", "Average Visit Minutes"]:
        assert 'Appointments[appointment_status] = "Completed"' in measures[name], name
    assert "DATEADD ( 'Date'[date], -1, MONTH )" in measures["Previous Month Appointments"]


def test_dax_formats_are_specified():
    for name, measure in dax_measures().items():
        if "Rate" in name or "Utilization" in name or "Percent" in name:
            assert "0.0%" in measure["format"], name
        elif "Minutes" in name:
            assert "(0.0)" in measure["format"], name
        else:
            assert "#,0" in measure["format"], name


def test_dax_documents_capacity_limitation():
    text = read_text("dax_measures.txt")
    assert "FILTER-CONTEXT LIMITATION" in text
    for field in ["appointment type", "age", "gender", "insurance type"]:
        assert field in text


# --- Documents -------------------------------------------------------------------------------

def test_build_guide_covers_tables_relationships_pages_and_pbix():
    guide = read_text("POWER_BI_BUILD_GUIDE.md")
    for file_name, table in POWERBI_TABLES.items():
        assert f"`{file_name}`" in guide and f"`{table}`" in guide, table
    for relationship in RELATIONSHIPS:
        assert relationship in guide, relationship
    for page in ["Page 1: Operational Overview", "Page 2: Capacity and Provider Performance",
                 "Page 3: Patient and Appointment Patterns"]:
        assert page in guide
    assert "powerbi/healthcare_patient_flow_dashboard.pbix" in guide
    assert "screenshots/" in guide
    assert "Mark as date table" in guide and "Auto date/time" in guide
    assert "healthcare_theme.json" in guide and "dax_measures.txt" in guide


def test_page_3_has_no_capacity_visuals():
    guide = read_text("POWER_BI_BUILD_GUIDE.md")
    page_3 = guide.split("### Page 3")[1].split("## Step 10")[0]
    visual_rows = [line for line in page_3.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(visual_rows) >= 14
    for row in visual_rows:
        for measure in ["Available Slots", "Booking Rate", "Completed Slot Utilization"]:
            assert measure not in row, row


def test_data_model_documents_relationships_and_settings():
    model = read_text("POWER_BI_DATA_MODEL.md")
    for relationship in RELATIONSHIPS:
        assert relationship in model, relationship
    assert "```mermaid" in model
    for text in ["One to many", "Single", "Mark as date table", "Auto date/time",
                 "Hide in report view", "`Date[month_name]` | `Date[month_number]`",
                 "`Date[year_month]` | `Date[year_month_sort]`",
                 "`Date[weekday_name]` | `Date[weekday_number]`"]:
        assert text in model, text


def test_data_dictionary_covers_every_column():
    dictionary = read_text("DATA_DICTIONARY.md")
    assert "not clinical data" in dictionary
    sections = re.split(r"^## ", dictionary, flags=re.MULTILINE)
    for file_name, columns in EXPECTED_COLUMNS.items():
        section = next(s for s in sections if f"(`{file_name}`)" in s.splitlines()[0])
        for column in columns:
            assert re.search(rf"^\| `{column}` \|", section, re.MULTILINE), (file_name, column)


def test_verification_checklist_covers_kpis_and_slicers():
    checklist = read_text("POWER_BI_VERIFICATION_CHECKLIST.md")
    for text in ["expected_kpis.json", "Slicer testing", "Department-to-provider",
                 "Monthly ordering", "Weekday ordering", "Blank and zero",
                 "Capacity measure limitation", "No clipped text",
                 "No unexplained blank visuals", "healthcare_patient_flow_dashboard.pbix",
                 "screenshots/", "real patients"]:
        assert text in checklist, text
    for kpi in KPI_COLUMNS:
        assert f"| {kpi} |" in checklist, kpi
