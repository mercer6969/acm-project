# ◈ Autonomous Constellation Manager (ACM)
### National Space Hackathon 2026 — Project SOLIS

> A high-performance backend system and real-time 3D dashboard for autonomous satellite collision avoidance, maneuver planning, and constellation management in Low Earth Orbit.

---

![Status](https://img.shields.io/badge/status-operational-00ff88?style=for-the-badge&labelColor=040a0f)
![Python](https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python&labelColor=040a0f)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&labelColor=040a0f)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&labelColor=040a0f)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&labelColor=040a0f)

---

## Overview

The ACM is a ground-based autonomous system acting as the "brain" for a fleet of 50+ active satellites navigating a hazardous debris field in LEO. It continuously ingests orbital telemetry, predicts conjunctions up to 24 hours ahead, and autonomously plans and executes collision avoidance maneuvers — all without human intervention.

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
        CFG[config.py\nsatellites + debris dicts\nsim clock]
        SATM[models/satellite.py]
        DEBM[models/debris.py]
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
    C --> D[advance_sim_time]
    D --> E[execute_scheduled_burns]
    E --> F[predict_conjunctions\n24hr lookahead]

    subgraph PIPELINE["3-Stage Conjunction Pipeline"]
        F --> G[Stage 1: KDTree\nfilter within 50km]
        G --> H[Stage 2: Linear TCA\neliminate safe trajectories]
        H --> I[Stage 3: Propagated TCA\nRK4 two-pass 24hr scan]
    end

    I --> J{severity?}
    J -->|CRITICAL under 0.1km| K[plan_maneuver]
    J -->|YELLOW under 5km| L[Log warning]
    K --> M[Apply evasion burn\nsat.v += dv]
    M --> N[Tsiolkovsky fuel depletion]
    N --> O[Schedule recovery burn\nT + 660s]
    O --> P([STEP_COMPLETE response])
```

---

## Conjunction Detection Pipeline

```mermaid
flowchart LR
    A[50 Satellites\n10000+ Debris] --> B

    subgraph S1["Stage 1 — KDTree"]
        B[Build KDTree over debris]
        B --> C[Query 50km radius per sat]
        C --> D[99%+ debris eliminated]
    end

    D --> E

    subgraph S2["Stage 2 — Linear TCA"]
        E[Compute linear closest approach\nconstant velocity assumption]
        E --> F{Future threat?}
        F -->|No| G[Skip]
        F -->|Yes| H[Pass to Stage 3]
    end

    H --> I

    subgraph S3["Stage 3 — Propagated TCA"]
        I[Coarse RK4 scan\n60s steps over 24hr]
        I --> J[Fine RK4 scan\n5s steps around minimum]
        J --> K{dist under 0.1km?}
        K -->|Yes| L[CRITICAL warning]
        K -->|No| M[Safe — discard]
    end
```

---

## Maneuver Planning Flow

```mermaid
flowchart TD
    A([plan_maneuver called]) --> B{Satellite exists?}
    B -->|No| Z1([Return None])
    B -->|Yes| C{Cooldown active?}
    C -->|Yes| Z2([COOLDOWN status])
    C -->|No| D{Fuel under 5%?}
    D -->|Yes| E[Graveyard burn\nprograde to raise apogee]
    D -->|No| F[Compute evasion dv\nRTN frame geometry]
    F --> G[dv = away from debris\n10 m/s magnitude]
    G --> H[Tsiolkovsky fuel cost]
    H --> I{Enough fuel?}
    I -->|No| Z3([INSUFFICIENT_FUEL])
    I -->|Yes| J[Apply evasion burn\nsat.v += dv]
    J --> K[Deplete fuel mass]
    K --> L[Start 600s cooldown]
    L --> M[Schedule recovery burn\nT + 660s]
    M --> N([Return maneuver dict])
