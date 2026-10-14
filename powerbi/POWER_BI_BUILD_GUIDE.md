# Power BI Dashboard Build Guide

> **Synthetic data only.** The dashboard shows computer-generated data. It does not
> describe real patients, providers, hospitals or clinics. Put this notice on every page.

This guide builds the dashboard by hand in **Power BI Desktop** (Windows) from the files
prepared in Phase 4A. Python cannot create or check a `.pbix` file. Building, checking and
saving the report are manual steps, recorded in
[POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md).

| You will use | File |
|---|---|
| Six data tables | `powerbi/data/*.csv` |
| Model specification | [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md) |
| Column types and meanings | [DATA_DICTIONARY.md](DATA_DICTIONARY.md) |
| DAX measures | [dax_measures.txt](dax_measures.txt) |
| Theme | [healthcare_theme.json](healthcare_theme.json) |
| Reference values | [expected_kpis.json](expected_kpis.json) |
| Final report (you create it) | `powerbi/healthcare_patient_flow_dashboard.pbix` |

## Step 0: Refresh the data files

Run these from the project folder in PowerShell. The last command rewrites
`powerbi/data/` and `powerbi/expected_kpis.json` from the validated database.

```powershell
.\.venv\Scripts\python.exe generate_data.py --appointments 5000 --seed 42
.\.venv\Scripts\python.exe prepare_data.py
.\.venv\Scripts\python.exe analyze_data.py
.\.venv\Scripts\python.exe prepare_powerbi_data.py
```

## Step 1: Create the file and change two settings

1. Open Power BI Desktop and choose **Blank report**.
2. Go to **File > Options and settings > Options**. Under **CURRENT FILE > Data Load**:
   - under *Time intelligence*, clear **Auto date/time**;
   - under *Relationships*, clear **Autodetect new relationships after data is
     loaded**. You will create the relationships yourself in Step 5.
3. Select **OK**.
4. Save the file now as `powerbi/healthcare_patient_flow_dashboard.pbix` (**File > Save
   as**), and save again after each step.

## Step 2: Import the six CSV files

Do this for each file in `powerbi/data/`:
- `appointments.csv`
- `provider_schedules.csv`
- `providers.csv`
- `departments.csv`
- `patients.csv`
- `date.csv`

1. **Home > Get data > Text/CSV**, then select the file.
2. In the preview window, check these settings:
   - **File origin:** `65001: Unicode (UTF-8)`;
   - **Delimiter:** Comma;
   - **Data type detection:** Based on entire dataset.
3. Select **Transform Data**. For the second and later files, use **Home > New Source >
   Text/CSV** inside Power Query.

In Power Query, rename each query: double-click its name in the Queries pane.

| File | Query (table) name |
|---|---|
| `appointments.csv` | `Appointments` |
| `provider_schedules.csv` | `ProviderSchedules` |
| `providers.csv` | `Providers` |
| `departments.csv` | `Departments` |
| `patients.csv` | `Patients` |
| `date.csv` | `Date` |

## Step 3: Set the data types in Power Query

Power Query adds a "Changed Type" step automatically. Check every column against this
list:
- To change a type, click the type icon in the column header. If asked, choose **Replace
  current**.
- **Text:** all ID columns and all names or labels.
- **Whole number:**
  - `Providers[daily_slot_capacity]`;
  - `Patients[age]`;
  - `ProviderSchedules[available_slots]`;
  - `Appointments[wait_minutes]` and `Appointments[visit_minutes]`;
  - `Date[year]`, `[quarter]`, `[month_number]`, `[year_month_sort]` and
    `[weekday_number]`.
- **Date:** `Appointments[appointment_date]`, `ProviderSchedules[schedule_date]`,
  `Date[date]`.
- **Date/Time:** `Appointments[scheduled_datetime]`, `[check_in_datetime]`,
  `[seen_datetime]`, `[checkout_datetime]`.
- **True/False:** `Date[is_weekend]`.

[DATA_DICTIONARY.md](DATA_DICTIONARY.md) lists the type of every column.

