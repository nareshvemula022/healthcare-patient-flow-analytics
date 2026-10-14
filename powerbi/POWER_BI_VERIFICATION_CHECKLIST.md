# Power BI Verification Checklist

> **Synthetic data only.** Python tests cover the data files, documents and saved
> artifacts. They cannot open, render or calculate a `.pbix` report, so the report itself
> was checked by hand in Power BI Desktop.

## Verification record (Phase 4B)

- **Date:** 2026-10-14
- **Report:** `powerbi/healthcare_patient_flow_dashboard.pbix` (335,165 bytes)
- **Power BI Desktop checks:** done by the project owner and reported as passed (items
  marked **[U]**)
- **File and screenshot review:** done in the repository (items marked **[F]** and
  **[S]**)
- **Power BI Desktop version:** not recorded
- **Approval:** the project owner approved the saved `.pbix` and the three screenshots as
  the **final dashboard**. The visual titles, sizing, layout, colours and formatting are
  accepted as built. No further manual Power BI changes are planned.

### How to read this checklist

Each item is marked with how it was verified:

| Mark | Meaning |
|---|---|
| **[F]** | **Automated file verification.** Checked from files in the repository by `pytest` or file inspection, without Power BI Desktop. |
| **[S]** | **Screenshot-visible verification.** Seen in the saved screenshots and compared with the data. A screenshot shows only what is on the canvas. It does **not** prove hidden model settings such as data types, relationship direction, sort-by-column or measure formats. |
| **[U]** | **User-confirmed in Power BI Desktop.** The project owner did this and reported the result. It is not independently verifiable from the repository. |
| **[A]** | **Accepted design choice.** Differs from the original plan and was approved by the project owner as final. See [Accepted design choices](#accepted-design-choices). |
| **n/a** | Not checked and not required for the approved dashboard. |

## 1. Data import

- [x] **[F]** The six snapshot CSV files exist in `powerbi/data/` and match SQLite (row
      counts, keys and headline KPIs; `tests/test_powerbi_assets.py`).
- [x] **[U]** The six tables were imported and used to build the model.
- [x] **[S]** The Total Appointments card (5000) and Available Slots card (6956) equal
      the full Appointments and ProviderSchedules totals, so all rows were loaded.
- n/a Power Query *Column quality* was not recorded.

## 2. Data types

- [x] **[F]** The CSV files store IDs as text, dates as ISO `YYYY-MM-DD`, datetimes as
      `YYYY-MM-DD HH:MM:SS`, and blank visit times and durations for Cancelled and No
      Show appointments.
- n/a The column types set inside Power BI were not recorded one by one. The date
      slicers and the date-ordered monthly axes **[S]** are consistent with a working
      Date column. Screenshots cannot prove the stored types.

## 3. Relationships

- [x] **[U]** Six active, one-to-many, single-direction relationships were created as in
      `POWER_BI_DATA_MODEL.md`.
- [x] **[U]** **Department-to-provider filtering:** selecting Cardiology limited the
      Provider choices. The data has two Cardiology providers, Dr. Casey Galloway and
      Dr. Taylor Ashford.
- n/a Hiding technical columns from report view was not recorded. This doesn't affect
      the results.

## 4. Date table and sorting

- [x] **[U]** **Auto date/time** is off for this file.
- [x] **[U]** Date is marked as the date table using `Date[date]`.
- [x] **[U]** Sort-by-column is set:
  - `month_name` by `month_number`;
  - `year_month` by `year_month_sort`;
  - `weekday_name` by `weekday_number`.
- [x] **[S]** **Monthly ordering:** the monthly axes on Pages 1 and 2 run Jan 2025 → Dec
      2025 in date order.
- [x] **[S]** **Weekday ordering:** the Page 3 weekday axis runs Monday → Friday.

## 5. DAX measures

- [x] **[F]** `powerbi/dax_measures.txt` contains all 16 measures. Every rate uses
      DIVIDE, and the definitions match Phase 3 (`tests/test_powerbi_assets.py`).
- [x] **[U]** All 16 measures were created in the report.
- [x] **[S]** No visual shows an error.
- [x] **[A]** The count cards show `5000` and `1229` without a thousands separator. The
      values are correct, and this display is accepted as final.

## 6. KPI reconciliation with `expected_kpis.json` (no slicers applied)

Expected values are the `display` values in `powerbi/expected_kpis.json` (seed 42).

| KPI | Expected (seed 42) | Power BI value | Source | Result |
|---|---|---|---|---|
| Reporting period | 01/01/2025 – 12/31/2025 | Date slicer 01-01-2025 – 31-12-2025 (day-month-year display) | [S] | Match |
| Total Appointments | 5,000 | 5000 | [S] [U] | Match |
| Unique Patients | 1,229 | 1229 | [S] [U] | Match |
| Completed Appointments | 4,000 | Status column chart at about 4K, no data label | [S] | Consistent |
| Cancelled Appointments | 573 | Status column chart, no data label | [S] | Not displayed as a number |
| No Show Appointments | 427 | 427 with the No Show status slicer selected | [U] | Match |
| Completion Rate | 80.0% | 80.0% | [S] [U] | Match |
| Cancellation Rate | 11.5% | Not on a card (not required by the approved design) | n/a | Not displayed |
| No Show Rate | 8.5% | 8.5% | [S] [U] | Match |
| Average Wait Minutes | 29.7 | 29.7 | [S] [U] | Match |
| Average Visit Minutes | 32.0 | Not on a card (not required by the approved design) | n/a | Not displayed |
| Available Slots | 6,956 | 6956 | [S] [U] | Match |
| Booking Rate | 71.9% | 71.9% | [S] [U] | Match |
| Completed Slot Utilization | 57.5% | 57.5% | [S] [U] | Match |

- [x] **[S] [U]** Every KPI shown on a card matches `expected_kpis.json`. No mismatches
      were found.
- [x] **[S]** The Total rows of the Page 1 department matrix and the Page 2 provider
      matrix match the cards: 5000, 80.0%, 8.5%, 29.7, 6956, 71.9%, 57.5%.
- [x] **[S]** These screenshot values were recomputed from `powerbi/data/` and match:
  - all six department matrix rows;
  - sampled provider matrix rows;
  - weekday, appointment-type and age-group volumes;
  - monthly volumes and slots;
  - insurance-type shares (49.88%, 21%, 20.42%, 8.7%).
- [x] **[F]** The measures that produce Cancellation Rate and Average Visit Minutes are in
      the DAX library and were created in the report **[U]**. The approved pages just
      don't display them.

## 7. Slicers and interactions

- [x] **[U]** **Slicer testing:**
  - Department = Cardiology gave **705** appointments, which matches the data.
  - Appointment Status = No Show gave **427** appointments and a **100.0%** No Show Rate,
    as expected when only No Show rows are selected.
- [x] **[U]** All slicers were cleared before saving. **[S]** is consistent: every
      dropdown slicer shows "All" and the date slicers span the full year.
- [x] **[S]** The slicers on each page match the approved design:
  - Pages 1–2: Date, Department, Provider;
  - Page 3: Date, Department, Provider, Appointment Type, Appointment Status.
- n/a Testing the remaining slicers one by one, the interaction settings and slicer
      syncing was not recorded.

## 8. Blank and zero behaviour

- [x] **[F]** Every DAX division uses DIVIDE, so a zero or blank denominator returns a
      blank instead of an error. The SQL views, which the DAX matches, are tested with
      zero denominators (`tests/test_analytics.py`).
- n/a An empty date range was not tested in Power BI.

## 9. Capacity measure limitation

- [x] **[S]** Available Slots, Booking Rate and Completed Slot Utilization appear only on
      Pages 1 and 2. There they are used with Date, Department and Provider (department
      matrix, provider matrix, booking-rate bars, monthly slots).
- [x] **[S]** Page 3 shows **no** capacity measure. Its cards are Total Appointments,
      Completion Rate, Unique Patients and No Show Rate.
- [x] **[A]** Page 3's Appointment Status slicer changes Completion Rate and No Show Rate
      to 0% or 100% when one status is selected. This is expected and accepted. It does
      not involve capacity.

## 10. Layout and readability

- [x] **[S]** Each page is a 16:9 canvas. The screenshots are 1348 × 756 and 1347 × 755
      pixels.
- [x] **[S]** **No unexplained blank visuals:** every visual shows data with no slicer
      selections.
- [x] **[S]** No error messages are visible.
- [x] **[S]** No accidental slicer selections are visible.
- [x] **[S]** No visuals overlap.
- [x] **[S] No clipped text** is visible. Both matrices show a scroll bar (Page 1
      vertical, Page 2 horizontal), but every row, column and Total row is visible in the
      screenshots. **[A]**
- [x] **[A]** The visual titles are Power BI's automatic titles, such as "Total
      Appointments by department_name". Slicer headers show column names. The titles are
      factual and make no claims.
- [x] **[A]** Colours:
  - the Page 1 status chart uses one blue;
  - Page 3 shows Cancelled blue, Completed teal and No Show orange;
  - the Page 3 legend names every status, so meaning does not depend on colour alone.
- [x] **[S]** The look is consistent with the imported theme (white visuals, no borders or
      shadows). The theme import itself is **[U]**.
- Non-blocking capture artifacts **[S]**. They look like a mouse cursor, text cursor or
  hover state captured with the screenshot. No values are hidden.
  - Page 1: a small blue mark inside the department matrix.
  - Page 1: a small mark after the "department_name" slicer header.
  - Page 2: the Department slicer shows its hover header icons.
  - Page 3: the Completion Rate card shows a hover or focus outline.

## 11. Synthetic-data statement

- [x] **[S]** Nothing in the report claims to show real patients, a real hospital or real
      results.
- [x] **[S]** No recommendations or business outcomes are stated on the pages.
- [x] **[A]** The pages have no on-canvas synthetic-data notice or page-title text boxes.
      The synthetic-data statement is in the README, the data dictionary, the data model,
      `expected_kpis.json` and this checklist.

## 12. Files

- [x] **[F]** The report is saved as `powerbi/healthcare_patient_flow_dashboard.pbix`:
  - it is not empty;
  - it is the only `.pbix` in the project, and none is under `powerbi/data/`;
  - Git does not ignore it.

  The tests check only the file's presence and size. They do not open its proprietary
  contents.
- [x] **[F]** Dashboard screenshots are saved, one per page with no slicer selections.
      They are valid PNG files and Git does not ignore them:
  - `screenshots/powerbi_operational_overview.png`
  - `screenshots/powerbi_capacity_provider_performance.png`
  - `screenshots/powerbi_patient_appointment_patterns.png`
- [x] **[F]** The README roadmap marks Phase 4 complete after these checks.

## Accepted design choices

The project owner approved the dashboard as built. These differences from the original
build plan are accepted as final. None of them changes a KPI value.

1. **Page 2 cards:** Total Appointments, Available Slots, Booking Rate, Completed Slot
   Utilization. Average Visit Minutes is not required on the page.
2. **Page 3 slicers:** Date, Department, Provider, Appointment Type, Appointment Status.
   Age Group and Insurance Type are shown as charts, not slicers.
3. **Page 3 charts:**
   - status by appointment type is a stacked column chart;
   - insurance type is a pie chart with rounded "K" labels and percentages.
4. **Page 2 combo chart:** Available Slots are the columns and Total Appointments the
   line, on one shared axis.
5. **Page 1 monthly chart:** a smoothed line whose Y axis starts near 360 rather than 0.
   Month-to-month differences therefore look larger than a zero-based axis would show.
6. **Page 1 department matrix:** also shows Booking Rate and Completed Slot Utilization.
   These are valid there because Department defines capacity.
7. **Formatting:**
   - automatic visual titles and column-name slicer headers;
   - count cards without thousands separators;
   - status colours as built;
   - most bar and column charts without data labels.
8. **No on-canvas page titles or synthetic-data notice.** The repository documents state
   that the data is synthetic.
