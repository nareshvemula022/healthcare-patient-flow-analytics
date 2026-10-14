# Power BI Verification Checklist

> **Synthetic data only.** Complete this checklist by hand in Power BI Desktop. Python
> tests cover the data files and documents, but they cannot open, render or calculate a
> `.pbix` report.

Record the date you checked, the Power BI Desktop version, and a tick or a note for each
item. Fix every failed item before reporting the dashboard as complete.

- Checked by: ____________
- Date: ____________
- Power BI Desktop version: ____________

## 1. Data import

- [ ] All six tables are imported and renamed: Appointments, ProviderSchedules,
      Providers, Departments, Patients, Date.
- [ ] The row counts match `dataset.row_counts` in `expected_kpis.json`. Seed 42:
  - Appointments: 5,000
  - ProviderSchedules: 626
  - Providers: 12
  - Departments: 6
  - Patients: 1,250
  - Date: 365
- [ ] Power Query **Column quality** shows 0% errors in every column.

## 2. Data types

- [ ] Every ID column is **Text**: appointment_id, patient_id, provider_id,
      department_id.
- [ ] These columns are **Date**: appointment_date, schedule_date, `Date[date]`.
- [ ] These columns are **Date/Time**: scheduled_datetime, check_in_datetime,
      seen_datetime, checkout_datetime.
- [ ] These columns are **Whole number**: wait_minutes, visit_minutes, available_slots,
      daily_slot_capacity, age, and the Date number columns.
- [ ] `Date[is_weekend]` is **True/False**.
- [ ] Blank visit times and durations appear only on Cancelled and No Show rows.

## 3. Relationships

- [ ] Exactly six relationships exist, as listed in `POWER_BI_DATA_MODEL.md`.
- [ ] Each one is **One to many**, **Single** direction and **Active**. The one side is
      Date, Departments, Providers or Patients.
- [ ] There is no relationship on `Appointments[department_id]` or
      `ProviderSchedules[department_id]`.
- [ ] Technical ID, date-key and sort columns are hidden from report view.

## 4. Date table and sorting

- [ ] **Auto date/time** is off for this file.
- [ ] Date is marked as the date table using `Date[date]`.
- [ ] Each Date label column is sorted by its number column:
  - `month_name` by `month_number`;
  - `year_month` by `year_month_sort`;
  - `weekday_name` by `weekday_number`.
- [ ] **Monthly ordering:** every monthly axis runs Jan 2025 → Dec 2025 in date order,
      not alphabetically.
- [ ] **Weekday ordering:** the weekday axis runs Monday → Friday.

## 5. DAX measures

- [ ] All 16 measures from `dax_measures.txt` exist with exactly those names.
- [ ] Formats are set as follows:
  - counts: whole number with thousands separator;
  - rates: percentage with 1 decimal;
  - minutes: decimal with 1 decimal.
- [ ] No measure shows an error. Previous Month Appointments, Month over Month Change
      and Month over Month Change Percent are blank for Jan 2025, which has no previous
      month.

## 6. KPI reconciliation with `expected_kpis.json` (no slicers applied)

Compare each card or table value with the `display` value in `powerbi/expected_kpis.json`.

| KPI | Expected (seed 42) | Power BI value | Match? |
|---|---|---|---|
| Reporting period | 01/01/2025 – 12/31/2025 | | |
| Total Appointments | 5,000 | | |
| Unique Patients | 1,229 | | |
| Completed Appointments | 4,000 | | |
| Cancelled Appointments | 573 | | |
| No Show Appointments | 427 | | |
| Completion Rate | 80.0% | | |
| Cancellation Rate | 11.5% | | |
| No Show Rate | 8.5% | | |
| Average Wait Minutes | 29.7 | | |
| Average Visit Minutes | 32.0 | | |
| Available Slots | 6,956 | | |
| Booking Rate | 71.9% | | |
| Completed Slot Utilization | 57.5% | | |

If the data was regenerated with other settings, use the values in the current
`expected_kpis.json` instead of this column.

- [ ] Every value matches.
- [ ] The Total row of each matrix equals the matching card.

## 7. Slicers and interactions

- [ ] **Slicer testing:** every slicer on every page was tested. Each time, one value
      was selected, all visuals on that page changed, and the slicer was cleared.
      - Page 1: Date, Department, Provider.
      - Page 2: Date, Department, Provider.
      - Page 3: Date, Department, Appointment Type, Age Group, Insurance Type.
- [ ] **Department-to-provider filtering:** selecting one department leaves only that
      department's providers in the Provider slicer (2 per department with seed 42). The
      provider visuals show only those providers.
- [ ] Visual interactions are left at the default (filter) on every page. Any exception
      is written here with its reason: ____________
- [ ] Slicers are not synced between pages.

## 8. Blank and zero behaviour

- [ ] A date range with no appointments (for example a single weekend day) shows blank
      counts and rates, never an error or `NaN`.
- [ ] Rates never show "Infinity" or an error. Every division uses DIVIDE.

## 9. Capacity measure limitation

- [ ] Available Slots, Booking Rate and Completed Slot Utilization appear only on Pages
      1 and 2. They are used only with Date, Department and Provider filters.
- [ ] Page 3 shows **no** capacity measure. No visual shows capacity by appointment
      type, age group, gender or insurance type.

## 10. Layout and readability

- [ ] Each page is 16:9 and follows its wireframe in `POWER_BI_BUILD_GUIDE.md`.
- [ ] Every visual has a clear, factual title, with no recommendations or claims.
- [ ] Data labels and axis labels are readable at **Fit to page**.
- [ ] Visuals are aligned and evenly spaced.
- [ ] **No clipped text** in titles, cards, slicers, axis labels or matrix headers.
- [ ] **No unexplained blank visuals** with no slicer selections.
- [ ] **Colour consistency:** Completed is teal, Cancelled orange and No Show muted red
      on every status visual, and status names are also shown as labels.
- [ ] The theme `healthcare_theme.json` is applied: Segoe UI, dark navy titles, light
      grey page, no shadows.

## 11. Synthetic-data statement

- [ ] Every page shows the synthetic-data notice.
- [ ] Nothing in the report claims to show real patients, a real hospital or real
      results.
- [ ] No recommendations or business outcomes are stated.

## 12. Files

- [ ] The report is saved as `powerbi/healthcare_patient_flow_dashboard.pbix`.
- [ ] Dashboard screenshots are saved, one per page with no slicer selections:
  - `screenshots/page1_operational_overview.png`
  - `screenshots/page2_capacity_provider_performance.png`
  - `screenshots/page3_patient_appointment_patterns.png`
- [ ] The README roadmap was updated only after everything above passed.
