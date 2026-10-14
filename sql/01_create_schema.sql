-- Phase 2: SQLite schema for the SYNTHETIC healthcare analytics database.
-- All data is fictional. Run by prepare_data.py; safe to run again because
-- existing tables are dropped (children first) and created again (parents first).
--
-- Date format:     YYYY-MM-DD           (checked with SQLite's date() function)
-- Datetime format: YYYY-MM-DD HH:MM:SS  (checked with SQLite's datetime() function)

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS provider_schedules;
DROP TABLE IF EXISTS patients;
DROP TABLE IF EXISTS providers;
DROP TABLE IF EXISTS departments;

-- One row per clinic department.
CREATE TABLE departments (
    department_id   TEXT PRIMARY KEY,
    department_name TEXT NOT NULL UNIQUE
);

-- One row per provider. Each provider belongs to one department.
CREATE TABLE providers (
    provider_id         TEXT PRIMARY KEY,
    department_id       TEXT NOT NULL REFERENCES departments (department_id),
    provider_name       TEXT NOT NULL,
    specialty           TEXT NOT NULL,
    daily_slot_capacity INTEGER NOT NULL CHECK (daily_slot_capacity > 0)
);

-- One row per patient. Age 0 is allowed (patients under one year old).
CREATE TABLE patients (
    patient_id     TEXT PRIMARY KEY,
    age            INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
    age_group      TEXT NOT NULL CHECK (age_group IN ('0-17', '18-34', '35-49', '50-64', '65+')),
    gender         TEXT NOT NULL,
    city           TEXT NOT NULL,
    insurance_type TEXT NOT NULL
);

-- One row per provider per clinic day. available_slots is 0 when the provider is away.
CREATE TABLE provider_schedules (
    schedule_date   TEXT NOT NULL CHECK (schedule_date = date(schedule_date)),
    provider_id     TEXT NOT NULL REFERENCES providers (provider_id),
    department_id   TEXT NOT NULL REFERENCES departments (department_id),
    available_slots INTEGER NOT NULL CHECK (available_slots >= 0),
    PRIMARY KEY (schedule_date, provider_id)
);

-- One row per booked appointment.
-- Visit times and durations are filled in only for Completed appointments.
CREATE TABLE appointments (
    appointment_id     TEXT PRIMARY KEY,
    patient_id         TEXT NOT NULL REFERENCES patients (patient_id),
    provider_id        TEXT NOT NULL REFERENCES providers (provider_id),
    department_id      TEXT NOT NULL REFERENCES departments (department_id),
    appointment_date   TEXT NOT NULL CHECK (appointment_date = date(appointment_date)),
    scheduled_datetime TEXT NOT NULL CHECK (scheduled_datetime = datetime(scheduled_datetime)),
    check_in_datetime  TEXT CHECK (check_in_datetime = datetime(check_in_datetime)),
    seen_datetime      TEXT CHECK (seen_datetime = datetime(seen_datetime)),
    checkout_datetime  TEXT CHECK (checkout_datetime = datetime(checkout_datetime)),
    wait_minutes       INTEGER CHECK (wait_minutes >= 0),
    visit_minutes      INTEGER CHECK (visit_minutes >= 0),
    appointment_type   TEXT NOT NULL
        CHECK (appointment_type IN ('Follow-Up', 'New Patient', 'Consultation', 'Procedure')),
    appointment_status TEXT NOT NULL
        CHECK (appointment_status IN ('Completed', 'Cancelled', 'No Show')),

    -- Every appointment must fall on one of the provider's clinic days.
    FOREIGN KEY (appointment_date, provider_id)
        REFERENCES provider_schedules (schedule_date, provider_id),

    -- Times must be in order: check-in, then seen, then checkout.
    CHECK (check_in_datetime <= seen_datetime AND seen_datetime <= checkout_datetime),

    -- Completed visits have every time and duration; other statuses have none.
    CHECK (
        (appointment_status = 'Completed'
            AND check_in_datetime IS NOT NULL AND seen_datetime IS NOT NULL
            AND checkout_datetime IS NOT NULL
            AND wait_minutes IS NOT NULL AND visit_minutes IS NOT NULL)
        OR
        (appointment_status <> 'Completed'
            AND check_in_datetime IS NULL AND seen_datetime IS NULL
            AND checkout_datetime IS NULL
            AND wait_minutes IS NULL AND visit_minutes IS NULL)
    )
);

-- Indexes for the filters and joins used most in analysis.
CREATE INDEX idx_appointments_date ON appointments (appointment_date);
CREATE INDEX idx_appointments_status ON appointments (appointment_status);
CREATE INDEX idx_appointments_department ON appointments (department_id);
CREATE INDEX idx_appointments_provider ON appointments (provider_id);
CREATE INDEX idx_appointments_patient ON appointments (patient_id);
