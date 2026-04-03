# ◈ SOLIS
### National Space Hackathon 2026 — Project SOLIS-1

> A high-performance backend system and real-time 3D dashboard for autonomous satellite collision avoidance, maneuver planning, and constellation management in Low Earth Orbit.

---

![Status](https://img.shields.io/badge/status-operational-00ff88?style=for-the-badge&labelColor=040a0f)
![Python](https://img.shields.io/badge/python-3.12-blue?style=for-the-badge&logo=python&labelColor=040a0f)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&labelColor=040a0f)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&labelColor=040a0f)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&labelColor=040a0f)

---

## Overview

SOLIS is a ground-based autonomous system acting as the "brain" for a fleet of 50+ active satellites navigating a hazardous debris field in LEO. It continuously ingests orbital telemetry, predicts conjunctions up to 24 hours ahead, and autonomously plans and executes collision avoidance maneuvers — all without human intervention.

---

## System Architecture — High Level

```mermaid
flowchart TD
    EXT([Simulation Grader / External Client])

    subgraph BACKEND["Backend — FastAPI on port 8000"]
        TEL[POST /api/telemetry]
        SIM[POST /api/simulate/step]
        MAN[POST /api/maneuver/schedule]
        SNAP[GET /api/visualization/snapshot]
        ACTIVE[GET /api/maneuvers/active]
        LOS[GET /api/los/check]
        GS[POST /api/ground-stations/los-check]
        SK[POST /api/station-keeping/check]
        EVT[GET /api/events]
    end

    subgraph PHYSICS["Physics Engine"]
        PROP[orbit/propagator.py\nRK4 + J2 integration]
        TCA[prediction/tca.py\nLinear + Propagated TCA]
        PRED[prediction/predictor.py\n3-stage conjunction pipeline]
        CONJ[collision/conjunction.py\nSeverity classification]
        TREE[collision/spatial_index.py\nKDTree]
    end

    subgraph MANEUVER["Maneuver System"]
        PLAN[maneuver/planner.py\nEvasion + Recovery burns]
        FUEL[maneuver/fuel_model.py\nTsiolkovsky rocket equation]
    end

    subgraph STATE["Global State"]
        CFG[config.py\nsatellites + debris dicts\nsim clock + epoch]
        SATM[models/satellite.py]
        DEBM[models/debris.py]
        LOG[logger.py\nStructured JSON event log]
    end

    subgraph FRONTEND["Frontend — React + Three.js on port 3000"]
        APP[App.jsx\nLayout + polling every 2s]
        GLOBE[Globe3D.jsx\nPS1 Mouthwashing 3D Earth]
        BULL[BullseyePlot.jsx\nConjunction polar chart]
        FUELG[FuelGauges.jsx\nFleet fuel monitoring]
        GANTT[ManeuverTimeline.jsx\nGantt burn scheduler]
    end

    EXT -->|POST| TEL
    EXT -->|POST| SIM
    EXT -->|POST| MAN
    EXT -->|GET| SNAP

    TEL --> CFG
    SIM --> PROP
    SIM --> PRED
    SIM --> PLAN
    MAN --> FUEL

    PROP --> CFG
    PRED --> TREE
    PRED --> TCA
    PRED --> CONJ
    CONJ --> CFG
    PLAN --> FUEL
    PLAN --> CFG
    PLAN --> LOG

    CFG --> SATM
    CFG --> DEBM

    SNAP --> APP
    ACTIVE --> APP
    APP --> GLOBE
    APP --> BULL
    APP --> FUELG
    APP --> GANTT
```

---

## Request Flow — Telemetry Ingestion

```mermaid
flowchart LR
    A([POST /api/telemetry]) --> B{Parse JSON}
    B --> C{obj.type.upper}
    C -->|SATELLITE| D[Create Satellite\nfuel=50kg dry_mass=500kg]
    C -->|DEBRIS| E[Create Debris]
    D --> F[satellites dict]
    E --> G[debris dict]
    F --> H[detect_conjunctions\nfor CDM count]
    G --> H
    H --> I([ACK + active_cdm_warnings])
```

---

## Request Flow — Simulate Step

```mermaid
flowchart TD
    A([POST /api/simulate/step]) --> B[Propagate all Satellites\nRK4 + J2]
    B --> C[Propagate all Debris\nRK4 + J2]
    C --> C2[Propagate Nominal Slots\nsame RK4 + J2]
    C2 --> D[advance_sim_time]
    D --> E[execute_scheduled_burns]
    E --> F[predict_conjunctions\n24hr lookahead]

    subgraph PIPELINE["3-Stage Conjunction Pipeline"]
        F --> F0[Stage 0: Immediate\ndist < 0.1km right now]
        F0 --> G[Stage 1: KDTree\nfilter within 50km]
        G --> H[Stage 2: Linear TCA\neliminate safe trajectories]
        H --> I[Stage 3: Propagated TCA\nvelocity-adaptive RK4 24hr scan]
    end

    I --> J{severity?}
    J -->|CRITICAL under 0.1km| K[plan_maneuver\nRTN geometry-aware]
    J -->|YELLOW / RED| L[Log CDM warning]
    K --> M[Apply evasion burn\nsat.v += dv ECI]
    M --> N[Tsiolkovsky fuel depletion]
    N --> O[Schedule TCA-aware recovery]
    O --> P([STEP_COMPLETE\n+ fleet_metrics])
```

---

## Conjunction Detection Pipeline

```mermaid
flowchart LR
    A[50 Satellites\n10000+ Debris] --> B

    subgraph S0["Stage 0 — Immediate Check"]
        B[dist under 100m right now?]
        B -->|Yes| CRIT[CRITICAL — skip propagation]
    end

    B -->|No| S1

    subgraph S1["Stage 1 — KDTree O(N log N)"]
        S1A[Build KDTree over debris]
        S1A --> S1B[Query 50km radius per sat]
        S1B --> S1C[99%+ debris eliminated]
    end

    S1C --> S2

    subgraph S2["Stage 2 — Linear TCA"]
        S2A[Constant-velocity TCA]
        S2A --> S2B{miss > 2km?}
        S2B -->|Yes| SKIP[Skip — safe]
        S2B -->|No| S3
    end

    subgraph S3["Stage 3 — Propagated TCA"]
        S3A[Velocity-adaptive coarse scan\nover 24hr horizon]
        S3A --> S3B[Fine 5s scan ±5min around minimum]
        S3B --> S3C{dist under 0.1km?}
        S3C -->|Yes| L[CRITICAL warning]
        S3C -->|No| M[Safe — discard]
    end
```

---

## Maneuver Planning Flow

```mermaid
flowchart TD
    A([plan_maneuver called]) --> B{Satellite exists?}
    B -->|No| Z1([Return None])
    B -->|Yes| C{Cooldown active?\ncooldown_remaining_at}
    C -->|Yes| Z2([COOLDOWN status])
    C -->|No| D{Fuel under 5%?}
    D -->|Yes| E[Graveyard burn\nprograde to raise apogee]
    D -->|No| F[Compute evasion dv\nRTN frame geometry\nhead-on→radial\nabove/below→transverse]
    F --> G[Burn direction =\naway from debris at TCA]
    G --> H[Tsiolkovsky fuel cost\ndynamic wet mass]
    H --> I{Enough fuel?}
    I -->|No| Z3([INSUFFICIENT_FUEL])
    I -->|Yes| J[Apply evasion burn\nsat.v += dv ECI]
    J --> K[Deplete fuel mass]
    K --> L[Start 600s cooldown]
    L --> M[Schedule TCA-aware recovery\nfires when threat clears]
    M --> N([Return maneuver dict\n+ log events])
```

---

## Fuel Model

```mermaid
flowchart LR
    A[delta_v km/s] --> B[Convert to m/s]
    B --> C[dm = m_current × 1 − exp(−dv / Isp×g0)]
    C --> D[sat.fuel -= dm\nsat.mass decreases]
    D --> E{fuel fraction\nunder 5%?}
    E -->|Yes| F[EOL_TRIGGERED\nschedule graveyard burn]
    E -->|No| G[Continue ops]

    subgraph K["Constants"]
        H[Isp = 300s · g0 = 9.80665 m/s²\nMax dv = 15 m/s · Cooldown = 600s]
    end
```

---

## Ground Station LOS

```mermaid
flowchart LR
    A([Maneuver request]) --> B[get_unix_time\nSIM_EPOCH + sim_elapsed]
    B --> C[Compute GAST\nGreenwich Sidereal Time]
    C --> D[Rotate each station\nECEF → ECI via GAST]
    D --> E[Elevation angle\narcsin dot range up / range]
    E --> F{Any station\nabove min mask?}
    F -->|Yes| G([LOS = true\nmaneuver accepted])
    F -->|No| H([LOS = false\nREJECTED])
```

---

## Frontend Component Tree

```mermaid
flowchart TD
    APP[App.jsx\npolls snapshot + maneuvers every 2s\nmanages all state]

    APP -->|satellites debrisCloud selectedSat| GLOBE[Globe3D.jsx\nThree.js PS1 Earth\nReal texture + flat shading\nInstanced debris cloud\nSatellite 3D models + trails\n6 ground station beacons\nEarth group — all rotates together]

    APP -->|warnings selectedSat| BULL[BullseyePlot.jsx\nCanvas 2D polar chart\nDebris by distance + angle\nColour coded by severity]

    APP -->|satellites| FUEL[FuelGauges.jsx\nPer-satellite fuel bars\nRecharts fleet chart\nLow fuel warnings]

    APP -->|satellites maneuvers simTime| GANTT[ManeuverTimeline.jsx\nGantt rows per satellite\nOrange = evasion burn\nStriped = 600s cooldown\nBlue = recovery burn]
```

---

## File Reference

```mermaid
flowchart TD
    subgraph ROOT["Project Root"]
        DF[Dockerfile\nMulti-stage: Node build + ubuntu:22.04]
        REQ[requirements.txt]
        GS[ground_stations.csv\n6 stations from spec]
        RM[README.md]
    end

    subgraph APP["app/"]
        MAIN[main.py\nFastAPI app + all routers\nsnapshot + GST-corrected ECI→lat/lon]
        CFG[config.py\nsatellites + debris dicts\nsim clock + SIM_EPOCH_UNIX]
        LOG[logger.py\nStructured JSON events\nring buffer 500 events]

        subgraph API["api/"]
            TAPI[telemetry.py\nPOST /api/telemetry]
            SAPI[simulate.py\nPOST /api/simulate/step\nfleet_metrics in response]
            MAPI[maneuver.py\nPOST /api/maneuver/schedule\nGET /api/maneuvers/active]
            LOSAPI[los.py\nGET /api/los/check\nreal GAST + WGS-84 elevation]
            GSAPI[ground_stations.py\nPOST /api/ground-stations/los-check\npass + blackout windows]
            SKAPI[station_keeping.py\nPOST /api/station-keeping/check\nCW recovery burn trigger]
        end

        subgraph ORBIT["orbit/"]
            OPROP[propagator.py\nRK4 4th order + J2\nadaptive step sizing]
        end

        subgraph COL["collision/"]
            CCONJ[conjunction.py\nKDTree query\nCRITICAL RED YELLOW tiers]
            CTREE[spatial_index.py\nsklearn KDTree]
        end

        subgraph PRED["prediction/"]
            PPRED[predictor.py\nStage 0-3 pipeline\n24hr horizon]
            PTCA[tca.py\nlinear_tca + propagated_tca\nvelocity-adaptive coarse step]
        end

        subgraph MAN["maneuver/"]
            MPLAN[planner.py\nRTN geometry evasion\nTCA-aware recovery\ngraveyard EOL]
            MFUEL[fuel_model.py\nTsiolkovsky\ndynamic wet mass]
        end

        subgraph MOD["models/"]
            MSAT[satellite.py\ndynamic mass + cooldown\nnominal slot + EOL flag]
            MDEB[debris.py\nECI state vector]
        end
    end

    subgraph FE["frontend/"]
        PKG[package.json\nReact 18 + Three.js + Recharts]
        VCFG[vite.config.js\nproxy /api → port 8000]

        subgraph SRC["src/"]
            AAPP[App.jsx\nlayout + polling + step button]
            ICSS[index.css\nVT323 font · CRT design tokens]

            subgraph COMP["components/"]
                CG[Globe3D.jsx\nMouthwashing PS1 Earth\nground stations + satellites\nrotate with Earth group]
                CB[BullseyePlot.jsx\nCanvas 2D polar chart]
                CF[FuelGauges.jsx\nfuel bars + Recharts]
                CM[ManeuverTimeline.jsx\nGantt burn scheduler]
            end
        end
    end
```

---

## Physics Reference

### RK4 + J2 Propagation

```
d²r/dt² = -(μ/|r|³)r + a_J2

a_J2x = (3/2) × J2 × μ × R_E² / |r|⁵ × x × (5(z/|r|)² - 1)
a_J2y = (3/2) × J2 × μ × R_E² / |r|⁵ × y × (5(z/|r|)² - 1)
a_J2z = (3/2) × J2 × μ × R_E² / |r|⁵ × z × (5(z/|r|)² - 3)

μ = 398600.4418 km³/s²    R_E = 6378.137 km    J2 = 1.08263×10⁻³
```

### Tsiolkovsky Rocket Equation

```
Δm = m_current × (1 - e^(-|Δv| / (Isp × g₀)))

Isp = 300s    g₀ = 9.80665 m/s²
```

### Spacecraft Constants

| Parameter | Value |
|---|---|
| Dry mass | 500.0 kg |
| Initial fuel | 50.0 kg |
| Max Δv per burn | 15.0 m/s |
| Thruster cooldown | 600 s |
| EOL fuel threshold | 5% (2.5 kg) |
| Collision radius | 100 m (0.1 km) |
| Station-keeping box | 10 km radius |
| Signal latency | 10 s |

---

## API Reference

### `POST /api/telemetry`
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
```json
{ "step_seconds": 60 }
```

Response includes `fleet_metrics`:
```json
{
  "status": "STEP_COMPLETE",
  "collisions_detected": 3,
  "maneuvers_executed": 3,
  "fleet_metrics": {
    "uptime_pct": 94.0,
    "total_fuel_used_kg": 1.834,
    "optimization_ratio": 51.2,
    "sats_in_slot": 47,
    "sats_total": 50
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
      "deltaV_vector": { "x": 0.002, "y": 0.010, "z": -0.001 }
    }
  ]
}
```

Validated against: satellite existence · Δv ≤ 15 m/s · 600 s cooldown · sufficient fuel · ground station LOS

### `GET /api/visualization/snapshot`
Compressed fleet state. Debris returned as flattened tuples `[ID, lat, lon, alt]` for minimal payload size.

### `GET /api/maneuvers/active`
All pending burns across the constellation with type, execute_at, and status.

### `GET /api/los/check?x=6778&y=0&z=0`
Per-station elevation angles computed using GAST at simulation epoch.

### `GET /api/events`
Last 500 structured events: `CDM_DETECTED`, `MANEUVER_PLANNED`, `MANEUVER_EXECUTED`, `RECOVERY_SCHEDULED`, `RECOVERY_EXECUTED`, `EOL_TRIGGERED`, `GRAVEYARD_EXECUTED`.

---

## Evaluation Criteria

| Criteria | Weight | How We Address It |
|---|---|---|
| **Safety Score** | 25% | 4-stage pipeline (Stage 0 + KDTree + Linear TCA + Propagated TCA); geometry-aware RTN evasion; real LOS validation |
| **Fuel Efficiency** | 20% | RTN axis selection picks cheapest burn per geometry; dynamic Tsiolkovsky wet mass; slot-targeted recovery |
| **Constellation Uptime** | 15% | Nominal slot propagated with same RK4+J2; TCA-aware recovery only fires when threat clears; 10 km box monitoring |
| **Algorithmic Speed** | 15% | KDTree O(N log N); adaptive step sizing; velocity-adaptive TCA coarse step; 500 ms snapshot TTL cache |
| **UI/UX & Visualization** | 15% | PS1 Mouthwashing globe; pulsing ground station beacons; satellites rotate with Earth; Gantt timeline; Bullseye plot |
| **Code Quality** | 10% | Structured JSON event logging (7 event types); typed Pydantic models; modular architecture; full stress test suite |

---

## Quick Start

### Docker
```bash
docker build -t acm .
docker run -p 8000:8000 acm
# Full stack at http://localhost:8000
```

### Local Development

**Backend** (run from project root, not inside `app/`):
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
# Open http://localhost:3000
```

### Stress Test
```bash
python app/stress_test.py
```

---

## Project Structure

```
acm-project/
├── app/
│   ├── main.py                  # FastAPI entry point, all routers, snapshot
│   ├── config.py                # Global state, sim clock, SIM_EPOCH_UNIX
│   ├── logger.py                # Structured JSON event log (ring buffer)
│   ├── stress_test.py           # Automated test suite
│   ├── api/
│   │   ├── telemetry.py         # POST /api/telemetry
│   │   ├── simulate.py          # POST /api/simulate/step
│   │   ├── maneuver.py          # POST /api/maneuver/schedule + active
│   │   ├── los.py               # GET /api/los/check (real LOS geometry)
│   │   ├── ground_stations.py   # Pass windows + blackout calculator
│   │   └── station_keeping.py   # 10 km box monitor + CW recovery burns
│   ├── orbit/
│   │   └── propagator.py        # RK4 + J2, adaptive step sizing
│   ├── collision/
│   │   ├── conjunction.py       # KDTree query, severity tiers
│   │   └── spatial_index.py     # sklearn KDTree wrapper
│   ├── prediction/
│   │   ├── predictor.py         # Stage 0–3 pipeline
│   │   └── tca.py               # linear_tca + propagated_tca
│   ├── maneuver/
│   │   ├── planner.py           # RTN evasion, TCA-aware recovery, EOL
│   │   └── fuel_model.py        # Tsiolkovsky + max_delta_v
│   └── models/
│       ├── satellite.py         # Dynamic mass, cooldown, nominal slot
│       └── debris.py            # ECI state vector
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Layout, polling, step button
│   │   ├── index.css            # VT323 font, CRT design system
│   │   └── components/
│   │       ├── Globe3D.jsx      # Three.js PS1 globe + ground stations
│   │       ├── BullseyePlot.jsx # Polar conjunction chart
│   │       ├── FuelGauges.jsx   # Fleet fuel monitoring
│   │       └── ManeuverTimeline.jsx  # Gantt burn scheduler
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── Dockerfile                   # Multi-stage: Node build → ubuntu:22.04
├── requirements.txt
├── ground_stations.csv
└── README.md
```

---

## Team Solis

Built for the **National Space Hackathon 2026 — Project AETHER**.
