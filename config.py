"""Project settings for the synthetic data generator and the data pipeline.

Everything that controls the shape of the generated data lives here, so it can
be changed in one place. All names and values describe a FICTIONAL clinic.
"""

from pathlib import Path

# --- Folders and files -------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DATA_DIR = PROJECT_ROOT / "data" / "output"
SCHEMA_FILE = PROJECT_ROOT / "sql" / "01_create_schema.sql"
DATABASE_FILE_NAME = "healthcare_analytics.db"            # saved in PROCESSED_DATA_DIR
QUALITY_REPORT_FILE_NAME = "phase2_data_quality.json"     # saved in OUTPUT_DATA_DIR
DATABASE_FILE = PROCESSED_DATA_DIR / DATABASE_FILE_NAME
QUALITY_REPORT_FILE = OUTPUT_DATA_DIR / QUALITY_REPORT_FILE_NAME
ANALYTICS_VIEWS_FILE = PROJECT_ROOT / "sql" / "02_create_analytics_views.sql"
ANALYTICS_OUTPUT_DIR = OUTPUT_DATA_DIR / "analytics"
EXCEL_REPORT_FILE = PROJECT_ROOT / "reports" / "healthcare_patient_flow_report.xlsx"
POWERBI_DIR = PROJECT_ROOT / "powerbi"
POWERBI_DATA_DIR = POWERBI_DIR / "data"                   # tracked Power BI snapshot
EXPECTED_KPIS_FILE = POWERBI_DIR / "expected_kpis.json"
POWERBI_REPORT_FILE = POWERBI_DIR / "healthcare_patient_flow_dashboard.pbix"  # built by hand

# --- Defaults for the command line ----------------------------------------
DEFAULT_SEED = 42
DEFAULT_APPOINTMENTS = 5000
# If --patients is not given: one patient for every N appointments.
APPOINTMENTS_PER_PATIENT = 4
MIN_PATIENTS = 50

# --- Time period (one calendar year of history) ----------------------------
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"

# --- Output files and their columns ---------------------------------------
OUTPUT_COLUMNS = {
    "departments.csv": ["department_id", "department_name"],
    "providers.csv": [
        "provider_id",
        "department_id",
        "provider_name",
        "specialty",
        "daily_slot_capacity",
    ],
    "patients.csv": ["patient_id", "age", "age_group", "gender", "city", "insurance_type"],
    "appointments.csv": [
        "appointment_id",
        "patient_id",
        "provider_id",
        "department_id",
        "appointment_date",
        "scheduled_time",
        "check_in_time",
        "seen_time",
        "checkout_time",
        "appointment_type",
        "appointment_status",
    ],
    "provider_schedules.csv": ["schedule_date", "provider_id", "department_id", "available_slots"],
}

# --- Departments -----------------------------------------------------------
# patients: which patients can book ("child" = under 18, "adult" = 18+, "all")
# demand: relative popularity (1.0 = average)
# base_wait_minutes: typical wait for the first slot of the day (delays build up later)
# no_show_rate / cancel_rate: share of booked appointments with that outcome
DEPARTMENTS = [
    {"name": "Family Medicine", "patients": "all", "demand": 1.4, "base_wait_minutes": 12,
     "no_show_rate": 0.10, "cancel_rate": 0.10,
     "specialties": ["Family Physician", "Nurse Practitioner"]},
    {"name": "Pediatrics", "patients": "child", "demand": 1.1, "base_wait_minutes": 10,
     "no_show_rate": 0.08, "cancel_rate": 0.12,
     "specialties": ["Pediatrician"]},
    {"name": "Cardiology", "patients": "adult", "demand": 1.0, "base_wait_minutes": 15,
     "no_show_rate": 0.06, "cancel_rate": 0.09,
     "specialties": ["Cardiologist"]},
    {"name": "Orthopedics", "patients": "adult", "demand": 1.0, "base_wait_minutes": 18,
     "no_show_rate": 0.07, "cancel_rate": 0.11,
     "specialties": ["Orthopedic Surgeon", "Sports Medicine Physician"]},
    {"name": "Dermatology", "patients": "adult", "demand": 0.8, "base_wait_minutes": 8,
     "no_show_rate": 0.12, "cancel_rate": 0.13,
     "specialties": ["Dermatologist"]},
    {"name": "Neurology", "patients": "adult", "demand": 0.7, "base_wait_minutes": 20,
     "no_show_rate": 0.09, "cancel_rate": 0.10,
     "specialties": ["Neurologist"]},
]
PROVIDERS_PER_DEPARTMENT = 2

