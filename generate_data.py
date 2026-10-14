"""Generate SYNTHETIC outpatient clinic data as CSV files.

None of this data describes real patients, providers, or hospitals.

Example (PowerShell):
    python generate_data.py --appointments 5000 --seed 42

Creates five CSV files in data/raw/:
    departments.csv, providers.csv, patients.csv,
    appointments.csv, provider_schedules.csv
"""

import argparse
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config


# --- Small helpers ---------------------------------------------------------

def weighted_choice(rng, options):
    """Pick one key from a {value: weight} dictionary."""
    return rng.choices(list(options), weights=list(options.values()))[0]


def age_to_group(age):
    """Return the age group label (e.g. "35-49") for an age in years."""
    for group, (_share, (low, high)) in config.AGE_GROUPS.items():
        if low <= age <= high:
            return group
    raise ValueError(f"No age group for age {age}")


def all_dates():
    """Every calendar date from START_DATE to END_DATE (inclusive)."""
    day = date.fromisoformat(config.START_DATE)
    end = date.fromisoformat(config.END_DATE)
    dates = []
    while day <= end:
        dates.append(day)
        day += timedelta(days=1)
    return dates


def format_time(moment):
    """Format a datetime as HH:MM, or return None for a missing time."""
    return moment.strftime("%H:%M") if moment is not None else None


# --- Tables ----------------------------------------------------------------

def generate_departments():
    rows = []
    for number, dept in enumerate(config.DEPARTMENTS, start=1):
        rows.append({"department_id": f"DEP{number:02d}", "department_name": dept["name"]})
    return pd.DataFrame(rows)


def generate_providers(rng, departments):
    # Unique fictional names made from the first-name and last-name lists.
    possible_names = [f"Dr. {first} {last}"
                      for first in config.FIRST_NAMES for last in config.LAST_NAMES]
    names = rng.sample(possible_names, k=len(departments) * config.PROVIDERS_PER_DEPARTMENT)

    rows = []
    for dept_id, dept in zip(departments["department_id"], config.DEPARTMENTS):
        for k in range(config.PROVIDERS_PER_DEPARTMENT):
            rows.append({
                "provider_id": f"PRV{len(rows) + 1:03d}",
                "department_id": dept_id,
                "provider_name": names[len(rows)],
                "specialty": dept["specialties"][k % len(dept["specialties"])],
                "daily_slot_capacity": rng.randint(config.MIN_DAILY_SLOTS, config.MAX_DAILY_SLOTS),
            })
    return pd.DataFrame(rows)


def generate_patients(rng, n_patients):
    group_shares = {group: share for group, (share, _ages) in config.AGE_GROUPS.items()}
    width = max(5, len(str(n_patients)))

    rows = []
    for number in range(1, n_patients + 1):
        group = weighted_choice(rng, group_shares)
        low, high = config.AGE_GROUPS[group][1]
        age = rng.randint(low, high)
        insurance_options = config.INSURANCE_65_PLUS if age >= 65 else config.INSURANCE_UNDER_65
        rows.append({
            "patient_id": f"PAT{number:0{width}d}",
            "age": age,
            "age_group": age_to_group(age),
            "gender": weighted_choice(rng, config.GENDERS),
            "city": weighted_choice(rng, config.CITIES),
            "insurance_type": weighted_choice(rng, insurance_options),
        })
    return pd.DataFrame(rows)


def clinic_days_per_week(n_appointments, n_providers):
    """How many weekdays each provider works so the clinic is about TARGET_UTILIZATION full."""
    weeks = len(all_dates()) / 7
    average_slots = (config.MIN_DAILY_SLOTS + config.MAX_DAILY_SLOTS) / 2
    provider_days_needed = n_appointments / (config.TARGET_UTILIZATION * average_slots)
    days = round(provider_days_needed / (n_providers * weeks))
    return min(5, max(1, days))