```

---

## Fuel Model

```mermaid
flowchart LR
    A[delta_v km/s] --> B[Convert to m/s]
    B --> C[dm = m_wet x 1 - e to the power of -dv divided by Isp x g0]
    C --> D[sat.fuel -= dm]
    D --> E{fuel fraction\nunder 5%?}
    E -->|Yes| F[Flag EOL\nschedule graveyard]
    E -->|No| G[Continue ops]

    subgraph K["Constants"]
        H[Isp = 300s\ng0 = 9.80665\nMax dv = 15 m/s\nCooldown = 600s]
    end
```

---

## Frontend Component Tree

```mermaid
flowchart TD
    APP[App.jsx\npolls snapshot + maneuvers every 2s\nmanages all state]

    APP -->|satellites debrisCloud selectedSat| GLOBE[Globe3D.jsx\nThree.js PS1 Earth\nReal texture + flat shading\nInstanced debris cloud\nSatellite 3D models + trails\nCRT scanline overlay]

    APP -->|warnings selectedSat| BULL[BullseyePlot.jsx\nCanvas 2D polar chart\nDebris by distance + angle\nColour coded by severity]

    APP -->|satellites| FUEL[FuelGauges.jsx\nPer-satellite fuel bars\nRecharts fleet chart\nLow fuel warnings]

    APP -->|satellites maneuvers simTime| GANTT[ManeuverTimeline.jsx\nGantt rows per satellite\nOrange = evasion burn\nStriped = 600s cooldown\nBlue = recovery burn]
```

---

## File Reference

```mermaid
flowchart TD
    subgraph ROOT["Project Root"]
        DF[Dockerfile\nubuntu:22.04\nexposes port 8000]
        REQ[requirements.txt\nfastapi uvicorn numpy scikit-learn]
        ST[stress_test.py\n50 sats 500 debris 7 tests]
        RM[README.md]
    end

    subgraph APP["app/"]
        MAIN[main.py\nFastAPI app + routers\nvisualization snapshot endpoint]
        CFG[config.py\nglobal satellites + debris dicts\nsim clock functions]

        subgraph API["api/"]
            TAPI[telemetry.py\nPOST /api/telemetry\nroutes SATELLITE vs DEBRIS]
            SAPI[simulate.py\nPOST /api/simulate/step\nfull pipeline per tick]
            MAPI[maneuver.py\nPOST /api/maneuver/schedule\nGET /api/maneuvers/active]
        end

        subgraph ORBIT["orbit/"]
            OPROP[propagator.py\nRK4 4th order\nJ2 perturbation\nadaptive step sizing]
        end

        subgraph COL["collision/"]
            CCONJ[conjunction.py\nKDTree query\nYELLOW RED CRITICAL tiers]
            CTREE[spatial_index.py\nsklearn KDTree\nbuild + query helpers]
        end

        subgraph PRED["prediction/"]
            PPRED[predictor.py\n3-stage pipeline\n24hr horizon]
            PTCA[tca.py\nlinear_tca fast\npropagated_tca accurate]
        end

        subgraph MAN["maneuver/"]
            MPLAN[planner.py\nplan_maneuver\nexecute_scheduled_burns\ngraveyard EOL]
            MFUEL[fuel_model.py\nTsiolkovsky\nmax_delta_v helper]
        end

        subgraph MOD["models/"]
            MSAT[satellite.py\ndynamic mass property\ncooldown tracking\nnominal slot]
            MDEB[debris.py\nr v state vectors]
        end
    end

    subgraph FE["frontend/"]
        PKG[package.json\nReact 18 + Three.js + Recharts]
        VCFG[vite.config.js\nproxy /api to port 8000]

        subgraph SRC["src/"]
            AAPP[App.jsx\nlayout + polling + step button]
            ICSS[index.css\nVT323 font CRT design tokens]

            subgraph COMP["components/"]
                CG[Globe3D.jsx\nMouthwashing PS1 Earth\nflat shading NearestFilter]
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
| EOL fuel threshold | 5% |
| Collision radius | 100 m (0.1 km) |
| Station-keeping box | 10 km radius |

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