# --- Provider schedules ----------------------------------------------------
# Each provider runs clinic on a few fixed weekdays. The number of clinic days
# per week is chosen so the clinic is roughly this full (booked / available).
TARGET_UTILIZATION = 0.75
MIN_DAILY_SLOTS = 10
MAX_DAILY_SLOTS = 14
SLOT_MINUTES = 30
CLINIC_START = "08:00"
LEAVE_DAY_RATE = 0.03      # share of clinic days with no slots (provider away)
REDUCED_DAY_RATE = 0.08    # share of clinic days with fewer slots (meetings, training)

# --- Demand patterns (multipliers, 1.0 = average) --------------------------
# Higher in winter (cold and flu season), lower in summer.
MONTH_DEMAND = {1: 1.15, 2: 1.10, 3: 1.05, 4: 1.00, 5: 0.95, 6: 0.90,
                7: 0.85, 8: 0.90, 9: 1.00, 10: 1.05, 11: 1.05, 12: 0.90}
# Monday = 0 ... Friday = 4
WEEKDAY_DEMAND = {0: 1.15, 1: 1.05, 2: 1.00, 3: 1.00, 4: 0.85}

# --- Appointments ----------------------------------------------------------
# type: (share of appointments, (min, max) visit length in minutes)
APPOINTMENT_TYPES = {
    "Follow-Up": (0.50, (15, 30)),
    "New Patient": (0.25, (30, 50)),
    "Consultation": (0.15, (25, 45)),
    "Procedure": (0.10, (40, 75)),
}
# Patients arrive between 20 minutes early and 10 minutes late.
CHECK_IN_OFFSET_MINUTES = (-20, 10)
# Extra wait added per earlier slot in the day (delays build up).
WAIT_INCREASE_PER_SLOT = 1.5
MONDAY_EXTRA_WAIT = 5
WAIT_RANDOM_SPREAD = 6     # standard deviation of random noise added to each wait
# Extra cancellations in winter months.
WINTER_MONTHS = [1, 2, 12]
WINTER_EXTRA_CANCEL_RATE = 0.03

# --- Patients --------------------------------------------------------------
# age group: (share of patients, (min age, max age))
AGE_GROUPS = {
    "0-17": (0.18, (0, 17)),
    "18-34": (0.22, (18, 34)),
    "35-49": (0.20, (35, 49)),
    "50-64": (0.20, (50, 64)),
    "65+": (0.20, (65, 90)),
}
GENDERS = {"Female": 0.51, "Male": 0.47, "Other": 0.02}
# Fictional city names.
CITIES = {"Riverton": 0.30, "Lakeview": 0.22, "Oakdale": 0.18,
          "Westbridge": 0.14, "Fairmont": 0.10, "Pinecrest": 0.06}
INSURANCE_UNDER_65 = {"Commercial": 0.62, "Medicaid": 0.24, "Self-Pay": 0.09, "Medicare": 0.05}
INSURANCE_65_PLUS = {"Medicare": 0.78, "Commercial": 0.14, "Medicaid": 0.04, "Self-Pay": 0.04}

# --- Fictional provider names ---------------------------------------------
FIRST_NAMES = ["Avery", "Jordan", "Morgan", "Riley", "Casey", "Taylor", "Quinn", "Rowan",
               "Harper", "Emerson", "Sage", "Reese", "Parker", "Logan", "Skyler", "Dakota"]
LAST_NAMES = ["Ashford", "Bellamy", "Calloway", "Delgado", "Ellison", "Fairbanks", "Galloway",
              "Hollis", "Iverson", "Jansen", "Kendrick", "Lockwood", "Merritt", "Northcott"]
