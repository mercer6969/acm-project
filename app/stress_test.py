"""
ACM Stress Test
───────────────
Tests the full ACM pipeline with:
  - 50 satellites
  - 500 debris objects (some on collision courses)
  - 10 simulate/step calls
  - Maneuver schedule validation
  - Snapshot performance check

Run from project root:
  python app/stress_test.py
"""

import requests
import random
import math
import time
import json

BASE = "http://localhost:8000"

# ── Helpers ────────────────────────────────────────────────────────────────────

def post(endpoint, payload):
    r = requests.post(f"{BASE}{endpoint}", json=payload)
    return r.status_code, r.json()

def get(endpoint):
    r = requests.get(f"{BASE}{endpoint}")
    return r.status_code, r.json()

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_ok(msg):   print(f"  ✅  {msg}")
def print_warn(msg): print(f"  ⚠️   {msg}")
def print_err(msg):  print(f"  ❌  {msg}")

# ── Orbit helpers ──────────────────────────────────────────────────────────────

def circular_orbit_velocity(r_km):
    """Compute circular orbit velocity for given radius."""
    MU = 398600.4418
    return math.sqrt(MU / r_km)

def orbit_position(altitude_km, angle_deg, inclination_deg=0):
    """Generate ECI position for a circular orbit."""
    r = 6378.137 + altitude_km
    angle = math.radians(angle_deg)
    inc   = math.radians(inclination_deg)
    x = r * math.cos(angle)
    y = r * math.sin(angle) * math.cos(inc)
    z = r * math.sin(angle) * math.sin(inc)
    return x, y, z

def orbit_velocity(altitude_km, angle_deg, inclination_deg=0):
    """Generate ECI velocity for a circular orbit."""
    r     = 6378.137 + altitude_km
    v     = circular_orbit_velocity(r)
    angle = math.radians(angle_deg)
    inc   = math.radians(inclination_deg)
    vx = -v * math.sin(angle)
    vy =  v * math.cos(angle) * math.cos(inc)
    vz =  v * math.cos(angle) * math.sin(inc)
    return vx, vy, vz

# ── Build telemetry payload ────────────────────────────────────────────────────

def build_telemetry(n_sats=50, n_debris=500, n_collisions=10):
    """
    Build a telemetry payload with:
      - n_sats satellites evenly spaced in LEO
      - n_debris random debris objects
      - n_collisions debris placed dangerously close to satellites
    """
    objects = []

    # ── Satellites: evenly spaced at 400km altitude, various inclinations ─────
    altitudes    = [400, 450, 500, 550, 600]
    inclinations = [0, 28, 45, 53, 97]

    for i in range(n_sats):
        alt  = altitudes[i % len(altitudes)]
        inc  = inclinations[i % len(inclinations)]
        angle = (i / n_sats) * 360

        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)

        objects.append({
            "id": f"SAT-{i+1:03d}",
            "type": "SATELLITE",
            "r": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
            "v": {"x": round(vx, 6), "y": round(vy, 6), "z": round(vz, 6)},
        })

    # ── Debris: random LEO positions ──────────────────────────────────────────
    for i in range(n_debris - n_collisions):
        alt   = random.uniform(380, 650)
        angle = random.uniform(0, 360)
        inc   = random.uniform(-90, 90)

        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)

        # Add random velocity perturbation for cross-track debris
        vx += random.uniform(-0.5, 0.5)
        vy += random.uniform(-0.5, 0.5)
        vz += random.uniform(-0.5, 0.5)

        objects.append({
            "id": f"DEB-{i+1:05d}",
            "type": "DEBRIS",
            "r": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
            "v": {"x": round(vx, 6), "y": round(vy, 6), "z": round(vz, 6)},
        })

    # ── Collision-course debris: placed very close to specific satellites ──────
    for i in range(n_collisions):
        sat_obj = objects[i]  # target the first n_collision satellites
        sx = sat_obj["r"]["x"]
        sy = sat_obj["r"]["y"]
        sz = sat_obj["r"]["z"]
        svx = sat_obj["v"]["x"]
        svy = sat_obj["v"]["y"]
        svz = sat_obj["v"]["z"]

        # Place debris 50-90 metres away (within 100m collision threshold)
        offset = random.uniform(0.05, 0.09)  # km
        objects.append({
            "id": f"DEB-THREAT-{i+1:03d}",
            "type": "DEBRIS",
            "r": {
                "x": round(sx + offset, 4),
                "y": round(sy, 4),
                "z": round(sz, 4),
            },
            "v": {
                "x": round(svx, 6),
                "y": round(svy + 0.001, 6),  # slight relative velocity
                "z": round(svz, 6),
            },
        })

    return {
        "timestamp": "2026-03-12T08:00:00.000Z",
        "objects": objects,
    }