### `GET /api/visualization/snapshot`
Compressed fleet snapshot for 3D frontend rendering.

### `GET /api/maneuvers/active`
All pending scheduled burns across the constellation.

---

## Quick Start

### Docker
```bash
docker build -t acm .
docker run -p 8000:8000 acm
```

### Local Development

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

### Stress Test
```bash
pip install requests
python stress_test.py
```

---

## Evaluation Criteria

| Criteria | Weight | Implementation |
|---|---|---|
| Safety Score | 25% | 3-stage conjunction pipeline, autonomous evasion |
| Fuel Efficiency | 20% | RTN-frame burns, Tsiolkovsky mass tracking |
| Constellation Uptime | 15% | Station-keeping box, recovery burns |
| Algorithmic Speed | 15% | KDTree O(N log N), adaptive RK4 step sizing |
| UI/UX & Visualization | 15% | PS1 Mouthwashing-style 3D globe, real-time panels |
| Code Quality | 10% | Modular architecture, typed models, logging |

---

## Team Solis

Built for the **National Space Hackathon 2026**.
## Project Structure

```
ACM PROJECT
├── app/
│   ├── __pycache__/
│   ├── api/
│   │   ├── __pycache__/
│   │   ├── maneuver.py
│   │   ├── simulate.py
│   │   └── telemetry.py
│   ├── collision/
│   │   ├── __pycache__/
│   │   ├── conjunction.py
│   │   └── spatial_index.py
│   ├── maneuver/
│   │   ├── __pycache__/
│   │   ├── fuel_model.py
│   │   └── planner.py
│   ├── models/
│   │   ├── __pycache__/
│   │   ├── debris.py
│   │   └── satellite.py
│   ├── orbit/
│   │   ├── __pycache__/
│   │   └── propagator.py
│   ├── physics/
│   │   └── __pycache__/
│   │       └── propagator.cpython-314.pyc
│   ├── prediction/
│   │   ├── __pycache__/
│   │   ├── predictor.py
│   │   └── tca.py
│   ├── config.py
│   ├── main.py
│   └── stress_test.py
│
├── frontend/
│   ├── node_modules/
│   └── src/
│       ├── components/
│       │   ├── BullseyePlot.jsx
│       │   ├── FuelGauges.jsx
│       │   ├── Globe3D.jsx
│       │   └── ManeuverTimeline.jsx
│       ├── App.jsx
│       ├── index.css
│       └── main.jsx
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   └── vite.config.js
│
├── dockerfile
├── README.md
└── requirements.txt
```
## 📁 Project Structure (Explained)

```
ACM PROJECT
```

### 🔧 Backend (`app/`)
Core logic for simulation, prediction, and maneuver planning.

