<div align="center">

# ◈ SOLIS — Autonomous Constellation Manager
### National Space Hackathon 2026 · Project SOLIS-1

*Autonomous collision avoidance, maneuver planning, and real-time 3D orbital situational awareness for Low Earth Orbit constellations.*

---

![Status](https://img.shields.io/badge/status-operational-00ff88?style=for-the-badge&labelColor=040a0f)
![Python](https://img.shields.io/badge/python-3.12-3776ab?style=for-the-badge&logo=python&labelColor=040a0f)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&labelColor=040a0f)
![React](https://img.shields.io/badge/React-18-61dafb?style=for-the-badge&logo=react&labelColor=040a0f)
![Three.js](https://img.shields.io/badge/Three.js-r162-white?style=for-the-badge&logo=threedotjs&labelColor=040a0f)
![Docker](https://img.shields.io/badge/Docker-ubuntu_22.04-2496ed?style=for-the-badge&logo=docker&labelColor=040a0f)

</div>

---

## What We Built

SOLIS is a ground-based autonomous system that acts as the central "brain" for a fleet of 50+ active satellites navigating a hazardous debris field in LEO. The system runs a continuous loop: ingest telemetry → predict conjunctions → plan maneuvers → execute burns → verify recovery — entirely without human intervention.

The frontend renders the full constellation in real time on a PS1/Mouthwashing-style low-poly 3D globe, giving flight dynamics officers instant situational awareness across the entire fleet.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Simulation Grader / External Client                            │
└──────────────┬──────────────────────────────────────────────────┘
               │ REST API (port 8000)
┌──────────────▼──────────────────────────────────────────────────┐
│  FastAPI Backend                                                │
│                                                                 │
│  POST /api/telemetry        → Ingest ECI state vectors         │
│  POST /api/simulate/step    → Advance physics simulation       │
│  POST /api/maneuver/schedule→ Validate & queue burns           │
│  POST /api/ground-stations/ → LOS checks & blackout windows   │
│  POST /api/station-keeping/ → Slot drift monitoring           │
│  GET  /api/visualization/snapshot → Compressed fleet state    │
│  GET  /api/maneuvers/active → Pending burn queue              │
│  GET  /api/events           → Structured event log            │
└───────┬─────────┬───────────┬────────────┬──────────────────────┘
        │         │           │            │
   Physics   Conjunction  Maneuver    Ground Station
   Engine    Pipeline     Planner     LOS Engine
   (RK4+J2)  (KDTree→    (RTN-frame  (GAST + WGS-84
             TCA→Prop.)   geometry)   elevation)
```

---

## Core Systems

### 1 · Physics Engine (`orbit/propagator.py`)

Orbital propagation using **4th-order Runge-Kutta (RK4)** with adaptive step sizing and **J2 perturbation** for Earth's equatorial bulge:

```
d²r/dt² = −(μ/|r|³)r + a_J2

a_J2 = (3/2) · J2 · μ · R_E² / |r|⁵ · [x(5z²/r²−1), y(5z²/r²−1), z(5z²/r²−3)]

μ = 398600.4418 km³/s²    R_E = 6378.137 km    J2 = 1.08263×10⁻³
```

Adaptive step sizing (`max_step = 30s`) means a 1-hour tick uses 120 RK4 iterations instead of 3,600 — 30× faster with no accuracy loss.

---

### 2 · Conjunction Assessment (`prediction/`)

Three-stage pipeline eliminates O(N²) complexity for 50 satellites × 10,000+ debris:

| Stage | Method | Purpose |
|---|---|---|
| 1 | **KDTree** (sklearn) | Query 50 km radius — eliminates >99% of debris instantly |
| 2 | **Linear TCA** | Constant-velocity closest approach — drops clearly safe trajectories |
| 3 | **Propagated TCA** | Full RK4+J2 two-pass scan over 24hr horizon with velocity-adaptive step sizing |

Stage 0 (immediate collision check) catches debris already inside the 100 m threshold before propagation runs.

---

### 3 · Autonomous Collision Avoidance (`maneuver/planner.py`)

Evasion burns are computed geometrically in the **RTN (Radial-Transverse-Normal)** frame:

- Compute relative position at TCA in RTN coordinates
- Choose burn axis based on dominant approach direction:
  - Head-on/tail-on (dominant T) → **burn radial** — shifts altitude, changes crossing time
  - Above/below (dominant R) → **burn transverse** — most fuel-efficient phase shift
  - Out-of-plane (dominant N) → **burn transverse** — avoids expensive plane-change burns
- Burn sign chosen to push satellite **away** from debris at TCA

Recovery burns use slot-targeted correction (`nominal_r − r`) capped at 5 m/s, and only fire once the threat distance exceeds 0.5 km — no hardcoded T+660s.

---

### 4 · Fuel Model (`maneuver/fuel_model.py`)

Tsiolkovsky rocket equation with **dynamic wet mass** (mass decreases after every burn, making subsequent burns slightly more efficient):

```
Δm = m_current × (1 − e^(−|Δv| / (Isp × g₀)))

Isp = 300 s    g₀ = 9.80665 m/s²
```

| Spacecraft Parameter | Value |
|---|---|
| Dry mass | 500.0 kg |
| Initial fuel | 50.0 kg |
| Max Δv per burn | 15.0 m/s |
| Thruster cooldown | 600 s |
| EOL fuel threshold | 5% → graveyard burn |
| Collision radius | 0.1 km (100 m) |
| Station-keeping box | 10 km sphere |

---

### 5 · Ground Station LOS (`api/los.py`)

Real elevation angle geometry using WGS-84 ellipsoid and Greenwich Apparent Sidereal Time (GAST) computed from simulation epoch (not wall clock):

```
GAST(t) = 280.46061837° + 360.98564736629° × (t_unix − t_J2000) / 86400
```

Six stations from the problem spec are loaded from `ground_stations.csv`. Any maneuver is rejected if no station has elevation ≥ its minimum mask angle.

---

### 6 · Station-Keeping (`api/station_keeping.py`)

Each satellite has a nominal orbital slot propagated with the same RK4+J2 integrator as its real position — preventing phantom drift penalties. Violations (distance > 10 km) trigger automatic slot-targeted recovery burns via the Clohessy-Wiltshire equations.

---

### 7 · Event Logging (`logger.py`)

Structured JSON event log with in-memory ring buffer (last 500 events) served at `GET /api/events`:

- `CDM_DETECTED` — conjunction found, severity, predicted miss distance
- `MANEUVER_PLANNED` — burn queued, Δv, fuel before/after
- `MANEUVER_EXECUTED` — burn applied, success/failure reason
- `RECOVERY_SCHEDULED` — recovery burn queued
- `RECOVERY_EXECUTED` — satellite back in slot, distance logged
- `EOL_TRIGGERED` — fuel critical, graveyard burn scheduled
- `GRAVEYARD_EXECUTED` — satellite moved to safe disposal orbit

---

## Frontend — Orbital Insight Dashboard

PS1/Mouthwashing-style retro-futuristic mission control built with **React 18 + Three.js**.

```
┌────────────────────────────────────────────────────────────┐
│  ◈ ORBITAL INSIGHT — ACM v1.0          [BACKEND LIVE] ▶   │
├──────────────┬─────────────────────────┬───────────────────┤
│ CONSTELLATION│                         │ CONJUNCTION PLOT  │
│ satellite    │   PS1 3D GLOBE          │ polar chart       │
│ list + fuel  │   drag / scroll / zoom  │ debris by dist    │
│ + event log  │   ground stations       │ + approach angle  │
│              │   satellite models      │                   │
├──────────────┴──────────────────────┬──┴───────────────────┤
│ FUEL & RESOURCES                    │ MANEUVER TIMELINE    │
│ per-sat bars + fleet chart          │ Gantt burn schedule  │
└─────────────────────────────────────┴──────────────────────┘
```

**Globe features:**
- `IcosahedronGeometry(1, 6)` + `flatShading: true` + NASA Blue Marble texture with `NearestFilter` → photo-accurate polygon patches (the Mouthwashing look)
- Satellites, debris, and ground stations are children of the Earth group — they all rotate together
- Ground station beacons: cyan disc + antenna spike + pulsing rings, one per station
- Debris rendered as `InstancedMesh` of red tetrahedra — handles 10,000+ objects at 60 FPS
- `pixelRatio: 0.6` — intentionally chunky PS1 pixel aesthetic
- CRT scanline CSS overlay + dark vignette

---

## API Reference

### `POST /api/telemetry`
```json
{
  "timestamp": "2026-03-12T08:00:00.000Z",
  "objects": [
    {
      "id": "SAT-001", "type": "SATELLITE",
      "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
      "v": {"x": 0.0, "y": 7.669, "z": 0.0}
    }
  ]
}
```

### `POST /api/simulate/step`
```json
{ "step_seconds": 60 }
```

**Response includes `fleet_metrics`:**
```json
{
  "status": "STEP_COMPLETE",
  "collisions_detected": 3,
  "maneuvers_executed": 3,
  "fleet_metrics": {
    "uptime_pct": 94.0,
    "total_fuel_used_kg": 1.834,
    "optimization_ratio": 51.2
  }
}
```

### `POST /api/maneuver/schedule`
```json
{
  "satelliteId": "SAT-001",
  "maneuver_sequence": [
    {
      "burn_id": "EVASION_BURN_1",
      "burnTime": "2026-03-12T14:15:30.000Z",
      "deltaV_vector": {"x": 0.002, "y": 0.010, "z": -0.001}
    }
  ]
}
```

Validates: satellite exists · Δv ≤ 15 m/s · 600 s cooldown between burns · sufficient fuel · ground station LOS

### `GET /api/visualization/snapshot`
Returns `satellites` array + flattened `debris_cloud` tuples `[ID, lat, lon, alt]` for efficient network transfer.

### `GET /api/los/check?x=6778&y=0&z=0`
Per-station elevation angles + GAST at simulation epoch.

---

## Evaluation Criteria

| Criteria | Weight | How We Address It |
|---|---|---|
| **Safety Score** | 25% | 3-stage KDTree→TCA pipeline; Stage 0 immediate check; geometry-aware RTN evasion |
| **Fuel Efficiency** | 20% | RTN axis selection (cheapest burn per geometry); dynamic Tsiolkovsky mass tracking |
| **Constellation Uptime** | 15% | Nominal slot propagated with RK4+J2; slot-targeted recovery; station-keeping monitoring |
| **Algorithmic Speed** | 15% | KDTree O(N log N); adaptive step sizing; velocity-adaptive TCA coarse step |
| **UI/UX & Visualization** | 15% | PS1 globe; 60 FPS instanced debris; pulsing ground stations; Gantt timeline |
| **Code Quality** | 10% | Structured JSON event logging; modular architecture; typed Pydantic models |

---

## Quick Start

### Docker (required for grader)
```bash
docker build -t acm .
docker run -p 8000:8000 acm
# Full stack available at http://localhost:8000
```

### Local Development
```bash
# Terminal 1 — backend (run from project root)
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev -- --host 0.0.0.0
# Open http://localhost:3000
```

### Stress Test
```bash
python app/stress_test.py
```

Expected results:
```
✅  Health check
✅  530 objects ingested
✅  Valid maneuver accepted
✅  Over-limit burn rejected
✅  Cooldown violation rejected
✅  0 collisions across 15 survival steps
✅  Evasion maneuvers fired
✅  Event log populated
```

---

## Project Structure

```
acm-project/
├── app/
│   ├── main.py                  # FastAPI app, all routers, snapshot endpoint
│   ├── config.py                # Global state, sim clock, epoch constants
│   ├── logger.py                # Structured JSON event log
│   ├── api/
│   │   ├── telemetry.py         # POST /api/telemetry
│   │   ├── simulate.py          # POST /api/simulate/step + fleet metrics
│   │   ├── maneuver.py          # POST /api/maneuver/schedule, GET /active
│   │   ├── los.py               # Real LOS geometry (GAST + WGS-84)
│   │   ├── ground_stations.py   # Pass windows + blackout calculator
│   │   └── station_keeping.py   # 10 km box monitor + CW recovery burns
│   ├── orbit/
│   │   └── propagator.py        # RK4 + J2, adaptive step sizing
│   ├── collision/
│   │   ├── conjunction.py       # KDTree query, CRITICAL/RED/YELLOW tiers
│   │   └── spatial_index.py     # sklearn KDTree wrapper
│   ├── prediction/
│   │   ├── predictor.py         # 3-stage + Stage 0 immediate check
│   │   └── tca.py               # linear_tca + propagated_tca (velocity-adaptive)
│   ├── maneuver/
│   │   ├── planner.py           # RTN geometry evasion, TCA-aware recovery
│   │   └── fuel_model.py        # Tsiolkovsky, max_delta_v
│   ├── models/
│   │   ├── satellite.py         # Dynamic mass, cooldown, nominal slot, EOL
│   │   └── debris.py            # ECI state vector
│   └── stress_test.py           # Full automated test suite
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Layout, 2s polling, step button
│   │   ├── index.css            # CRT design system
│   │   └── components/
│   │       ├── Globe3D.jsx      # Three.js PS1 globe + ground stations
│   │       ├── BullseyePlot.jsx # Polar conjunction chart
│   │       ├── FuelGauges.jsx   # Fleet fuel monitoring
│   │       └── ManeuverTimeline.jsx  # Gantt burn scheduler
│   ├── index.html
│   ├── package.json
│   └── vite.config.js           # Proxy /api → :8000
├── Dockerfile                   # Multi-stage: Node build → ubuntu:22.04
├── requirements.txt
├── ground_stations.csv
└── README.md
```

---

## Team Solis

Built for the **National Space Hackathon 2026 — Project Solis-1**.
