"""Final repository checks: portfolio artifacts, documentation links and repository hygiene.

These tests read the tracked files in the repository. They complement the pipeline tests,
which build their own data in temporary folders.
"""

import json
import re
import shutil
import subprocess
import zipfile

import pytest

import config
from conftest import PROJECT_ROOT

SCREENSHOTS = ["screenshots/powerbi_operational_overview.png",
               "screenshots/powerbi_capacity_provider_performance.png",
               "screenshots/powerbi_patient_appointment_patterns.png"]
ARTIFACTS = ["reports/healthcare_patient_flow_report.xlsx",
             "powerbi/healthcare_patient_flow_dashboard.pbix",
             *SCREENSHOTS,
             "powerbi/expected_kpis.json", "powerbi/dax_measures.txt",
             "powerbi/healthcare_theme.json", "powerbi/POWER_BI_DATA_MODEL.md",
             "powerbi/DATA_DICTIONARY.md", "powerbi/POWER_BI_BUILD_GUIDE.md",
             "powerbi/POWER_BI_VERIFICATION_CHECKLIST.md",
             "sql/01_create_schema.sql", "sql/02_create_analytics_views.sql",
             "requirements.txt", "README.md"]
EXCEL_SHEETS = ["Summary", "Monthly Trends", "Department Analysis", "Provider Analysis",
                "Appointment Types", "Data Quality", "Appointment Data", "Capacity Data"]
TEXT_SUFFIXES = {".py", ".md", ".sql", ".txt", ".json", ".gitignore"}
MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024   # far below GitHub's 100 MB hard limit


def tracked_files():
    if shutil.which("git") is None or not (PROJECT_ROOT / ".git").exists():
        pytest.skip("git repository not available")
    result = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True,
                            text=True, check=True)
    return result.stdout.split()


def tracked_text_files():
    return [name for name in tracked_files()
            if (PROJECT_ROOT / name).suffix in TEXT_SUFFIXES or name.endswith(".gitignore")]


