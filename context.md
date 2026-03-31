# ACM Project — CONTEXT.md (Update-5)
> Last updated: Session 5 (shreyansh). Read this before touching any file.

---

## What This Project Is

An **Autonomous Constellation Manager (ACM)** built for the National Space Hackathon 2026.
Full-stack system: Python 3.12 + FastAPI backend, React 18 + Three.js frontend, Docker deployment.

Stack: FastAPI · NumPy · scikit-learn · React · Three.js · Docker (ubuntu:22.04)

---

## Current Project Status

### ✅ WORKING
| Feature | File | Notes |
|---|---|---|
| RK4 + J2 propagation | app/orbit/propagator.py | Core physics, confirmed working |
| Telemetry ingestion | app/api/telemetry.py | ACK in <30ms, 550 objects |
| 3-stage conjunction pipeline | app/prediction/predictor.py | KDTree → linear TCA → propagated TCA |
| Simulate step | app/api/simulate.py | All 10 steps clean, <200ms each |
| Nominal slot propagation | app/models/satellite.py | propagate_nominal() uses same RK4+J2 |
| Structured logging | app/logger.py | JSON events, ring buffer, /api/events |
| Snapshot performance | app/main.py | 10-20ms avg, EXCELLENT rating |
| Docker multi-stage build | dockerfile | Node + Python, serves frontend |
| Ground stations (6 correct) | ground_stations.csv | Bengaluru, Svalbard, Goldstone, Punta Arenas, IIT Delhi, McMurdo |
| Station-keeping (Euclidean) | app/api/station_keeping.py | 10km sphere check, correct |
| Maneuver validation | app/api/maneuver.py | Cooldown, fuel, dV limit enforced |
| Over-limit burn rejection | app/api/maneuver.py | >15 m/s correctly rejected |
| Unknown satellite rejection | app/api/maneuver.py | REJECTED with reason |
| Active maneuvers endpoint | app/api/maneuver.py | GET /api/maneuvers/active working |
| Fuel depletion tracking | app/maneuver/fuel_model.py | Tsiolkovsky with current wet mass |
| RTN frame evasion | app/maneuver/planner.py | Geometry-aware direction |
| TCA-aware recovery | app/maneuver/planner.py | Waits for threat to clear |
| EOL graveyard burn | app/maneuver/planner.py | Prograde to raise apogee |

### ❌ CURRENTLY BROKEN
| Issue | File | Error |
|---|---|---|
| los.py has two conflicting versions | app/api/los.py | Repo version different from fixed version — `alt_m` vs `alt_km`, `epoch_unix` vs `sim_time_s`, `los_details()` wrong signature |
| LOS check endpoint 500 error | GET /api/los/check | `los_details() got unexpected kwarg 'sim_time_s'` — repo los.py uses different function signature than fixed version |
| Valid maneuver always rejected | app/api/maneuver.py | Because LOS always returns error, maneuver schedule test fails |
| Stress test: test 4 failing | app/stress_test.py | Valid maneuver rejected due to LOS bug above |

### ⚠️ WATCH OUT FOR
| Item | Notes |
|---|---|
| `app/api/los.py` has TWO versions | Repo version (old, different signature) vs fixed version (new). Must reconcile. |
| `lru_cache` on `_load_stations` | CSV is cached after first load — if CSV changes, must restart server |
| `simulate.py` router prefix | Registered as `/api/simulate` in main.py but endpoints use full paths `/api/simulate/step` — check for double-prefix issues |
| `propagate_orbit` returns tuple | `sat.r, sat.v = propagate_orbit(...)` — must unpack as tuple, not assign single value |
| `.tolist()` calls | All fixed in predictor.py, conjunction.py — if new files added, use `list(x)` not `x.tolist()` |

---

## Stress Test Results (Latest Run)

```
✅  1. HEALTH CHECK — Backend alive
✅  2. TELEMETRY — 550 objects in ~15ms, 10 CDM warnings
✅  3. SIMULATE x10 — 0 collisions, <200ms per step
❌  4. MANEUVER SCHEDULE — Valid maneuver rejected (LOS bug)
✅  5. SNAPSHOT — 10-20ms avg, EXCELLENT
✅  6. ACTIVE MANEUVERS — endpoint working
✅  7. FUEL DEPLETION — tracking correctly
```

**Score: 6/7 tests passing. Only test 4 failing.**

---

## File Structure