# ── Test runner ────────────────────────────────────────────────────────────────

def test_health():
    print_section("1. HEALTH CHECK")
    code, data = get("/")
    if code == 200 and data.get("status") == "ACM Running":
        print_ok(f"Backend alive: {data}")
    else:
        print_err(f"Backend not responding! Code={code}")
        exit(1)

def test_telemetry(n_sats, n_debris, n_collisions):
    print_section(f"2. TELEMETRY INGESTION ({n_sats} sats, {n_debris} debris, {n_collisions} on collision course)")
    payload = build_telemetry(n_sats, n_debris, n_collisions)
    total   = len(payload["objects"])

    t0 = time.time()
    code, data = post("/api/telemetry", payload)
    elapsed = time.time() - t0

    if code == 200 and data.get("status") == "ACK":
        print_ok(f"ACK received — {data['processed_count']} objects in {elapsed*1000:.1f}ms")
        print_ok(f"Active CDM warnings: {data.get('active_cdm_warnings', 0)}")
        if data.get('active_cdm_warnings', 0) > 0:
            print_warn(f"Immediate conjunctions detected on ingestion!")
    else:
        print_err(f"Telemetry failed: {code} — {data}")

def test_simulate_steps(n_steps=10):
    print_section(f"3. SIMULATE STEP x{n_steps} (60s each = {n_steps} min simulated)")
    total_maneuvers  = 0
    total_collisions = 0

    for i in range(n_steps):
        t0 = time.time()
        code, data = post("/api/simulate/step", {"step_seconds": 60})
        elapsed = time.time() - t0

        if code != 200:
            print_err(f"Step {i+1} failed: {code}")
            continue

        collisions = data.get("collisions_detected", 0)
        maneuvers  = data.get("maneuvers_executed", 0)
        total_collisions += collisions
        total_maneuvers  += maneuvers

        status = "⚠️ " if collisions > 0 else "✅"
        print(f"  {status} Step {i+1:2d} | T+{(i+1)*60:4d}s "
              f"| {elapsed*1000:6.1f}ms "
              f"| collisions={collisions} "
              f"| maneuvers={maneuvers}")

    print()
    if total_collisions == 0:
        print_ok(f"All {n_steps} steps clean — 0 collisions!")
    else:
        print_warn(f"{total_collisions} collision event(s) across {n_steps} steps")
    print_ok(f"Total maneuvers executed: {total_maneuvers}")