def markdown_links(text):
    """Relative link targets in Markdown, ignoring code blocks and web links."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    targets = re.findall(r"!?\[[^\]]*\]\(([^)\s]+)\)", text)
    return [t for t in targets if not re.match(r"https?://|mailto:", t)]


def heading_anchors(text):
    """GitHub-style anchors for every Markdown heading."""
    headings = re.findall(r"^#+\s+(.*)$", text, re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in headings}


# --- Portfolio artifacts ---------------------------------------------------------------

@pytest.mark.parametrize("name", ARTIFACTS)
def test_portfolio_artifact_exists_and_is_not_empty(name):
    path = PROJECT_ROOT / name
    assert path.is_file(), f"missing {name}"
    assert path.stat().st_size > 0, f"{name} is empty"


def test_excel_report_is_a_valid_workbook_with_all_sheets():
    with zipfile.ZipFile(PROJECT_ROOT / "reports" / "healthcare_patient_flow_report.xlsx") as xlsx:
        assert xlsx.testzip() is None                       # every part is readable
        names = xlsx.namelist()
        workbook = xlsx.read("xl/workbook.xml").decode("utf-8")
    sheets = [name.replace("&amp;", "&") for name in re.findall(r'<sheet [^>]*name="([^"]+)"',
                                                                  workbook)]
    assert sheets == EXCEL_SHEETS
    assert not any("externalLink" in n or "vbaProject" in n for n in names)


def test_excel_report_has_only_neutral_author_metadata():
    """The tracked workbook may name only the project as its author: no personal or
    computer user names. Saving the file from Excel would break this; regenerate it with
    create_excel_report.py instead."""
    allowed = {"Healthcare Patient Flow Analytics"}
    with zipfile.ZipFile(PROJECT_ROOT / "reports" / "healthcare_patient_flow_report.xlsx") as xlsx:
        core = xlsx.read("docProps/core.xml").decode("utf-8")
        app = xlsx.read("docProps/app.xml").decode("utf-8")
    people = dict(re.findall(r"<(?:\w+:)?(creator|lastModifiedBy)[^>]*>([^<]*)<", core))
    assert set(people) == {"creator", "lastModifiedBy"}
    for field, value in people.items():
        assert value in allowed, f"workbook {field} is not neutral"
    for field in ["Company", "Manager"]:
        assert not re.search(rf"<(?:\w+:)?{field}>[^<]+<", app), f"workbook {field} is set"


def test_pbix_is_the_configured_dashboard_file():
    assert config.POWERBI_REPORT_FILE == PROJECT_ROOT / "powerbi" / (
        "healthcare_patient_flow_dashboard.pbix")
    assert config.POWERBI_REPORT_FILE.is_file()


def test_important_assets_are_tracked_by_git():
    tracked = set(tracked_files())
    for name in ARTIFACTS:
        assert name in tracked, f"{name} is not tracked by Git"
    for name in ["appointments.csv", "provider_schedules.csv", "providers.csv",
                 "departments.csv", "patients.csv", "date.csv"]:
        assert f"powerbi/data/{name}" in tracked


# --- Documentation -------------------------------------------------------------------------

def test_markdown_links_and_anchors_resolve():
    checked = 0
    for name in tracked_files():
        if not name.endswith(".md"):
            continue
        source = PROJECT_ROOT / name
        for target in markdown_links(source.read_text(encoding="utf-8")):
            path_part, _, anchor = target.partition("#")
            destination = (source.parent / path_part) if path_part else source
            assert destination.exists(), f"{name}: broken link {target}"
            if anchor and destination.suffix == ".md":
                anchors = heading_anchors(destination.read_text(encoding="utf-8"))
                assert anchor in anchors, f"{name}: missing anchor {target}"
            checked += 1
    assert checked > 0


def test_readme_shows_every_dashboard_screenshot():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    images = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", readme)
    assert sorted(set(images)) == sorted(SCREENSHOTS)


def test_obsolete_screenshot_names_are_not_referenced():
    # Early drafts used "page<number>_..." names; the approved files are "powerbi_...".
    # The old names are built here so that this file does not contain them itself.
    obsolete_names = [f"page{number}_{name}" for number, name in [
        (1, "operational_overview"), (2, "capacity_provider_performance"),
        (3, "patient_appointment_patterns")]]
    for name in tracked_text_files():
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for obsolete in obsolete_names:
            assert obsolete not in text, f"{name} mentions {obsolete}"


def test_readme_states_data_is_synthetic_and_not_clinical():
    opening = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")[:1500].lower()
    assert "synthetic" in opening
    assert "clinical" in opening
    assert "fictional" in opening


def test_readme_kpi_values_match_expected_kpis():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    expected = json.loads((PROJECT_ROOT / "powerbi" / "expected_kpis.json").read_text(
        encoding="utf-8"))
    for name, item in expected["kpis"].items():
        assert item["display"] in readme, f"README does not show {name} = {item['display']}"


# --- Reference KPIs --------------------------------------------------------------------------

def test_expected_kpis_are_internally_consistent():
    expected = json.loads((PROJECT_ROOT / "powerbi" / "expected_kpis.json").read_text(
        encoding="utf-8"))
    assert expected["synthetic_data"] is True
    k = {name: item["value"] for name, item in expected["kpis"].items()}
    total, slots = k["Total Appointments"], k["Available Slots"]
    assert (k["Completed Appointments"] + k["Cancelled Appointments"]
            + k["No Show Appointments"]) == total
    assert k["Unique Patients"] <= total
    assert k["Completion Rate"] == pytest.approx(k["Completed Appointments"] / total)
    assert k["Cancellation Rate"] == pytest.approx(k["Cancelled Appointments"] / total)
    assert k["No Show Rate"] == pytest.approx(k["No Show Appointments"] / total)
    assert k["Booking Rate"] == pytest.approx(total / slots)
    assert k["Completed Slot Utilization"] == pytest.approx(k["Completed Appointments"] / slots)
    assert expected["dataset"]["row_counts"]["appointments.csv"] == total


# --- Repository hygiene ----------------------------------------------------------------------

def test_no_machine_specific_paths_or_email_addresses_in_tracked_text():
    # Drive-letter paths, user home folders and the Windows app-data folder. The patterns
    # are written so that this file cannot match itself ("Ap{2}" means two letters p).
    machine_path = re.compile(r"\b[A-Za-z]:[\\/][A-Za-z]|/(?:Users|home)/|Ap{2}Data",
                              re.IGNORECASE)
    email = re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.IGNORECASE)
    for name in tracked_text_files():
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert not machine_path.search(text), f"machine-specific path in {name}"
        assert not email.search(text), f"email address in {name}"


def test_no_generated_cache_or_lock_files_are_tracked():
    unwanted = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.venv|venv)/|\.pyc$|\.db$"
                          r"|(^|/)~\$|\.tmp$|^data/(raw|processed|output)/[^.]")
    for name in tracked_files():
        assert not unwanted.search(name), f"{name} should not be tracked"


def test_tracked_files_are_a_normal_size_for_github():
    for name in tracked_files():
        assert (PROJECT_ROOT / name).stat().st_size < MAX_TRACKED_FILE_BYTES, name
