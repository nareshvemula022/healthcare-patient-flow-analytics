-- Phase 3: analytical views for the SYNTHETIC healthcare database (SQLite).
-- All data is fictional. Run by analyze_data.py after prepare_data.py.
-- Safe to run again: every view is dropped and created again.
--
-- KPI definitions (the same in SQL, Python, Excel and the README):
--   Total Appointments         = all appointment rows, every status
--   Completed / Cancelled / No Show Appointments = rows with that appointment_status
--   Completion Rate            = Completed Appointments / Total Appointments
--   Cancellation Rate          = Cancelled Appointments / Total Appointments
--   No Show Rate               = No Show Appointments   / Total Appointments
--   Average Wait Minutes       = AVG(wait_minutes)  of Completed appointments only
--   Average Visit Minutes      = AVG(visit_minutes) of Completed appointments only
--   Available Slots            = SUM(provider_schedules.available_slots)
--   Booking Rate               = Total Appointments     / Available Slots
--                                (every status uses up a booked slot)
--   Completed Slot Utilization = Completed Appointments / Available Slots
--
-- Rules used in every view:
--   * A rate is NULL when its denominator is 0:  CASE WHEN denominator > 0 THEN ... END
--   * "1.0 *" makes SQLite divide with decimals instead of whole numbers.
--   * Appointment counts and capacity are each added up on their own first and only
--     then joined. Joining raw rows would repeat (multiply) one side for every row
--     of the other.
--   * Overall rates use overall counts; they are never an average of percentages.

DROP VIEW IF EXISTS vw_overall_kpis;
DROP VIEW IF EXISTS vw_monthly_trends;
DROP VIEW IF EXISTS vw_department_performance;
DROP VIEW IF EXISTS vw_provider_performance;
DROP VIEW IF EXISTS vw_appointment_type_performance;
DROP VIEW IF EXISTS vw_weekday_activity;
DROP VIEW IF EXISTS vw_appointment_details;
DROP VIEW IF EXISTS vw_schedule_details;


-- Helper: one row per appointment, with 0/1 status flags, month and weekday.
CREATE VIEW vw_appointment_details AS
SELECT
    appointment_id,
    patient_id,
    provider_id,
    department_id,
    appointment_date,
    appointment_type,
    appointment_status,
    substr(appointment_date, 1, 7) AS month,                       -- 'YYYY-MM'
    -- SQLite's %w gives 0 = Sunday ... 6 = Saturday; turn it into 1 = Monday ... 7 = Sunday.
    (CAST(strftime('%w', appointment_date) AS INTEGER) + 6) % 7 + 1 AS weekday_number,
    CASE WHEN appointment_status = 'Completed' THEN 1 ELSE 0 END AS is_completed,
    CASE WHEN appointment_status = 'Cancelled' THEN 1 ELSE 0 END AS is_cancelled,
    CASE WHEN appointment_status = 'No Show'   THEN 1 ELSE 0 END AS is_no_show,
    -- Durations count for Completed appointments only (NULL otherwise; AVG skips NULL).
    CASE WHEN appointment_status = 'Completed' THEN wait_minutes END  AS completed_wait_minutes,
    CASE WHEN appointment_status = 'Completed' THEN visit_minutes END AS completed_visit_minutes
FROM appointments;


-- Helper: one row per provider clinic day, with month and weekday.
CREATE VIEW vw_schedule_details AS
SELECT
    schedule_date,
    provider_id,
    department_id,
    available_slots,
    substr(schedule_date, 1, 7) AS month,
    (CAST(strftime('%w', schedule_date) AS INTEGER) + 6) % 7 + 1 AS weekday_number
FROM provider_schedules;