def generate_provider_schedules(rng, providers, days_per_week):
    dates = all_dates()
    rows = []
    for index, provider in enumerate(providers.itertuples()):
        # Each provider works the same weekdays every week (0 = Monday).
        # Starting days rotate so clinic days are spread evenly across the week.
        clinic_weekdays = [(index + offset) % 5 for offset in range(days_per_week)]
        for day in dates:
            if day.weekday() not in clinic_weekdays:
                continue
            slots = provider.daily_slot_capacity
            roll = rng.random()
            if roll < config.LEAVE_DAY_RATE:
                slots = 0
            elif roll < config.LEAVE_DAY_RATE + config.REDUCED_DAY_RATE:
                slots = rng.randint(slots // 2, slots - 2)
            rows.append({
                "schedule_date": day.isoformat(),
                "provider_id": provider.provider_id,
                "department_id": provider.department_id,
                "available_slots": slots,
            })
    schedules = pd.DataFrame(rows)
    return schedules.sort_values(["schedule_date", "provider_id"]).reset_index(drop=True)


def choose_status(rng, dept, day):
    cancel_rate = dept["cancel_rate"]
    if day.month in config.WINTER_MONTHS:
        cancel_rate += config.WINTER_EXTRA_CANCEL_RATE
    roll = rng.random()
    if roll < dept["no_show_rate"]:
        return "No Show"
    if roll < dept["no_show_rate"] + cancel_rate:
        return "Cancelled"
    return "Completed"


def pick_patient(rng, pool, day, booked_patient_days):
    """Pick a patient, avoiding a second appointment for them on the same day when possible."""
    for _attempt in range(20):
        patient_id = rng.choice(pool)
        if (patient_id, day) not in booked_patient_days:
            break
    booked_patient_days.add((patient_id, day))
    return patient_id


def generate_appointments(rng, n_appointments, departments, patients, schedules):
    # Department settings from config, looked up by department_id.
    dept_settings = dict(zip(departments["department_id"], config.DEPARTMENTS))

    # Step 1: list every open slot, weighted by how busy that day usually is.
    slot_rows = []
    for sched in schedules.itertuples():
        day = date.fromisoformat(sched.schedule_date)
        weight = (config.MONTH_DEMAND[day.month]
                  * config.WEEKDAY_DEMAND[day.weekday()]
                  * dept_settings[sched.department_id]["demand"])
        for slot_number in range(sched.available_slots):
            slot_rows.append({
                "schedule_date": sched.schedule_date,
                "provider_id": sched.provider_id,
                "department_id": sched.department_id,
                "slot_number": slot_number,
                "weight": weight,
            })
    open_slots = pd.DataFrame(slot_rows)

    if n_appointments > len(open_slots):
        raise ValueError(
            f"Requested {n_appointments} appointments, but the schedule only has "
            f"{len(open_slots)} open slots. Use a smaller --appointments value."
        )

    # Step 2: book n slots without using any slot twice. Each slot gets a random
    # score (random number ** (1 / weight)); higher weights tend to give higher
    # scores, so busier days fill up first. Keep the n highest scores.
    open_slots["score"] = [rng.random() ** (1 / weight) for weight in open_slots["weight"]]
    booked = open_slots.nlargest(n_appointments, "score")
    booked = booked.sort_values(["schedule_date", "slot_number", "provider_id"])

    # Patients who can be booked in each kind of department.
    all_ids = patients["patient_id"].tolist()
    children = patients.loc[patients["age"] < 18, "patient_id"].tolist()
    adults = patients.loc[patients["age"] >= 18, "patient_id"].tolist()
    pools = {"all": all_ids, "child": children or all_ids, "adult": adults or all_ids}

    type_shares = {name: share for name, (share, _minutes) in config.APPOINTMENT_TYPES.items()}
    clinic_start = datetime.strptime(config.CLINIC_START, "%H:%M").time()
    width = max(6, len(str(n_appointments)))
    booked_patient_days = set()

    # Step 3: fill in the details of each booked appointment.
    rows = []
    for number, slot in enumerate(booked.itertuples(), start=1):
        dept = dept_settings[slot.department_id]
        day = date.fromisoformat(slot.schedule_date)
        scheduled = (datetime.combine(day, clinic_start)
                     + timedelta(minutes=slot.slot_number * config.SLOT_MINUTES))
        appointment_type = weighted_choice(rng, type_shares)
        status = choose_status(rng, dept, day)

        # Only completed visits have check-in, seen and checkout times.
        check_in = seen = checkout = None
        if status == "Completed":
            check_in = scheduled + timedelta(minutes=rng.randint(*config.CHECK_IN_OFFSET_MINUTES))
            wait = (dept["base_wait_minutes"]
                    + config.WAIT_INCREASE_PER_SLOT * slot.slot_number
                    + (config.MONDAY_EXTRA_WAIT if day.weekday() == 0 else 0)
                    + rng.gauss(0, config.WAIT_RANDOM_SPREAD))
            # The patient is seen after both check-in and the scheduled time.
            seen = max(check_in, scheduled) + timedelta(minutes=max(0, round(wait)))
            low, high = config.APPOINTMENT_TYPES[appointment_type][1]
            checkout = seen + timedelta(minutes=rng.randint(low, high))

        rows.append({
            "appointment_id": f"APT{number:0{width}d}",
            "patient_id": pick_patient(rng, pools[dept["patients"]], day, booked_patient_days),
            "provider_id": slot.provider_id,
            "department_id": slot.department_id,
            "appointment_date": slot.schedule_date,
            "scheduled_time": format_time(scheduled),
            "check_in_time": format_time(check_in),
            "seen_time": format_time(seen),
            "checkout_time": format_time(checkout),
            "appointment_type": appointment_type,
            "appointment_status": status,
        })
    return pd.DataFrame(rows)


# --- Putting it together ---------------------------------------------------

def generate_all(n_appointments=config.DEFAULT_APPOINTMENTS, seed=config.DEFAULT_SEED,
                 n_patients=None):
    """Build all five tables. The same arguments always give the same data."""
    if n_appointments < 1:
        raise ValueError("--appointments must be at least 1.")
    if n_patients is None:
        n_patients = max(config.MIN_PATIENTS, n_appointments // config.APPOINTMENTS_PER_PATIENT)
    if n_patients < 1:
        raise ValueError("--patients must be at least 1.")

    rng = random.Random(seed)
    departments = generate_departments()
    providers = generate_providers(rng, departments)
    patients = generate_patients(rng, n_patients)
    days_per_week = clinic_days_per_week(n_appointments, len(providers))
    schedules = generate_provider_schedules(rng, providers, days_per_week)
    appointments = generate_appointments(rng, n_appointments, departments, patients, schedules)

    return {
        "departments.csv": departments,
        "providers.csv": providers,
        "patients.csv": patients,
        "appointments.csv": appointments,
        "provider_schedules.csv": schedules,
    }


def write_csvs(tables, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for file_name, table in tables.items():
        columns = config.OUTPUT_COLUMNS[file_name]
        table[columns].to_csv(output_dir / file_name, index=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic patient-flow CSV files.")
    parser.add_argument("--appointments", type=int, default=config.DEFAULT_APPOINTMENTS,
                        help=f"number of appointments (default {config.DEFAULT_APPOINTMENTS})")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED,
                        help=f"random seed (default {config.DEFAULT_SEED})")
    parser.add_argument("--patients", type=int, default=None,
                        help="number of patients (default: appointments / "
                             f"{config.APPOINTMENTS_PER_PATIENT})")
    parser.add_argument("--output-dir", default=str(config.RAW_DATA_DIR),
                        help="folder for the CSV files (default data/raw)")
    args = parser.parse_args(argv)

    try:
        tables = generate_all(args.appointments, args.seed, args.patients)
    except ValueError as error:
        parser.error(str(error))
    write_csvs(tables, args.output_dir)

    print(f"SYNTHETIC data written to {Path(args.output_dir).resolve()} (seed {args.seed})")
    for file_name, table in tables.items():
        print(f"  {file_name:<24} {len(table):>7,} rows")


if __name__ == "__main__":
    main()
