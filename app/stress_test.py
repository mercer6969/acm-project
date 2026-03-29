"""
app/stress_test.py
──────────────────
ACM Stress Test — National Space Hackathon 2026
Run from project root: python app/stress_test.py
"""

import math
import random
import time

import requests

BASE = "http://localhost:8000"
random.seed(42)


# ── Helpers ───────────────────────────────────────────────────────────────────

def post(endpoint, payload):
    r = requests.post(f"{BASE}{endpoint}", json=payload, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}


def get(endpoint):
    r = requests.get(f"{BASE}{endpoint}", timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_ok(msg):   print(f"  ✅  {msg}")
def print_warn(msg): print(f"  ⚠️   {msg}")
def print_err(msg):  print(f"  ❌  {msg}")


# ── Orbit helpers ─────────────────────────────────────────────────────────────

MU = 398600.4418
RE = 6378.137


def circ_velocity(r_km):
    return math.sqrt(MU / r_km)


def orbit_position(alt_km, angle_deg, inc_deg=0):
    r = RE + alt_km
    a = math.radians(angle_deg)
    i = math.radians(inc_deg)
    return (r*math.cos(a),
            r*math.sin(a)*math.cos(i),
            r*math.sin(a)*math.sin(i))


def orbit_velocity(alt_km, angle_deg, inc_deg=0):
    r = RE + alt_km
    v = circ_velocity(r)
    a = math.radians(angle_deg)
    i = math.radians(inc_deg)
    return (-v*math.sin(a),
             v*math.cos(a)*math.cos(i),
             v*math.cos(a)*math.sin(i))


# ── Build telemetry ───────────────────────────────────────────────────────────

def build_telemetry(n_sats=50, n_debris=500, n_collisions=10):
    objects    = []
    sat_states = []
    alts = [400, 450, 500, 550, 600]
    incs = [0, 28, 45, 53, 97]

    for i in range(n_sats):
        alt   = alts[i % len(alts)]
        inc   = incs[i % len(incs)]
        angle = (i / n_sats) * 360
        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)
        sid = f"SAT-{i+1:03d}"
        objects.append({
            "id": sid, "type": "SATELLITE",
            "r": {"x": round(x,3),  "y": round(y,3),  "z": round(z,3)},
            "v": {"x": round(vx,6), "y": round(vy,6), "z": round(vz,6)},
        })
        sat_states.append((sid, x, y, z, vx, vy, vz))

    # 10 collision-course debris — 0.05 km directly in front of satellite
    collision_sats = random.sample(sat_states, min(n_collisions, len(sat_states)))
    for idx, (sid, sx, sy, sz, svx, svy, svz) in enumerate(collision_sats):
        speed = math.sqrt(svx**2 + svy**2 + svz**2)
        ux, uy, uz = svx/speed, svy/speed, svz/speed
        objects.append({
            "id": f"DEB-CRIT-{idx+1:03d}", "type": "DEBRIS",
            "r": {"x": round(sx - ux*0.05, 4),
                  "y": round(sy - uy*0.05, 4),
                  "z": round(sz - uz*0.05, 4)},
            "v": {"x": round(svx,6), "y": round(svy,6), "z": round(svz,6)},
        })

    # Remaining safe debris
    for i in range(n_debris - n_collisions):
        alt   = random.uniform(380, 650)
        angle = random.uniform(0, 360)
        inc   = random.uniform(0, 97)
        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)
        x += random.uniform(-50, 50)
        y += random.uniform(-50, 50)
        z += random.uniform(-20, 20)
        objects.append({
            "id": f"DEB-{i+1:04d}", "type": "DEBRIS",
            "r": {"x": round(x,3),  "y": round(y,3),  "z": round(z,3)},
            "v": {"x": round(vx,6), "y": round(vy,6), "z": round(vz,6)},
        })

    return objects, sat_states


# ── Find visible satellite ────────────────────────────────────────────────────

def _find_visible_satellite(sat_states):
    """
    Scan all satellites and return the one with the highest elevation
    above any ground station (using 5 degree operational mask).
    Falls back to SAT-001 if none found.
    """
    best_id   = None
    best_elev = -999.0

    for (sid, sx, sy, sz, *_) in sat_states:
        try:
            # Use sx, sy, sz — the actual satellite ECI coordinates
            code, los = get(f"/api/los/check?x={sx}&y={sy}&z={sz}&min_elev=5")
            if code != 200:
                continue
            for st in los.get("stations", []):
                elev = st.get("elevation_deg", -999.0)
                if elev > best_elev:
                    best_elev = elev
                    best_id   = sid
        except Exception:
            continue

    if best_id and best_elev >= 5.0:
        print(f"  (best visible sat: {best_id}, max elevation: {best_elev:.1f}°)")
        return best_id

    # No satellite above 5° — find the one closest to the horizon
    print(f"  (no sat above 5° mask, using closest-to-horizon)")
    best_id   = None
    best_elev = -999.0
    for (sid, sx, sy, sz, *_) in sat_states:
        try:
            code, los = get(f"/api/los/check?x={sx}&y={sy}&z={sz}&min_elev=-90")
            if code != 200:
                continue
            for st in los.get("stations", []):
                elev = st.get("elevation_deg", -999.0)
                if elev > best_elev:
                    best_elev = elev
                    best_id   = sid
        except Exception:
            continue

    if best_id:
        print(f"  (best available: {best_id}, elevation: {best_elev:.1f}°)")
    return best_id or "SAT-001"


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health():
    print_section("1. HEALTH CHECK")
    code, data = get("/")
    if code == 200 and "ACM Running" in str(data.get("status", "")):
        print_ok(f"Backend alive: {data}")
    else:
        print_err(f"Backend not responding! Code={code} Body={data}")
        exit(1)