-- 1. Overall KPI summary: exactly one row.
CREATE VIEW vw_overall_kpis AS
WITH appointment_totals AS (
    SELECT
        COUNT(*)                       AS total_appointments,
        COUNT(DISTINCT patient_id)     AS unique_patients,
        COALESCE(SUM(is_completed), 0) AS completed_appointments,
        COALESCE(SUM(is_cancelled), 0) AS cancelled_appointments,
        COALESCE(SUM(is_no_show), 0)   AS no_show_appointments,
        AVG(completed_wait_minutes)    AS avg_wait_minutes,
        AVG(completed_visit_minutes)   AS avg_visit_minutes
    FROM vw_appointment_details
),
capacity_totals AS (
    SELECT COALESCE(SUM(available_slots), 0) AS available_slots
    FROM provider_schedules
),
reporting_period AS (
    -- First and last day found in the schedules or the appointments.
    SELECT MIN(day) AS period_start, MAX(day) AS period_end
    FROM (SELECT schedule_date AS day FROM provider_schedules
          UNION ALL
          SELECT appointment_date FROM appointments)
)
SELECT
    p.period_start,
    p.period_end,
    a.total_appointments,
    a.unique_patients,
    a.completed_appointments,
    a.cancelled_appointments,
    a.no_show_appointments,
    CASE WHEN a.total_appointments > 0
         THEN 1.0 * a.completed_appointments / a.total_appointments END AS completion_rate,
    CASE WHEN a.total_appointments > 0
         THEN 1.0 * a.cancelled_appointments / a.total_appointments END AS cancellation_rate,
    CASE WHEN a.total_appointments > 0
         THEN 1.0 * a.no_show_appointments / a.total_appointments END   AS no_show_rate,
    a.avg_wait_minutes,
    a.avg_visit_minutes,
    c.available_slots,
    -- Booking Rate: booked slots (every status) / available slots.
    CASE WHEN c.available_slots > 0
         THEN 1.0 * a.total_appointments / c.available_slots END        AS booking_rate,
    -- Completed Slot Utilization: slots that turned into a completed visit / available slots.
    CASE WHEN c.available_slots > 0
         THEN 1.0 * a.completed_appointments / c.available_slots END    AS completed_slot_utilization
FROM appointment_totals AS a
CROSS JOIN capacity_totals AS c
CROSS JOIN reporting_period AS p;


-- 2. Monthly trends: one row per month ('YYYY-MM').
CREATE VIEW vw_monthly_trends AS
WITH months AS (
    -- Every month that has capacity or appointments (UNION removes duplicates).
    SELECT month FROM vw_schedule_details
    UNION
    SELECT month FROM vw_appointment_details
),
appointment_counts AS (
    SELECT
        month,
        COUNT(*)                     AS total_appointments,
        SUM(is_completed)            AS completed_appointments,
        SUM(is_cancelled)            AS cancelled_appointments,
        SUM(is_no_show)              AS no_show_appointments,
        AVG(completed_wait_minutes)  AS avg_wait_minutes,
        AVG(completed_visit_minutes) AS avg_visit_minutes
    FROM vw_appointment_details
    GROUP BY month
),
capacity AS (
    SELECT month, SUM(available_slots) AS available_slots
    FROM vw_schedule_details
    GROUP BY month
),
combined AS (
    SELECT
        m.month,
        COALESCE(a.total_appointments, 0)     AS total_appointments,
        COALESCE(a.completed_appointments, 0) AS completed_appointments,
        COALESCE(a.cancelled_appointments, 0) AS cancelled_appointments,
        COALESCE(a.no_show_appointments, 0)   AS no_show_appointments,
        a.avg_wait_minutes,
        a.avg_visit_minutes,
        COALESCE(c.available_slots, 0)        AS available_slots
    FROM months AS m
    LEFT JOIN appointment_counts AS a ON a.month = m.month
    LEFT JOIN capacity AS c ON c.month = m.month
)
SELECT
    month,
    total_appointments,
    completed_appointments,
    cancelled_appointments,
    no_show_appointments,
    CASE WHEN total_appointments > 0 THEN 1.0 * completed_appointments / total_appointments END AS completion_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * cancelled_appointments / total_appointments END AS cancellation_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * no_show_appointments / total_appointments END   AS no_show_rate,
    avg_wait_minutes,
    avg_visit_minutes,
    available_slots,
    CASE WHEN available_slots > 0 THEN 1.0 * total_appointments / available_slots END     AS booking_rate,
    CASE WHEN available_slots > 0 THEN 1.0 * completed_appointments / available_slots END AS completed_slot_utilization
FROM combined;