```
acm-project/
├── ground_stations.csv          ← 6 correct stations from spec
├── app/
│   ├── main.py                  ← FastAPI app, all routers registered
│   ├── config.py                ← Global state: satellites, debris, sim clock
│   ├── logger.py                ← Structured JSON logging, ring buffer
│   ├── api/
│   │   ├── telemetry.py         ← POST /api/telemetry
│   │   ├── simulate.py          ← POST /api/simulate/step, GET /api/events
│   │   ├── maneuver.py          ← POST /api/maneuver/schedule
│   │   ├── los.py               ← LOS geometry ← CURRENTLY BROKEN (version conflict)
│   │   ├── ground_stations.py   ← GET /api/ground-stations/list
│   │   └── station_keeping.py   ← POST /api/station-keeping/check
│   ├── orbit/
│   │   └── propagator.py        ← RK4 + J2 — DO NOT TOUCH
│   ├── collision/
│   │   ├── conjunction.py       ← KDTree query — .tolist() fixed
│   │   └── spatial_index.py     ← KDTree wrapper
│   ├── prediction/
│   │   ├── predictor.py         ← 3-stage pipeline — .tolist() fixed
│   │   └── tca.py               ← linear_tca + propagated_tca
│   ├── maneuver/
│   │   ├── planner.py           ← RTN evasion, TCA-aware recovery, logging
│   │   └── fuel_model.py        ← Tsiolkovsky rocket equation
│   └── models/
│       ├── satellite.py         ← propagate_nominal(), is_on_cooldown()
│       └── debris.py            ← r, v state vectors
├── frontend/
│   └── src/components/
│       ├── Globe3D.jsx           ← Three.js PS1 Earth
│       ├── BullseyePlot.jsx      ← Conjunction polar chart
│       ├── FuelGauges.jsx        ← Per-satellite fuel bars
│       └── ManeuverTimeline.jsx  ← Gantt burn scheduler
├── dockerfile                   ← Multi-stage Node+Python build
└── requirements.txt             ← fastapi uvicorn numpy scikit-learn aiofiles python-dateutil
```

---

## API Endpoints (All Registered)

| Method | Path | Status |
|---|---|---|
| GET | / | ✅ Health check |
| POST | /api/telemetry | ✅ Working |
| POST | /api/simulate/step | ✅ Working |
| GET | /api/simulate/events | ✅ Working |
| GET | /api/visualization/snapshot | ✅ Working |
| POST | /api/maneuver/schedule | ⚠️ Works but LOS always errors |
| GET | /api/maneuvers/active | ✅ Working |
| GET | /api/los/check | ❌ 500 error (version conflict) |
| POST | /api/ground-stations/los-check | ✅ Working |
| POST | /api/station-keeping/check | ✅ Working |
| GET | /api/station-keeping/burn-queue | ✅ Working |

---

## Known Issues To Fix (Priority Order)

### 1. 🔴 CRITICAL — los.py version conflict
The repo has an OLD version of los.py with different function signatures:
- Uses `epoch_unix` instead of `sim_time_s`
- Uses `alt_m` instead of `alt_km`
- `los_details()` has different signature

**Fix:** Replace entire `app/api/los.py` with the corrected version that uses:
- `sim_time_s` parameter throughout
- `alt_km` column from CSV
- Consistent function signatures

### 2. 🟡 MEDIUM — Stress test always finds SAT-001 not visible
At any given sim time, 80% of LEO satellites are in blackout.
The stress test needs to scan all 50 satellites and pick the one
with the highest elevation angle above any station.

**Fix:** Already in stress_test.py — `_find_visible_satellite()` with `min_elev=-90`
but depends on los.py fix above working first.

### 3. 🟡 MEDIUM — Maneuver test 4 (valid maneuver)
Once LOS is fixed, this will automatically pass for visible satellites.

---

## Physics Constants

| Constant | Value |
|---|---|
| μ | 398600.4418 km³/s² |
| R_E | 6378.137 km |
| J2 | 1.08263×10⁻³ |
| Isp | 300 s |
| g₀ | 9.80665 m/s² |
| Dry mass | 500.0 kg |
| Initial fuel | 50.0 kg |
| Max ΔV per burn | 15.0 m/s |
| Cooldown | 600 s |
| EOL threshold | 5% (2.5 kg) |
| Collision radius | 0.1 km |
| Station-keeping | 10 km sphere |
| Signal latency | 10 s |

---

## Running The Project

```bash
# Backend (from project root — NOT from inside app/)
python -m uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev

# Stress test (backend must be running)
python app/stress_test.py

# Docker (full stack)
docker build -t acm .
docker run -p 8000:8000 acm
```

---

## Teammate Warnings

1. **DO NOT** change `orbit/propagator.py` — physics core, everything depends on it
2. **DO NOT** change `prediction/tca.py` return signature — planner.py imports it
3. **DO NOT** create a second `app = FastAPI()` instance in main.py
4. **DO NOT** run uvicorn from inside `app/` directory — always from project root
5. **DO NOT** use `.tolist()` on satellite/debris r,v — use `list(x)` instead
6. **ALL** new files must be added to router registration in `main.py`