def test_telemetry(objects):
    n_sats  = sum(1 for o in objects if o["type"] == "SATELLITE")
    n_deb   = sum(1 for o in objects if o["type"] == "DEBRIS")
    print_section(f"2. TELEMETRY INGESTION ({n_sats} sats, {n_deb} debris, 10 on collision course)")
    t0 = time.time()
    code, data = post("/api/telemetry", {
        "timestamp": "2026-03-12T08:00:00.000Z",
        "objects":   objects,
    })
    ms = (time.time() - t0) * 1000

    if code == 200 and data.get("status") == "ACK":
        print_ok(f"ACK received — {len(objects)} objects in {ms:.1f}ms")
        cdm = data.get("active_cdm_warnings", 0)
        print_ok(f"Active CDM warnings: {cdm}")
        if cdm > 0:
            print_warn("Immediate conjunctions detected on ingestion!")
    else:
        print_err(f"Telemetry FAILED: code={code} body={data}")


def test_maneuver_schedule(sat_states):
    """Run BEFORE simulate steps so satellites are at initial positions."""
    print_section("3. MANEUVER SCHEDULE ENDPOINT")

    vis_id = _find_visible_satellite(sat_states)

    # Test 1: Valid maneuver
    print(f"  Using {vis_id} for LOS-valid maneuver test")
    code, data = post("/api/maneuver/schedule", {
        "satelliteId": vis_id,
        "maneuver_sequence": [{
            "burn_id":       "STRESS_BURN_1",
            "burnTime":      "2026-03-12T14:00:00.000Z",
            "deltaV_vector": {"x": 0.002, "y": 0.010, "z": -0.001},
        }],
    })
    status = data.get("status", "")
    if status == "SCHEDULED":
        print_ok(f"Valid maneuver accepted for {vis_id}")
    else:
        reason = data.get("reason", "unknown")
        los_ok = data.get("validation", {}).get("ground_station_los", "?")
        print_err(f"Valid maneuver rejected: {reason} | LOS={los_ok}")
        if "LOS" in reason or "ground station" in reason.lower():
            print_warn("  Note: LOS rejection is physically correct if sat is in blackout")

    # Test 2: Over-limit burn
    code2, data2 = post("/api/maneuver/schedule", {
        "satelliteId": vis_id,
        "maneuver_sequence": [{
            "burn_id":       "OVERLIMIT_BURN",
            "burnTime":      "2026-03-12T15:00:00.000Z",
            "deltaV_vector": {"x": 0.010, "y": 0.010, "z": 0.010},
        }],
    })
    if data2.get("status") == "REJECTED":
        print_ok(f"Over-limit burn correctly rejected: {data2.get('reason','')}")
    else:
        print_err(f"Over-limit burn NOT rejected: {data2}")

    # Test 3: Unknown satellite
    code3, data3 = post("/api/maneuver/schedule", {
        "satelliteId": "SAT-GHOST-999",
        "maneuver_sequence": [{
            "burn_id":       "GHOST_BURN",
            "burnTime":      "2026-03-12T16:00:00.000Z",
            "deltaV_vector": {"x": 0.001, "y": 0.001, "z": 0.001},
        }],
    })
    if data3.get("status") == "REJECTED":
        print_ok("Unknown satellite correctly rejected")
    else:
        print_err(f"Unknown satellite NOT rejected: {data3}")

    # Test 4: Blind conjunction (SAT-001 regardless of LOS)
    code4, data4 = post("/api/maneuver/schedule", {
        "satelliteId": "SAT-001",
        "maneuver_sequence": [{
            "burn_id":       "BLIND_CONJ_TEST",
            "burnTime":      "2026-03-12T17:00:00.000Z",
            "deltaV_vector": {"x": 0.002, "y": 0.008, "z": -0.001},
        }],
    })
    sat1_status = data4.get("status", "UNKNOWN")
    sat1_los    = data4.get("validation", {}).get("ground_station_los", "?")
    print_ok(f"SAT-001 maneuver → {sat1_status} (LOS: {sat1_los})")