-- 3. Department performance: one row per department, including departments
--    with no appointments or no capacity.
CREATE VIEW vw_department_performance AS
WITH appointment_counts AS (
    SELECT
        department_id,
        COUNT(*)                     AS total_appointments,
        SUM(is_completed)            AS completed_appointments,
        SUM(is_cancelled)            AS cancelled_appointments,
        SUM(is_no_show)              AS no_show_appointments,
        AVG(completed_wait_minutes)  AS avg_wait_minutes,
        AVG(completed_visit_minutes) AS avg_visit_minutes
    FROM vw_appointment_details
    GROUP BY department_id
),
capacity AS (
    SELECT department_id, SUM(available_slots) AS available_slots
    FROM provider_schedules
    GROUP BY department_id
),
combined AS (
    -- Start from the departments table so every department appears.
    SELECT
        d.department_id,
        d.department_name,
        COALESCE(a.total_appointments, 0)     AS total_appointments,
        COALESCE(a.completed_appointments, 0) AS completed_appointments,
        COALESCE(a.cancelled_appointments, 0) AS cancelled_appointments,
        COALESCE(a.no_show_appointments, 0)   AS no_show_appointments,
        a.avg_wait_minutes,
        a.avg_visit_minutes,
        COALESCE(c.available_slots, 0)        AS available_slots
    FROM departments AS d
    LEFT JOIN appointment_counts AS a ON a.department_id = d.department_id
    LEFT JOIN capacity AS c ON c.department_id = d.department_id
)
SELECT
    department_id,
    department_name,
    total_appointments,
    completed_appointments,
    cancelled_appointments,
    no_show_appointments,
    CASE WHEN total_appointments > 0 THEN 1.0 * completed_appointments / total_appointments END AS completion_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * cancelled_appointments / total_appointments END AS cancellation_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * no_show_appointments / total_appointments END   AS no_show_rate,
    avg_wait_minutes,
    avg_visit_minutes,
    available_slots,
    CASE WHEN available_slots > 0 THEN 1.0 * total_appointments / available_slots END     AS booking_rate,
    CASE WHEN available_slots > 0 THEN 1.0 * completed_appointments / available_slots END AS completed_slot_utilization
FROM combined;


-- 4. Provider performance: one row per provider, including providers
--    with capacity but no appointments.
CREATE VIEW vw_provider_performance AS
WITH appointment_counts AS (
    SELECT
        provider_id,
        COUNT(*)                     AS total_appointments,
        SUM(is_completed)            AS completed_appointments,
        SUM(is_cancelled)            AS cancelled_appointments,
        SUM(is_no_show)              AS no_show_appointments,
        AVG(completed_wait_minutes)  AS avg_wait_minutes,
        AVG(completed_visit_minutes) AS avg_visit_minutes
    FROM vw_appointment_details
    GROUP BY provider_id
),
capacity AS (
    SELECT provider_id, SUM(available_slots) AS available_slots
    FROM provider_schedules
    GROUP BY provider_id
),
combined AS (
    -- Start from the providers table so every provider appears.
    SELECT
        p.provider_id,
        p.provider_name,
        p.specialty,
        p.department_id,
        d.department_name,
        p.daily_slot_capacity,
        COALESCE(a.total_appointments, 0)     AS total_appointments,
        COALESCE(a.completed_appointments, 0) AS completed_appointments,
        COALESCE(a.cancelled_appointments, 0) AS cancelled_appointments,
        COALESCE(a.no_show_appointments, 0)   AS no_show_appointments,
        a.avg_wait_minutes,
        a.avg_visit_minutes,
        COALESCE(c.available_slots, 0)        AS available_slots
    FROM providers AS p
    JOIN departments AS d ON d.department_id = p.department_id
    LEFT JOIN appointment_counts AS a ON a.provider_id = p.provider_id
    LEFT JOIN capacity AS c ON c.provider_id = p.provider_id
)
SELECT
    provider_id,
    provider_name,
    specialty,
    department_id,
    department_name,
    daily_slot_capacity,
    total_appointments,
    completed_appointments,
    cancelled_appointments,
    no_show_appointments,
    CASE WHEN total_appointments > 0 THEN 1.0 * completed_appointments / total_appointments END AS completion_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * cancelled_appointments / total_appointments END AS cancellation_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * no_show_appointments / total_appointments END   AS no_show_rate,
    avg_wait_minutes,
    avg_visit_minutes,
    available_slots,
    CASE WHEN available_slots > 0 THEN 1.0 * total_appointments / available_slots END     AS booking_rate,
    CASE WHEN available_slots > 0 THEN 1.0 * completed_appointments / available_slots END AS completed_slot_utilization