def test_maneuver_schedule():
    print_section("4. MANEUVER SCHEDULE ENDPOINT")

    # Valid maneuver — should be accepted
    code, data = post("/api/maneuver/schedule", {
        "satelliteId": "SAT-001",
        "maneuver_sequence": [
            {
                "burn_id": "STRESS_EVASION_1",
                "burnTime": "2026-03-12T14:00:00.000Z",
                "deltaV_vector": {"x": 0.002, "y": 0.010, "z": -0.001}
            },
            {
                "burn_id": "STRESS_RECOVERY_1",
                "burnTime": "2026-03-12T15:30:00.000Z",
                "deltaV_vector": {"x": -0.002, "y": -0.010, "z": 0.001}
            }
        ]
    })
    if data.get("status") == "SCHEDULED":
        print_ok(f"Valid maneuver accepted — fuel remaining: {data['validation']['projected_mass_remaining_kg']}kg")
    else:
        print_err(f"Valid maneuver rejected: {data.get('reason')}")

    # Over-limit maneuver — should be rejected
    code2, data2 = post("/api/maneuver/schedule", {
        "satelliteId": "SAT-001",
        "maneuver_sequence": [
            {
                "burn_id": "OVERLIMIT_BURN",
                "burnTime": "2026-03-12T14:00:00.000Z",
                "deltaV_vector": {"x": 0.01, "y": 0.02, "z": 0.01}  # >15 m/s
            }
        ]
    })
    if data2.get("status") == "REJECTED":
        print_ok(f"Over-limit burn correctly rejected: {data2.get('reason')}")
    else:
        print_err(f"Over-limit burn should have been rejected!")

    # Unknown satellite — should be rejected
    code3, data3 = post("/api/maneuver/schedule", {
        "satelliteId": "SAT-GHOST",
        "maneuver_sequence": [
            {
                "burn_id": "GHOST_BURN",
                "burnTime": "2026-03-12T14:00:00.000Z",
                "deltaV_vector": {"x": 0.001, "y": 0.001, "z": 0.001}
            }
        ]
    })
    if data3.get("status") == "REJECTED":
        print_ok(f"Unknown satellite correctly rejected")
    else:
        print_err(f"Unknown satellite should have been rejected!")

def test_snapshot_performance():
    print_section("5. SNAPSHOT PERFORMANCE")
    times = []
    for i in range(5):
        t0 = time.time()
        code, data = get("/api/visualization/snapshot")
        elapsed = time.time() - t0
        times.append(elapsed * 1000)

    avg = sum(times) / len(times)
    mx  = max(times)
    sats    = len(data.get("satellites", []))
    debris  = len(data.get("debris_cloud", []))

    print_ok(f"Snapshot: {sats} sats + {debris} debris")
    print_ok(f"Avg response: {avg:.1f}ms | Max: {mx:.1f}ms")

    if avg < 100:
        print_ok("Snapshot performance: EXCELLENT (<100ms)")
    elif avg < 500:
        print_warn(f"Snapshot performance: OK ({avg:.0f}ms)")
    else:
        print_err(f"Snapshot performance: SLOW ({avg:.0f}ms) — may hurt UI score")

def test_active_maneuvers():
    print_section("6. ACTIVE MANEUVERS ENDPOINT")
    code, data = get("/api/maneuvers/active")
    if code == 200:
        burns = data.get("maneuvers", [])
        print_ok(f"Active maneuvers endpoint working — {len(burns)} burns queued")
        for b in burns[:3]:
            print(f"     · {b['satellite']} — {b['burn_id']} ({b['type']})")
        if len(burns) > 3:
            print(f"     · ... and {len(burns)-3} more")
    else:
        print_err(f"Active maneuvers endpoint failed: {code}")

def test_fuel_depletion():
    print_section("7. FUEL DEPLETION CHECK")
    code, data = get("/api/visualization/snapshot")
    sats = data.get("satellites", [])
    if not sats:
        print_warn("No satellites in snapshot")
        return

    evading = [s for s in sats if s.get("status") == "EVADING"]
    depleted = [s for s in sats if s.get("fuel_kg", 50) < 45]

    print_ok(f"Satellites evading: {len(evading)}")
    print_ok(f"Satellites with fuel < 45kg (burned some): {len(depleted)}")
    for s in depleted[:5]:
        print(f"     · {s['id']} — {s['fuel_kg']:.3f}kg remaining ({s['status']})")

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "█"*60)
    print("  ACM STRESS TEST — National Space Hackathon 2026")
    print("█"*60)

    N_SATS       = 50
    N_DEBRIS     = 500
    N_COLLISIONS = 10
    N_STEPS      = 10

    test_health()
    test_telemetry(N_SATS, N_DEBRIS, N_COLLISIONS)
    test_simulate_steps(N_STEPS)
    test_maneuver_schedule()
    test_snapshot_performance()
    test_active_maneuvers()
    test_fuel_depletion()

    print("\n" + "█"*60)
    print("  STRESS TEST COMPLETE")
    print("█"*60 + "\n")