Then check for problems:
1. Turn on **View > Column quality** and set "Column profiling based on entire data set"
   (the status bar at the bottom).
2. Every column should show **0% Error**.
3. Blank values are expected only in `check_in_datetime`, `seen_datetime`,
   `checkout_datetime`, `wait_minutes` and `visit_minutes`. Those columns are blank for
   Cancelled and No Show appointments.
4. If a date or datetime column shows errors, change its type with **Using Locale…**
   and pick *English (United States)*.

Select **Home > Close & Apply**.

## Step 4: Check the row counts

In **Table view**, select each table. The row count appears at the bottom left. Compare
it with `dataset.row_counts` in `expected_kpis.json`. With seed 42 the counts are:

| Table | Rows |
|---|---|
| Appointments | 5,000 |
| ProviderSchedules | 626 |
| Providers | 12 |
| Departments | 6 |
| Patients | 1,250 |
| Date | 365 |

## Step 5: Create the relationships

1. Open **Model view**, then **Home > Manage relationships**. Delete any relationship
   that is not in the list below.
2. Select **New** for each relationship in the list. Pick the first table and column,
   then the second table and column, and set:
   - **Cardinality:** One to many (1:\*)
   - **Cross filter direction:** Single
   - **Make this relationship active:** ticked

| # | One side | Many side |
|---|---|---|
| 1 | `Date[date]` | `Appointments[appointment_date]` |
| 2 | `Date[date]` | `ProviderSchedules[schedule_date]` |
| 3 | `Departments[department_id]` | `Providers[department_id]` |
| 4 | `Providers[provider_id]` | `Appointments[provider_id]` |
| 5 | `Providers[provider_id]` | `ProviderSchedules[provider_id]` |
| 6 | `Patients[patient_id]` | `Appointments[patient_id]` |

Do **not** relate `Appointments[department_id]` or `ProviderSchedules[department_id]` to
Departments. [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md) explains why.

## Step 6: Date table, sorting, hiding and summarization

1. **Mark the date table.**
   1. Select the Date table, then **Table tools > Mark as date table**.
   2. Choose `date` and select OK.
2. **Sort columns.** Select a column in the Data pane, then **Column tools > Sort by
   column**:
   - `month_name` → `month_number`
   - `year_month` → `year_month_sort`
   - `weekday_name` → `weekday_number`
3. **Hide technical columns.** Right-click > **Hide in report view**:
   - in Appointments: `patient_id`, `provider_id`, `department_id`, `appointment_date`;
   - in ProviderSchedules: `provider_id`, `department_id`, `schedule_date`;
   - in Providers: `department_id`;
   - in Date: `month_number`, `year_month_sort`, `weekday_number`.
4. **Don't summarize.** Select the column, then **Column tools > Summarization > Don't
   summarize**:
   - `Date[year]` and `Date[quarter]`;
   - `Patients[age]`;
   - `Providers[daily_slot_capacity]`.

## Step 7: Import the theme

**View > Themes > Browse for themes**, then choose `powerbi/healthcare_theme.json`.

The theme sets:
- Segoe UI text, with dark navy titles;
- white visuals on a light grey page;
- no borders or shadows;
- medium blue as the first data colour.

The status colours are set per visual in Step 9:

| Status | Colour | Hex |
|---|---|---|
| Completed | Teal | `#1A8A7D` |
| Cancelled | Orange | `#D97B29` |
| No Show | Muted red | `#B4474F` |

Colour is never the only signal: every status chart also shows the status name on its
axis or legend, and data labels.

## Step 8: Create the measures

Open [dax_measures.txt](dax_measures.txt) and add the measures one at a time:
1. Select the home table named in the section heading.
2. Select **Home > New measure** and paste one measure (its name line and expression).
3. Under **Measure tools > Format**, set the format shown in its `// Format:` line:
   - **Counts:** *Whole number*, with the thousands separator (`,`) on.
   - **Rates:** *Percentage*, 1 decimal place.
   - **Minutes:** *Decimal number*, 1 decimal place.

The library has 16 measures:

