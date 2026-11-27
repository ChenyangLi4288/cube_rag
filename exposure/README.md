# Exposure series

Monthly exposure for rate questions (`÷E`, ALGEBRA §10; EXPERIMENTS "rate trend" and X6). STUDENT_START task 5,
issue #4. Built by `scripts/build_exposure.py` from frozen public downloads (`data/<ds>/exposure/raw/` +
`MANIFEST.json`, not committed); these derived files are small public aggregates, so they are committed like
`lattices/` (STATE.md E1).

| File | Content |
|---|---|
| `vaers.csv`, `asrs.csv` | `period` (YYYY-MM), `series`, `value` (count), `source` |
| `coverage.csv` | per series: first and last month, number of months, gaps inside the range |
| `BUILD.json` | build time, git commit, sha256 of every input file |

## Rules

- A row is a complete calendar month. A month the source does not cover is **absent, never 0**.
- Daily data are summed by month. Weekly data are spread evenly over the days of the week, then summed. Cumulative
  data are differenced first.
- The first month of a reporting period counts as complete: doses before the first reported week are either inside
  the first cumulative value (IQVIA flu) or zero because the vaccine was not yet available (COVID-19 Dec 2020 and
  Sep 2023). The last month is kept only if fully covered (so COVID-19 May 2023, 1–9 May only, is dropped).

## VAERS (CDC doses), 2019-01 to 2023-12

| Series | Measure | Source | Months |
|---|---|---|---|
| `covid19_doses` | COVID-19 doses administered, all ages, all settings, by administration date | CDC [rh2h-3yt2](https://data.cdc.gov/d/rh2h-3yt2) | 2020-12 … 2023-04 |
| `covid19_doses_age_5_11`, `_12_17`, `_18_64`, `_65plus` | same, by age band, **by report date** (differences of CDC's cumulative 5+/12+/18+/65+ columns) | CDC [unsk-b7fc](https://data.cdc.gov/d/unsk-b7fc) | from 2021-12 / 2021-06 / 2021-04 / 2021-04 … 2023-04 |
| `covid19_doses_iqvia_adults` | COVID-19 doses, adults 18+, retail pharmacies and physician offices only (IQVIA) | CDC [ewpg-rz7g](https://data.cdc.gov/d/ewpg-rz7g) | 2023-09 … 2023-12 |
| `flu_doses_iqvia_adults` | influenza doses, adults 18+, retail pharmacies and physician offices only (IQVIA) | CDC [ysd3-txwj](https://data.cdc.gov/d/ysd3-txwj) | Aug–Apr/May of each season, 2019-08 … 2023-12 |
| `flu_doses_iqvia_age_18_49`, `_50_64`, `_65plus` | same, by age group (the three add up to 18+) | CDC ysd3-txwj | same |
| `flu_doses_distributed` | influenza doses **distributed** (supply, all settings) | CDC [ph8r-wzxn](https://data.cdc.gov/d/ph8r-wzxn) | Jul–Feb of each season, 2019-01 … 2023-12 |

VAERS `vax_type` → series: `COVID19`, `COVID19-2` → `covid19_*`; `FLU3`, `FLU4`, `FLUA3/4`, `FLUC3/4`, `FLUN3/4`,
`FLUR3/4`, `FLUX` (and the rare `FLU(H1N1)`, `FLUX(H1N1)`) → `flu_*`. No other vaccine has a series.

**Coverage gaps (VAERS)**

- **No public monthly doses for any other vaccine.** In 2019 that is most VAERS reports: zoster (`VARZOS`) 37%,
  pneumococcal 12%, MMR, Tdap, HPV, hepatitis. CDC publishes only annual survey coverage (NHIS, NIS) for these.
- **Flu, Jan–Jul 2019:** no administered doses (the IQVIA series starts with the 2019–20 season). Distributed doses
  exist for Jan–Feb 2019 (end of the 2018–19 season), but they measure supply, not shots given.
- **Flu, Jun–Jul each year** (and May in some seasons): outside the IQVIA reporting season; few doses are given then.
- **COVID-19, May–Aug 2023:** CDC stopped collecting doses administered when the public health emergency ended
  (data end 9 May 2023). From Sep 2023 only the IQVIA adult pharmacy/office series exists; it is a different measure
  (no children, no other settings), so it is a separate series and must not be joined to `covid19_doses`.
- IQVIA series (`*_iqvia_*`) cover retail pharmacies and physician offices only (not workplaces, public health clinics,
  long-term care). `83ng-twza` is an older release of the same flu estimates (2–3% lower per season); it is kept in
  `raw/` for the record, and `ysd3-txwj` is used.
- Age bands are by report date, `covid19_doses` by administration date, so the bands do not add up to the national
  series month by month (2022-01 … 2023-04: bands 4.8% higher, from late-reported 2021 doses). Reports
  with unknown age are in neither band.

So for X6, VAERS rates are possible for COVID-19 (2021-01 … 2023-04) and flu (from 2019-08, adults, IQVIA settings);
"2019 against 2021–2023" as rates works for flu only, from Aug 2019 (STATE.md E5).

## ASRS (flight operations), 2018-01 to 2023-12, all 72 months

| Series | Measure | Source |
|---|---|---|
| `opsnet_total` | airport operations (takeoffs + landings) at FAA and contract towered airports, all users | FAA OPSNET Airport Operations |
| `opsnet_itinerant` | itinerant operations (sum of the four below) | same |
| `opsnet_itinerant_air_carrier`, `_air_taxi`, `_general_aviation`, `_military` | itinerant operations by user class | same |
| `opsnet_local_civil`, `opsnet_local_military` | local operations (e.g. pattern work) | same |
| `t100_departures` | departures performed, all carriers, all segments with a U.S. endpoint | BTS T-100 Segment (All Carriers) |
| `t100_departures_domestic` | same, origin and destination in the U.S. | same |
| `t100_departures_us_carriers` | same, U.S. carriers only (`DATA_SOURCE` DU, IU) | same |

Main ASRS series: `opsnet_total` (it covers all user classes, like ASRS: 62% air carrier, 28% Part 91 reports).
For slices: air carrier / Part 121 → `opsnet_itinerant_air_carrier` or `t100_departures_us_carriers`; general
aviation / Part 91 → `opsnet_itinerant_general_aviation` (+ `opsnet_local_civil`).

**Notes (ASRS)**

- An OPSNET *operation* is one takeoff or one landing, so an itinerant flight between two towered airports counts
  twice. OPSNET counts only towered airports (no overflights, no untowered fields). OPSNET's "air carrier" class is
  aircraft with more than 60 seats; regional jets are mostly "air taxi". So 2 × T-100 domestic departures is
  1.04–1.17 × OPSNET itinerant air-carrier operations, not 1.
- T-100 covers commercial carriers only (scheduled and non-scheduled, passenger and cargo), not general aviation.
- The OPSNET banner says centre counts changed in October 2018; that affects "Center Aircraft Handled", not airport
  operations used here.
- April 2020 traffic was 0.32–0.35 of April 2019 (T-100, OPSNET air carrier) and 0.46 for all OPSNET operations.

## Rebuild

```bash
python scripts/download_exposure.py   # CDC files (skips files already in raw/)
# FAA OPSNET and BTS T-100: browser downloads, settings in data/asrs/exposure/MANIFEST.json ("note")
python scripts/make_manifest.py data/asrs/exposure --dataset ... --source ... --note ...
python scripts/build_exposure.py      # writes exposure/*
python -m pytest tests/test_exposure.py
```
