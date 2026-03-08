# ◈ Autonomous Constellation Manager (ACM)
### National Space Hackathon 2026 — Project AETHER

> A high-performance backend system and real-time 3D dashboard for autonomous satellite collision avoidance, maneuver planning, and constellation management in Low Earth Orbit.

---

![Dashboard Preview](https://img.shields.io/badge/status-operational-00ff88?style=for-the-badge&labelColor=040a0f)
![Python](https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python&labelColor=040a0f)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&labelColor=040a0f)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&labelColor=040a0f)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&labelColor=040a0f)

---

## Overview

The ACM is a ground-based autonomous system acting as the "brain" for a fleet of 50+ active satellites navigating a hazardous debris field in LEO. It continuously ingests orbital telemetry, predicts conjunctions up to 24 hours ahead, and autonomously plans and executes collision avoidance maneuvers — all without human intervention.

### Key Capabilities

- **High-frequency telemetry ingestion** — processes position/velocity state vectors for satellites and debris in real time
- **Predictive conjunction assessment** — 24-hour lookahead using a 3-stage spatial filtering pipeline (KDTree → Linear TCA → Propagated TCA)
- **Autonomous collision avoidance** — geometry-aware delta-v calculation in RTN frame with evasion + recovery burn pairs
- **Orbital propagation** — RK4 numerical integration with J2 perturbation (Earth's equatorial bulge)
- **Fuel budget management** — Tsiolkovsky rocket equation with dynamic wet mass tracking and EOL graveyard maneuvers
- **3D real-time dashboard** — PS2-style low-poly globe with live satellite/debris rendering at 60 FPS

---

## Architecture

```
ACM PROJECT/
├── app/
│   ├── main.py                  # FastAPI app, visualization snapshot
│   ├── config.py                # Global state, simulation clock
│   ├── api/
│   │   ├── telemetry.py         # POST /api/telemetry
│   │   ├── simulate.py          # POST /api/simulate/step
│   │   └── maneuver.py          # POST /api/maneuver/schedule
│   ├── orbit/
│   │   └── propagator.py        # RK4 + J2 orbital propagator
│   ├── collision/
│   │   ├── conjunction.py       # Conjunction detection with severity tiers
│   │   └── spatial_index.py     # KDTree spatial index
│   ├── prediction/
│   │   ├── predictor.py         # 3-stage 24hr conjunction predictor
│   │   └── tca.py               # Linear + propagated TCA algorithms
│   ├── maneuver/
│   │   ├── planner.py           # Evasion + recovery burn planner
│   │   └── fuel_model.py        # Tsiolkovsky rocket equation
│   └── models/
│       ├── satellite.py         # Satellite state model
│       └── debris.py            # Debris state model
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Main dashboard layout + polling
│   │   └── components/
│   │       ├── Globe3D.jsx          # Three.js PS2-style 3D globe
│   │       ├── BullseyePlot.jsx     # Conjunction polar chart
│   │       ├── FuelGauges.jsx       # Fleet fuel monitoring
│   │       └── ManeuverTimeline.jsx # Gantt burn scheduler
│   └── index.html
├── Dockerfile
├── requirements.txt
└── stress_test.py
```

---

## Physics Engine

### Orbital Propagation
The system uses **4th-order Runge-Kutta (RK4)** numerical integration with adaptive step sizing for efficiency:

```
d²r/dt² = -(μ/|r|³)r + a_J2
```

The **J2 perturbation** accounts for Earth's equatorial bulge:
```
a_J2x = (3/2) * J2 * μ * R_E² / |r|⁵ * x * (5(z/|r|)² - 1)
a_J2y = (3/2) * J2 * μ * R_E² / |r|⁵ * y * (5(z/|r|)² - 1)
a_J2z = (3/2) * J2 * μ * R_E² / |r|⁵ * z * (5(z/|r|)² - 3)
```

Constants: `μ = 398600.4418 km³/s²`, `R_E = 6378.137 km`, `J2 = 1.08263×10⁻³`

### Conjunction Detection — 3-Stage Pipeline
Avoids O(N²) complexity with 50 satellites × 10,000+ debris:

```
Stage 1: KDTree spatial index    → O(N log N), filters 99%+ of debris
Stage 2: Linear TCA pre-filter   → eliminates non-threatening trajectories
Stage 3: Propagated TCA (RK4)    → accurate 24hr two-pass scan for threats
```

Collision threshold: **100 metres (0.1 km)**

### Maneuver Planning
Burns are calculated in the **RTN (Radial-Transverse-Normal)** frame:
- **Transverse (prograde/retrograde)** burns for orbital phasing — most fuel-efficient
- Delta-v direction chosen based on debris approach geometry

### Fuel Model — Tsiolkovsky Rocket Equation
```
Δm = m_current × (1 - e^(-|Δv| / (Isp × g₀)))
```

Where `Isp = 300s`, `g₀ = 9.80665 m/s²`. Mass is dynamically tracked — each burn makes subsequent burns slightly more efficient.

Spacecraft constants:
| Parameter | Value |
|---|---|
| Dry mass | 500.0 kg |
| Initial fuel | 50.0 kg |
| Max Δv per burn | 15.0 m/s |
| Thruster cooldown | 600 s |
| EOL fuel threshold | 5% |

---

## API Reference

### `POST /api/telemetry`
Ingest orbital state vectors for satellites and debris.
```json
{
  "timestamp": "2026-03-12T08:00:00.000Z",
  "objects": [
    {
      "id": "SAT-001",
      "type": "SATELLITE",
      "r": { "x": 6778.0, "y": 0.0, "z": 0.0 },
      "v": { "x": 0.0, "y": 7.669, "z": 0.0 }
    }
  ]
}
```

### `POST /api/simulate/step`
Advance simulation by N seconds. Propagates all objects, detects conjunctions, executes maneuvers.
```json
{ "step_seconds": 60 }
```

### `POST /api/maneuver/schedule`
Schedule a validated burn sequence for a satellite.
```json
{
  "satelliteId": "SAT-001",
  "maneuver_sequence": [
    {
      "burn_id": "EVASION_BURN_1",
      "burnTime": "2026-03-12T14:15:30.000Z",
      "deltaV_vector": { "x": 0.002, "y": 0.010, "z": -0.001 }
    }
  ]
}
```

### `GET /api/visualization/snapshot`
Compressed fleet snapshot for the frontend dashboard.

### `GET /api/maneuvers/active`
All pending scheduled burns across the constellation.

---

## Frontend — Orbital Insight Dashboard

A PS2-style retro-futuristic mission control dashboard built with React + Three.js.

| Panel | Description |
|---|---|
| **3D Globe** | Low-poly Earth with live satellite diamonds and red debris cloud. Drag to rotate, scroll to zoom |
| **Constellation List** | Per-satellite status, position, fuel level, and queued burn count |
| **Conjunction Bullseye** | Polar chart showing debris threats around the selected satellite |
| **Fuel Gauges** | Individual fuel bars + fleet-wide bar chart |
| **Maneuver Timeline** | Gantt chart with evasion burns 🟡, cooldown stripes, and recovery burns 🔵 |

---

## Quick Start

### Option 1 — Docker (recommended)
```bash
docker build -t acm .
docker run -p 8000:8000 acm
```

### Option 2 — Local development

**Backend:**
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

---

## Stress Test

Tests the full pipeline with 50 satellites, 500 debris, and 10 collision-course objects:

```bash
pip install requests
python stress_test.py
```

Expected output:
```
✅  Backend alive
✅  ACK received — 550 objects ingested
✅  All 10 steps clean — 0 collisions!
✅  Total maneuvers executed: 10
✅  Valid maneuver accepted
✅  Over-limit burn correctly rejected
✅  Snapshot performance: EXCELLENT (<100ms)
```

---

## Evaluation Criteria Coverage

| Criteria | Weight | Implementation |
|---|---|---|
| Safety Score | 25% | 3-stage conjunction pipeline, autonomous evasion |
| Fuel Efficiency | 20% | RTN-frame burns, Tsiolkovsky mass tracking |
| Constellation Uptime | 15% | Station-keeping box, recovery burns |
| Algorithmic Speed | 15% | KDTree O(N log N), adaptive RK4 step sizing |
| UI/UX & Visualization | 15% | PS2 3D globe, real-time panels, 60 FPS |
| Code Quality | 10% | Modular architecture, typed models, logging |

---

## Team

Built for the **National Space Hackathon 2026**.