def test_simulate_steps(n_steps=10, step_s=60):
    print_section(f"4. SIMULATE STEP x{n_steps} ({step_s}s each = "
                  f"{n_steps*step_s//60} min simulated)")
    total_collisions = 0
    total_maneuvers  = 0

    for i in range(n_steps):
        t0 = time.time()
        code, data = post("/api/simulate/step", {"step_seconds": step_s})
        ms = (time.time() - t0) * 1000

        if code != 200:
            print_err(f"Step {i+1} FAILED: code={code}")
            continue

        cols = data.get("collisions_detected", 0)
        mans = data.get("maneuvers_executed",  0)
        conj = data.get("conjunctions_active", 0)
        total_collisions += cols
        total_maneuvers  += mans

        icon = "⚠️ " if cols > 0 else "✅"
        print(f"  {icon} Step {i+1:2d} | T+{(i+1)*step_s:4d}s | "
              f"{ms:7.1f}ms | collisions={cols} | "
              f"maneuvers={mans} | conjunctions={conj}")

    print()
    if total_collisions == 0:
        print_ok("All steps clean — 0 collisions!")
    else:
        print_warn(f"{total_collisions} collision events detected")
    print_ok(f"Total maneuvers executed: {total_maneuvers}")


def test_snapshot():
    print_section("5. SNAPSHOT PERFORMANCE")
    times = []
    snap  = None
    for _ in range(5):
        t0 = time.time()
        code, data = get("/api/visualization/snapshot")
        times.append((time.time() - t0) * 1000)
        if code == 200:
            snap = data

    avg_ms = sum(times) / len(times)
    max_ms = max(times)

    if snap:
        n_sats = len(snap.get("satellites", []))
        n_deb  = len(snap.get("debris", snap.get("debris_cloud", [])))
        print_ok(f"Snapshot: {n_sats} sats + {n_deb} debris")
    else:
        print_err("Snapshot returned empty or failed")

    print_ok(f"Avg response: {avg_ms:.1f}ms | Max: {max_ms:.1f}ms")
    if max_ms < 100:
        print_ok("Snapshot performance: EXCELLENT (<100ms)")
    elif max_ms < 500:
        print_warn(f"Snapshot performance: OK ({max_ms:.0f}ms)")
    else:
        print_err(f"Snapshot performance: SLOW ({max_ms:.0f}ms)")


def test_active_maneuvers():
    print_section("6. ACTIVE MANEUVERS ENDPOINT")
    code, data = get("/api/maneuvers/active")
    if code == 200:
        burns = data if isinstance(data, list) else data.get("maneuvers", [])
        print_ok(f"Active maneuvers endpoint working — {len(burns)} burns queued")
    else:
        print_err(f"Active maneuvers FAILED: code={code}")


def test_fuel():
    print_section("7. FUEL DEPLETION CHECK")
    code, snap = get("/api/visualization/snapshot")
    if code != 200:
        print_err("Could not fetch snapshot")
        return
    sats = snap.get("satellites", [])
    if not sats:
        print_warn("No satellites in snapshot")
        return
    evading  = [s for s in sats if s.get("status") == "EVADING"]
    low_fuel = [s for s in sats if s.get("fuel_kg", 50.0) < 45.0]
    if evading:
        print_warn(f"Satellites evading: {len(evading)}")
        for s in evading[:5]:
            print(f"     · {s['id']} — {s.get('fuel_kg',0):.3f}kg ({s.get('status','')})")
    else:
        print_ok("Satellites evading: 0")
    if low_fuel:
        print_warn(f"Satellites with fuel < 45kg: {len(low_fuel)}")
    else:
        print_ok("Fuel depletion check passed (0 sats below 45 kg)")


def test_events():
    print_section("8. EVENT LOG CHECK")
    code, data = get("/api/simulate/events")
    if code != 200:
        code, data = get("/api/events")
    if code == 200:
        events = data.get("events", [])
        count  = data.get("count", len(events))
        print_ok(f"Event log endpoint working — {count} events recorded")
        types = {}
        for e in events:
            t = e.get("event", "UNKNOWN")
            types[t] = types.get(t, 0) + 1
        for t, c in sorted(types.items()):
            print(f"     · {t}: {c}")
    else:
        print_err(f"Event log FAILED: code={code}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "█"*60)
    print("  ACM STRESS TEST — National Space Hackathon 2026")
    print("█"*60)

    objects, sat_states = build_telemetry(n_sats=50, n_debris=500, n_collisions=10)

    test_health()
    test_telemetry(objects)
    test_maneuver_schedule(sat_states)   # ← BEFORE sim steps (sats at initial positions)
    test_simulate_steps(n_steps=10, step_s=60)
    test_snapshot()
    test_active_maneuvers()
    test_fuel()
    test_events()

    print("\n" + "█"*60)
    print("  STRESS TEST COMPLETE")
    print("█"*60 + "\n")


if __name__ == "__main__":
    main()