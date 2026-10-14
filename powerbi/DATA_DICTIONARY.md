# Power BI Data Dictionary

> **Synthetic data only, not clinical data.** All records are created by
> `generate_data.py` from fixed random seeds. Patients, providers, departments, cities
> and times are fictional. Nothing here is a medical record or describes a real person,
> hospital or clinic.

The six files in `powerbi/data/` are written by `prepare_powerbi_data.py` from the
validated SQLite database (`data/processed/healthcare_analytics.db`).

File format:
- **Encoding and layout:** UTF-8, comma separated, one header row.
- **Dates:** `YYYY-MM-DD`.
- **Datetimes:** `YYYY-MM-DD HH:MM:SS`.
- **Blank cells:** a value that does not apply, such as the visit times of a cancelled
  appointment. Power BI loads them as blank (null).
- **IDs:** text, such as `PAT00001`. Keep them as **Text** in Power BI so leading zeros
  are kept and they are never added up.

Column guide:
- **Key:**
  - **PK** = primary key (unique in the table);
  - **FK** = foreign key used by a relationship;
  - **ref** = reference column kept for traceability, with no relationship (see
    [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md)).
- **Blank?:** whether the column can contain blank values.

## Appointments (`appointments.csv`)

Fact table, one row per booked appointment.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `appointment_id` | Text | PK | No | Appointment identifier, e.g. `APT000001` | Unique |
| `patient_id` | Text | FK → Patients | No | Patient who booked | Hide after relating. `Unique Patients` counts this column |
| `provider_id` | Text | FK → Providers | No | Provider seen | Hide after relating |
| `department_id` | Text | ref | No | Department of the provider | No relationship; department filters arrive through Providers. Hide |
| `appointment_date` | Date | FK → Date | No | Day of the appointment | Hide after relating; use the Date table in visuals |
| `scheduled_datetime` | Date/time | | No | Booked start time | |
| `check_in_datetime` | Date/time | | Yes | When the patient checked in | Blank unless Completed. May be before `scheduled_datetime` (early arrival) |
| `seen_datetime` | Date/time | | Yes | When the provider saw the patient | Blank unless Completed |
| `checkout_datetime` | Date/time | | Yes | When the visit ended | Blank unless Completed |
| `wait_minutes` | Whole number | | Yes | `seen_datetime - check_in_datetime` in minutes | Blank unless Completed. Wait starts at actual check-in. Average with the `Average Wait Minutes` measure |
| `visit_minutes` | Whole number | | Yes | `checkout_datetime - seen_datetime` in minutes | Blank unless Completed. Use the `Average Visit Minutes` measure |
| `appointment_type` | Text | | No | Follow-Up, New Patient, Consultation or Procedure | Do not combine with capacity measures |
| `appointment_status` | Text | | No | Completed, Cancelled or No Show | Every status counts in `Total Appointments` and `Booking Rate` |

## ProviderSchedules (`provider_schedules.csv`)

Fact table, one row per provider clinic day.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `schedule_date` | Date | PK (with `provider_id`), FK → Date | No | Clinic day | Hide after relating |
| `provider_id` | Text | PK (with `schedule_date`), FK → Providers | No | Provider holding the clinic | Hide after relating |
| `department_id` | Text | ref | No | Department of the provider | No relationship (filters arrive through Providers). Hide |
| `available_slots` | Whole number | | No | Bookable slots that day | 0 means the provider was away. `Available Slots` sums this column. Meaningful only with Date, Department and Provider filters |

## Providers (`providers.csv`)

Dimension, one row per fictional provider.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `provider_id` | Text | PK | No | Provider identifier, e.g. `PRV001` | One side of the relationships to both fact tables |
| `department_id` | Text | FK → Departments | No | Department the provider belongs to | Many side of Departments → Providers. Hide after relating |
| `provider_name` | Text | | No | Fictional provider name | Use in the Provider slicer and provider visuals |
| `specialty` | Text | | No | Provider specialty | |
| `daily_slot_capacity` | Whole number | | No | Usual slots on a full clinic day | Set Summarization to Don't summarize. Capacity measures use `ProviderSchedules[available_slots]`, not this column |

## Departments (`departments.csv`)

Dimension, one row per department.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `department_id` | Text | PK | No | Department identifier, e.g. `DEP01` | One side of Departments → Providers |
| `department_name` | Text | | No | Department name, e.g. Cardiology | Use in the Department slicer and department visuals |

## Patients (`patients.csv`)

Dimension, one row per fictional patient. Some patients have no appointments.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `patient_id` | Text | PK | No | Patient identifier, e.g. `PAT00001` | One side of Patients → Appointments |
| `age` | Whole number | | No | Age in years (0–90) | Set Summarization to Don't summarize |
| `age_group` | Text | | No | 0-17, 18-34, 35-49, 50-64 or 65+ | Sorts correctly as text. Do not combine with capacity measures |
| `gender` | Text | | No | Female, Male or Other | Do not combine with capacity measures |
| `city` | Text | | No | Fictional city name | Do not combine with capacity measures |
| `insurance_type` | Text | | No | Commercial, Medicaid, Medicare or Self-Pay | Do not combine with capacity measures |

## Date (`date.csv`)

Dimension, one row per calendar day, with no gaps. It covers whole calendar years from the
first to the last year used by appointments or schedules. Mark it as the date table using
`Date[date]`.

| Column | Power BI type | Key | Blank? | Meaning | Notes |
|---|---|---|---|---|---|
| `date` | Date | PK | No | Calendar day | One side of both date relationships |
| `year` | Whole number | | No | Calendar year, e.g. 2025 | Don't summarize |
| `quarter` | Whole number | | No | Quarter 1–4 | Don't summarize |
| `month_number` | Whole number | | No | Month 1–12 | Sort column for `month_name`. Hide |
| `month_name` | Text | | No | January … December | Sort by `month_number` |
| `year_month` | Text | | No | Month label, e.g. `Jan 2025` | Sort by `year_month_sort`. Use on monthly axes |
| `year_month_sort` | Whole number | | No | `year * 100 + month`, e.g. 202501 | Sort column for `year_month`. Hide |
| `weekday_number` | Whole number | | No | Monday = 1 … Sunday = 7 | Sort column for `weekday_name`. Hide |
| `weekday_name` | Text | | No | Monday … Sunday | Sort by `weekday_number` |
| `is_weekend` | True/False | | No | True for Saturday and Sunday | The clinic schedules only weekdays, so weekend days have no appointments |