| Group | Measures |
|---|---|
| Counts | Total Appointments, Unique Patients, Completed Appointments, Cancelled Appointments, No Show Appointments |
| Rates | Completion Rate, Cancellation Rate, No Show Rate |
| Durations | Average Wait Minutes, Average Visit Minutes |
| Capacity | Available Slots, Booking Rate, Completed Slot Utilization |
| Month over month | Previous Month Appointments, Month over Month Change, Month over Month Change Percent |

**Check the measures against the reference values:**
1. On a blank page, add a **Table** visual containing the 13 headline measures, with no
   slicers or filters.
2. Compare each value with its `display` value in `expected_kpis.json`. For seed 42,
   Total Appointments is 5,000, Booking Rate is 71.9% and Average Wait Minutes is 29.7.
3. Delete the page afterwards.

## Step 9: Build the three report pages

Page setup for every page:
- **Canvas:** select empty canvas, then **Format page > Canvas settings > Type: 16:9**
  (1280 × 720).
- **Title:** a text box at the top left with the page title (Segoe UI Semibold 18, dark
  navy).
- **Notice:** a small text box at the bottom: *"Synthetic data for a portfolio project.
  Not real patients or hospitals."*
- **Slicers:** each page's slicers filter only that page. Do not sync slicers between
  pages.
- **Visual interactions:** keep the defaults, so selecting a bar or slicer filters the
  other visuals on the page (**Format > Edit interactions** should show the filter icon
  on every visual). No exceptions are needed in this design. If you change one, write
  the reason in the checklist.

How to apply the formatting called for below:
- **Visual titles:** turn on the title under *Format visual > General > Title* and type
  the suggested title.
- **Status colours:** on any visual that uses `appointment_status`, set the colours
  under *Format visual > Visual > Bars / Columns > Colors* (Completed teal, Cancelled
  orange, No Show muted red).
- **Sort orders:** set each sort from the visual's **More options (…) > Sort axis**.

> **As built.** The tables below describe the approved dashboard: its pages, cards,
> slicers and charts. In the saved report, a few presentation details differ from the
> formatting suggestions here, such as automatic visual titles, colours and data labels.
> The project owner accepted them as final. They are listed under "Accepted design
> choices" in
> [POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md).

### Page 1: Operational Overview

Wireframe (16:9, six equal columns):

| Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 |
|---|---|---|---|---|---|
| Page title | ← | Date slicer | ← | Department slicer | Provider slicer |
| Card: Total Appointments | Card: Unique Patients | Card: Completion Rate | Card: No Show Rate | Card: Average Wait Minutes | Card: Booking Rate |
| Line: Monthly Appointment Volume | ← | ← | ← | Column: Appointments by Status | ← |
| Bar: Appointments by Department | ← | Matrix: Department KPIs | ← | ← | ← |
| Synthetic-data notice | ← | ← | ← | ← | ← |

`←` means the visual continues from the cell to its left.

| # | Visual type | Fields / measures | Axis / legend | Sort | Title | Formatting and interaction |
|---|---|---|---|---|---|---|
| 1 | Slicer | `Date[date]` | n/a | n/a | Date | Style: *Between* (date range) |
| 2 | Slicer | `Departments[department_name]` | n/a | A–Z | Department | Style: Dropdown, multi-select, "Select all" on. Filters the Provider slicer |
| 3 | Slicer | `Providers[provider_name]` | n/a | A–Z | Provider | Style: Dropdown, multi-select, "Select all" on |
| 4 | Card | Total Appointments | n/a | n/a | Total Appointments | `#,0`; show category label |
| 5 | Card | Unique Patients | n/a | n/a | Unique Patients | `#,0` |
| 6 | Card | Completion Rate | n/a | n/a | Completion Rate | `0.0%` |
| 7 | Card | No Show Rate | n/a | n/a | No Show Rate | `0.0%` |
| 8 | Card | Average Wait Minutes | n/a | n/a | Average Wait (minutes) | `0.0` |
| 9 | Card | Booking Rate | n/a | n/a | Booking Rate | `0.0%` |
| 10 | Line chart | Y: Total Appointments | X: `Date[year_month]` | `year_month`, ascending | Monthly Appointment Volume | Markers on; data labels on; Y axis starts at 0 |
| 11 | Clustered column chart | Y: Total Appointments | X: `Appointments[appointment_status]` | Total Appointments, descending | Appointments by Status | Data labels on; status colours |
| 12 | Clustered bar chart | X: Total Appointments | Y: `Departments[department_name]` | Total Appointments, descending | Appointments by Department | Data labels on; one colour (medium blue) |
| 13 | Matrix | Values: Total Appointments, Completion Rate, No Show Rate, Average Wait Minutes, Booking Rate, Completed Slot Utilization | Rows: `Departments[department_name]` | Any (as built: No Show Rate, descending) | Department KPIs | Row subtotals (Total) on; the Total row must match the cards. Capacity columns are valid here because Department defines capacity |