- **api/** → Handles API endpoints (routes)
  - `simulate.py` → Runs simulation steps
  - `maneuver.py` → Handles maneuver-related requests
  - `telemetry.py` → Satellite data / telemetry APIs  

- **collision/** → Collision detection system  
  - `conjunction.py` → Detects close approaches between objects  
  - `spatial_index.py` → Optimized spatial searching  

- **maneuver/** → Maneuver planning logic  
  - `planner.py` → Decides how to avoid collisions  
  - `fuel_model.py` → Calculates fuel usage  

- **models/** → Data structures  
  - `satellite.py` → Satellite model  
  - `debris.py` → Space debris model  

- **orbit/** → Orbital mechanics  
  - `propagator.py` → Updates satellite position over time  

- **prediction/** → Future risk analysis  
  - `predictor.py` → Predicts possible collisions  
  - `tca.py` → Time of Closest Approach calculations  

- `config.py` → Configuration (constants, parameters)  
- `main.py` → Entry point (starts backend server)  
- `stress_test.py` → Performance testing  

---

### 🌐 Frontend (`frontend/`)
User interface built with React + Vite.

- **src/components/** → UI components  
  - `Globe3D.jsx` → 3D Earth visualization  
  - `BullseyePlot.jsx` → Collision visualization  
  - `FuelGauges.jsx` → Fuel usage display  
  - `ManeuverTimeline.jsx` → Timeline of maneuvers  

- `App.jsx` → Main app component  
- `main.jsx` → React entry point  
- `index.css` → Styling  

- `index.html` → Root HTML file  
- `package.json` → Project dependencies  
- `vite.config.js` → Vite configuration  

---

### ⚙️ Other Files

- `dockerfile` → Container setup  
- `requirements.txt` → Python dependencies  
- `README.md` → Project documentation  

---

### 💡 Summary
This project simulates **satellite collision detection and avoidance**, combining:
- Orbital physics  
- Collision prediction  
- Maneuver planning  
- Interactive 3D visualization  
### CONTEXT.md
-------------------------------------------------------------------------------------------------------------------------------------------------
# ACM Project — CONTEXT.md
> Read this file first. It gives a complete picture of the codebase so you can jump in without asking basic questions.

---

## What This Project Is

An **Autonomous Constellation Manager (ACM)** built for the National Space Hackathon 2026. It is a full-stack system that:

1. Ingests real-time orbital telemetry (position + velocity) for satellites and debris
2. Predicts collisions up to 24 hours ahead using a 3-stage spatial filtering pipeline
3. Autonomously plans and executes evasion + recovery maneuvers
4. Renders everything on a PS1/Mouthwashing-style 3D globe dashboard

**Stack:** Python 3.14 + FastAPI backend, React 18 + Three.js frontend, Docker for deployment.

---

## Project Structure

```
ACM PROJECT/
├── app/                        # All backend Python code
│   ├── main.py                 # FastAPI app entry point — registers all routers + snapshot endpoint
│   ├── config.py               # Global state: satellites dict, debris dict, sim clock
│   ├── api/
│   │   ├── telemetry.py        # POST /api/telemetry — ingests objects into global state
│   │   ├── simulate.py         # POST /api/simulate/step — runs full physics tick
│   │   └── maneuver.py         # POST /api/maneuver/schedule + GET /api/maneuvers/active
│   ├── orbit/
│   │   └── propagator.py       # RK4 integrator + J2 perturbation — the physics core
│   ├── collision/
│   │   ├── conjunction.py      # KDTree query, severity classification (YELLOW/RED/CRITICAL)
│   │   └── spatial_index.py    # sklearn KDTree wrapper (build_tree, query_collisions)
│   ├── prediction/
│   │   ├── predictor.py        # 3-stage conjunction pipeline, 24hr lookahead
│   │   └── tca.py              # linear_tca (fast) + propagated_tca (accurate two-pass RK4)
│   ├── maneuver/
│   │   ├── planner.py          # plan_maneuver, execute_scheduled_burns, graveyard logic
│   │   └── fuel_model.py       # Tsiolkovsky rocket equation, max_delta_v helper
│   └── models/
│       ├── satellite.py        # Satellite class — dynamic mass, cooldown, nominal slot
│       └── debris.py           # Debris class — just r and v
├── frontend/
│   ├── index.html
│   ├── vite.config.js          # proxies /api → localhost:8000
│   ├── package.json
│   └── src/
│       ├── main.jsx            # React entry point
│       ├── App.jsx             # Main layout, polling every 2s, step button
│       ├── index.css           # Design tokens, CRT effects, VT323 font
│       └── components/
│           ├── Globe3D.jsx         # Three.js scene — Mouthwashing PS1 Earth + satellites + debris
│           ├── BullseyePlot.jsx    # Canvas 2D polar chart — debris threats around selected sat
│           ├── FuelGauges.jsx      # Per-satellite fuel bars + Recharts fleet chart
│           └── ManeuverTimeline.jsx # Gantt chart — burn / cooldown / recovery blocks
├── Dockerfile                  # ubuntu:22.04, exposes port 8000, required for grader
├── requirements.txt            # fastapi uvicorn numpy scikit-learn
├── stress_test.py              # 50 sats + 500 debris automated test suite
└── README.md                   # Full docs with Mermaid flowcharts
```

---

## How the Simulation Works

### Global State (`config.py`)
Everything lives in two plain Python dicts:
```python
satellites: Dict[str, Satellite]   # keyed by sat ID e.g. "SAT-001"
debris:     Dict[str, Debris]      # keyed by debris ID e.g. "DEB-00042"
```
Plus a float `_sim_time` tracking elapsed simulation seconds. No database — pure in-memory. Resets on every server restart.

### Per Tick (`api/simulate.py`)
Every `POST /api/simulate/step` does this in order:
1. Propagate all satellites (RK4 + J2)
2. Propagate all debris (RK4 + J2)
3. Advance sim clock
4. Execute any scheduled recovery burns
5. Run 3-stage conjunction predictor
6. For each CRITICAL conjunction → plan evasion + schedule recovery
7. Return summary

### Orbital Propagation (`orbit/propagator.py`)
- Uses RK4 (Runge-Kutta 4th order) with adaptive step sizing — max 30s steps regardless of tick size
- Includes J2 perturbation (Earth's equatorial bulge) — required by spec, causes nodal regression
- `propagate_orbit(r, v, total_dt)` is the main function used everywhere

### Conjunction Detection
Three stages to avoid O(N²):
- **Stage 1:** KDTree over all debris positions, query 50km radius per satellite — eliminates 99%+ instantly
- **Stage 2:** Linear TCA (constant velocity assumption) — fast filter, skips non-threatening trajectories
- **Stage 3:** Propagated TCA — two-pass RK4 scan (60s coarse then 5s fine) over full 24hr horizon

Collision threshold: **0.1 km (100 metres)**

### Maneuver Planning (`maneuver/planner.py`)
- Evasion direction computed in RTN frame — burns in transverse direction away from debris
- Magnitude: 10 m/s evasion, 10 m/s recovery
- Recovery burn scheduled 660s after evasion (600s cooldown + 60s buffer)
- Fuel depleted using Tsiolkovsky with **current wet mass** (not initial — mass decreases each burn)
- If fuel < 5% → graveyard burn instead of evasion

### Satellite Model (`models/satellite.py`)
Key properties:
```python
sat.mass          # @property — dry_mass + fuel (dynamic, decreases each burn)
sat.fuel          # kg remaining (starts at 50.0)
sat.dry_mass      # 500.0 kg (never changes)
sat.last_burn_time     # sim time of last burn — used for 600s cooldown
sat.scheduled_burns    # list of pending burn dicts
sat.nominal_r/v        # ideal orbital slot — propagated alongside real position
sat.status        # "NOMINAL" | "EVADING" | "EOL"
```

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/telemetry` | Ingest satellite + debris state vectors |
| POST | `/api/simulate/step` | Advance physics by N seconds |
| POST | `/api/maneuver/schedule` | Validate + schedule a burn sequence |
| GET | `/api/visualization/snapshot` | Compressed lat/lon/fuel/status for frontend |
| GET | `/api/maneuvers/active` | All pending burns across constellation |
| GET | `/` | Health check |

### Key Request Formats

**Telemetry** — type must be `"SATELLITE"` or `"DEBRIS"` (case-insensitive):
```json
{
  "timestamp": "2026-03-12T08:00:00.000Z",
  "objects": [
    { "id": "SAT-001", "type": "SATELLITE",
      "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
      "v": {"x": 0.0, "y": 7.669, "z": 0.0} }
  ]
}
```

**Simulate step:**
```json
{ "step_seconds": 60 }
```

**Maneuver schedule** — delta_v in km/s, max magnitude 0.015 km/s (15 m/s):
```json
{
  "satelliteId": "SAT-001",
  "maneuver_sequence": [
    { "burn_id": "BURN_1", "burnTime": "2026-03-12T14:00:00.000Z",
      "deltaV_vector": {"x": 0.002, "y": 0.010, "z": -0.001} }
  ]
}
```

---

## Frontend

### Layout (App.jsx)
3-column CSS grid:
```
[Left: Sat list + Event log] [Centre: 3D Globe] [Right: Bullseye plot]
[Bottom-left: Fuel gauges  ] [Bottom centre+right: Maneuver timeline  ]
```

Polls `/api/visualization/snapshot` and `/api/maneuvers/active` every **2 seconds**.
Step button posts `{ step_seconds: 60 }` to `/api/simulate/step`.

### Globe (Globe3D.jsx)
- Three.js WebGL renderer, `pixelRatio: 0.6` for chunky PS1 pixel look
- Earth: `IcosahedronGeometry(1, 6)` + `flatShading: true` + NASA blue marble texture with `NearestFilter`
- This combination samples the photo texture per-face and renders it flat = Mouthwashing polygon look
- Debris: `InstancedMesh` of red tetrahedra — performant for thousands of objects
- Satellites: low-poly box body + solar wings + dish, colour by status (green/amber/red)
- Orbit trails: 10 fading dots behind each satellite
- HTML overlays: CRT scanlines, vignette, terminal text boxes in corners
- Camera: full spherical orbit via mouse drag, scroll to zoom

### Design Language
- Font: VT323 (headers) + Share Tech Mono (data) — loaded from Google Fonts
- Colors: `--green: #00ff88`, `--amber: #ffaa00`, `--red: #ff3333`, `--bg: #040a0f`
- CRT scanlines applied globally via `body::after` in `index.css`
- All panels have a subtle top-edge green gradient line via `.panel::before`

---

## Physics Constants

| Constant | Value |
|---|---|
| μ (Earth gravitational parameter) | 398600.4418 km³/s² |
| R_E (Earth radius) | 6378.137 km |
| J2 | 1.08263×10⁻³ |
| Isp | 300 s |
| g₀ | 9.80665 m/s² |
| Dry mass | 500.0 kg |
| Initial fuel | 50.0 kg |
| Max Δv per burn | 15.0 m/s (0.015 km/s) |
| Thruster cooldown | 600 s |
| EOL fuel threshold | 5% (2.5 kg) |
| Collision radius | 0.1 km (100 m) |
| Station-keeping box | 10 km radius |
| Signal latency | 10 s |

---

## Running Locally

```bash
# Backend (from project root — NOT from inside app/)
pip install -r requirements.txt
py -m uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

**Common mistake:** running uvicorn from inside `app/` causes `ModuleNotFoundError: No module named 'app'`. Always run from the project root.

```bash
# Docker
docker build -t acm .
docker run -p 8000:8000 acm

# Stress test (backend must be running)
py stress_test.py
```

---

## Known Quirks

- **State resets on restart** — all satellites and debris are in-memory only. Re-POST telemetry after every restart.
- **Debris not propagated before first step** — debris positions are static until the first `/api/simulate/step` call.
- **Trench line on globe** — the red zigzag line on the Earth is purely decorative, inspired by the Mouthwashing game reference image. It has no physics meaning.
- **`physics/propagator.py`** — this file should be deleted. It's a dead Euler integrator with no J2. Everything should import from `orbit/propagator.py` only.
- **Satellite trail direction** — trails approximate backward orbit by stepping west in longitude. Not physically accurate but visually correct for low-inclination orbits.
- **TCA horizon** — predictor uses 86400s (24hr) lookahead as required by spec. On large constellations this can be slow if many debris pass Stage 2 filter.

---