FROM combined;


-- 5. Appointment-type performance: one row per appointment type.
--    No capacity columns: slots are not reserved per appointment type, so there
--    is no valid "available slots" denominator for a type.
CREATE VIEW vw_appointment_type_performance AS
SELECT
    appointment_type,
    COUNT(*)                     AS total_appointments,
    SUM(is_completed)            AS completed_appointments,
    SUM(is_cancelled)            AS cancelled_appointments,
    SUM(is_no_show)              AS no_show_appointments,
    CASE WHEN COUNT(*) > 0 THEN 1.0 * SUM(is_completed) / COUNT(*) END AS completion_rate,
    CASE WHEN COUNT(*) > 0 THEN 1.0 * SUM(is_cancelled) / COUNT(*) END AS cancellation_rate,
    CASE WHEN COUNT(*) > 0 THEN 1.0 * SUM(is_no_show) / COUNT(*) END   AS no_show_rate,
    AVG(completed_wait_minutes)  AS avg_wait_minutes,
    AVG(completed_visit_minutes) AS avg_visit_minutes
FROM vw_appointment_details
GROUP BY appointment_type;


-- 6. Weekday activity: one row per weekday that has capacity or appointments.
CREATE VIEW vw_weekday_activity AS
WITH weekdays AS (
    SELECT weekday_number FROM vw_schedule_details
    UNION
    SELECT weekday_number FROM vw_appointment_details
),
appointment_counts AS (
    SELECT
        weekday_number,
        COUNT(*)                     AS total_appointments,
        SUM(is_completed)            AS completed_appointments,
        SUM(is_cancelled)            AS cancelled_appointments,
        SUM(is_no_show)              AS no_show_appointments,
        AVG(completed_wait_minutes)  AS avg_wait_minutes,
        AVG(completed_visit_minutes) AS avg_visit_minutes
    FROM vw_appointment_details
    GROUP BY weekday_number
),
capacity AS (
    SELECT weekday_number, SUM(available_slots) AS available_slots
    FROM vw_schedule_details
    GROUP BY weekday_number
),
combined AS (
    SELECT
        w.weekday_number,
        COALESCE(a.total_appointments, 0)     AS total_appointments,
        COALESCE(a.completed_appointments, 0) AS completed_appointments,
        COALESCE(a.cancelled_appointments, 0) AS cancelled_appointments,
        COALESCE(a.no_show_appointments, 0)   AS no_show_appointments,
        a.avg_wait_minutes,
        a.avg_visit_minutes,
        COALESCE(c.available_slots, 0)        AS available_slots
    FROM weekdays AS w
    LEFT JOIN appointment_counts AS a ON a.weekday_number = w.weekday_number
    LEFT JOIN capacity AS c ON c.weekday_number = w.weekday_number
)
SELECT
    weekday_number,
    CASE weekday_number
        WHEN 1 THEN 'Monday'   WHEN 2 THEN 'Tuesday'  WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday' WHEN 5 THEN 'Friday'   WHEN 6 THEN 'Saturday'
        ELSE 'Sunday'
    END AS weekday_name,
    total_appointments,
    completed_appointments,
    cancelled_appointments,
    no_show_appointments,
    CASE WHEN total_appointments > 0 THEN 1.0 * completed_appointments / total_appointments END AS completion_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * cancelled_appointments / total_appointments END AS cancellation_rate,
    CASE WHEN total_appointments > 0 THEN 1.0 * no_show_appointments / total_appointments END   AS no_show_rate,
    avg_wait_minutes,
    avg_visit_minutes,
    available_slots,
    CASE WHEN available_slots > 0 THEN 1.0 * total_appointments / available_slots END     AS booking_rate,
    CASE WHEN available_slots > 0 THEN 1.0 * completed_appointments / available_slots END AS completed_slot_utilization
FROM combined;