### Page 2: Capacity and Provider Performance

Wireframe:

| Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 |
|---|---|---|---|---|---|
| Page title | ← | Date slicer | ← | Department slicer | Provider slicer |
| Card: Total Appointments | ← | Card: Available Slots | Card: Booking Rate | ← | Card: Completed Slot Utilization |
| Bar: Booking Rate by Department | ← | ← | Bar: Booking Rate by Provider | ← | ← |
| Combo: Monthly Appointments vs Available Slots | ← | ← | Matrix: Provider Capacity and Performance | ← | ← |
| Synthetic-data notice | ← | ← | ← | ← | ← |

| # | Visual type | Fields / measures | Axis / legend | Sort | Title | Formatting and interaction |
|---|---|---|---|---|---|---|
| 1 | Slicer | `Date[date]` | n/a | n/a | Date | Between |
| 2 | Slicer | `Departments[department_name]` | n/a | A–Z | Department | Dropdown; filters the Provider slicer |
| 3 | Slicer | `Providers[provider_name]` | n/a | A–Z | Provider | Dropdown |
| 4 | Card | Total Appointments | n/a | n/a | Total Appointments | `#,0` |
| 5 | Card | Available Slots | n/a | n/a | Available Slots | `#,0` |
| 6 | Card | Booking Rate | n/a | n/a | Booking Rate | `0.0%` |
| 7 | Card | Completed Slot Utilization | n/a | n/a | Completed Slot Utilization | `0.0%` |
| 8 | Clustered bar chart | X: Booking Rate | Y: `Departments[department_name]` | Booking Rate, descending | Booking Rate by Department | Data labels `0.0%`; X axis starts at 0; tooltips: add Total Appointments and Available Slots |
| 9 | Clustered bar chart | X: Booking Rate | Y: `Providers[provider_name]` | Booking Rate, descending | Booking Rate by Provider | Data labels `0.0%`; X axis starts at 0; tooltips: Total Appointments, Available Slots |
| 10 | Line and clustered column chart | Column Y: Available Slots; Line Y: Total Appointments | X: `Date[year_month]` | `year_month`, ascending | Available Slots and Total Appointments | Legend on; turn **off** the secondary Y axis so both share one scale; data labels optional |
| 11 | Matrix | Values: Total Appointments, Completion Rate, No Show Rate, Average Wait Minutes, Available Slots, Booking Rate, Completed Slot Utilization | Rows: `Providers[provider_name]` | Provider A–Z | Provider Capacity and Performance | Row subtotals (Total) on; the Total row must match the cards |

With no slicer selections, these cards must match `expected_kpis.json`. Seed-42 values:
- Total Appointments: 5,000
- Available Slots: 6,956
- Booking Rate: 71.9%
- Completed Slot Utilization: 57.5%

The Average Visit Minutes measure is still in the DAX library, but it is not shown on
this page.

### Page 3: Patient and Appointment Patterns

**No capacity measures on this page.** Available Slots, Booking Rate and Completed Slot
Utilization are not shown. Appointment type, appointment status and patient fields such
as age group and insurance type do not define provider capacity (see the data model).

Wireframe:

| Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 |
|---|---|---|---|---|---|
| Page title | Date slicer | Department slicer | Provider slicer | Appointment Type slicer | Appointment Status slicer |
| Card: Total Appointments | ← | Card: Unique Patients | Card: Completion Rate | ← | Card: No Show Rate |
| Bar: Appointments by Type | ← | Column: Appointment Status by Type | ← | Column: Appointments by Weekday | ← |
| Bar: Appointments by Age Group | ← | ← | Pie: Appointments by Insurance Type | ← | ← |
| Synthetic-data notice | ← | ← | ← | ← | ← |

| # | Visual type | Fields / measures | Axis / legend | Sort | Title | Formatting and interaction |
|---|---|---|---|---|---|---|
| 1 | Slicer | `Date[date]` | n/a | n/a | Date | Between |
| 2 | Slicer | `Departments[department_name]` | n/a | A–Z | Department | Dropdown |
| 3 | Slicer | `Providers[provider_name]` | n/a | A–Z | Provider | Dropdown; filtered by the Department slicer |
| 4 | Slicer | `Appointments[appointment_type]` | n/a | A–Z | Appointment Type | Dropdown |
| 5 | Slicer | `Appointments[appointment_status]` | n/a | A–Z | Appointment Status | Dropdown. Selecting one status makes Completion Rate and No Show Rate 0% or 100%, which is expected |
| 6 | Card | Total Appointments | n/a | n/a | Total Appointments | `#,0` |
| 7 | Card | Unique Patients | n/a | n/a | Unique Patients | `#,0` |
| 8 | Card | Completion Rate | n/a | n/a | Completion Rate | `0.0%` |
| 9 | Card | No Show Rate | n/a | n/a | No Show Rate | `0.0%` |
| 10 | Clustered bar chart | X: Total Appointments | Y: `Appointments[appointment_type]` | Total Appointments, descending | Appointments by Type | Data labels optional |
| 11 | Stacked column chart | Y: Total Appointments | X: `Appointments[appointment_type]`; Legend: `Appointments[appointment_status]` | Total Appointments, descending | Appointment Status by Type | Legend on, so each status is named; status colours |
| 12 | Clustered column chart | Y: Total Appointments | X: `Date[weekday_name]` | `weekday_name`, ascending (Monday first) | Appointments by Weekday | Weekend days have no appointments and are not shown |
| 13 | Clustered bar chart | X: Total Appointments | Y: `Patients[age_group]` | `age_group`, ascending (0-17 first) | Appointments by Age Group | Data labels optional |
| 14 | Pie chart | Values: Total Appointments | Legend: `Patients[insurance_type]` | Total Appointments, descending | Appointments by Insurance Type | Detail labels: value and percent of total |

## Step 10: Test the report

Record each result in
[POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md).

1. **No slicer selections.** Every card matches `expected_kpis.json`.
2. **Test every slicer** on every page. Pick one value, check that all visuals on the page
   change, then clear it.
3. **Department filters Provider.** Select one department. The Provider slicer must list
   only that department's providers (two per department with seed 42). The provider
   visuals must show only those providers.
4. **Ordering.**
   - Monthly axes run January to December, not alphabetically.
   - The weekday axis runs Monday to Friday.
5. **Blank and zero behaviour.** Pick a date range with no appointments, such as a
   weekend day. Counts show blank (shown as "(Blank)" on cards, which is expected) and
   rates show blank, never an error.
6. **Capacity only on Pages 1 and 2.** Page 3 has no capacity measure.

## Step 11: Save and take screenshots

1. Save the report as `powerbi/healthcare_patient_flow_dashboard.pbix`.
2. Take one full-page screenshot of each page with no slicer selections:
   - in Power BI Desktop, use **View > Fit to page** first;
   - capture with **Windows key + Shift + S** (Snipping Tool) or **File > Export > Export
     to PDF**.
3. Save the images to `screenshots/`:
   - `screenshots/powerbi_operational_overview.png`
   - `screenshots/powerbi_capacity_provider_performance.png`
   - `screenshots/powerbi_patient_appointment_patterns.png`
4. Complete the verification checklist.

Only report the dashboard as complete once the `.pbix` file and the three screenshots
exist and the checklist is complete. In this project, all three conditions are met: see
the verification record in
[POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md).
