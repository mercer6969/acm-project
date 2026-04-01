"""
app/stress_test.py
──────────────────
ACM Stress Test — National Space Hackathon 2026
Run from project root: python app/stress_test.py

Changes from previous version:
  - Collision scenario: debris placed at 0.05 km (50m) directly ahead — inside
    the 100m threshold — so simulate/step MUST detect and avoid them.
  - New Test 5: COLLISION DETECTION — verifies collisions_detected > 0 on first
    tick, then drops to 0 after evasion maneuvers fire.
  - New Test 6: EVASION EFFECTIVENESS — checks satellites that were on collision
    course are no longer CRITICAL after maneuvers.
  - Existing tests renumbered, snapshot/active/fuel/events shifted down.
  - Added per-satellite fuel drain report after collision scenario.
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
    print(f"\n{'='*62}")
    print(f"  {title}")
    print(f"{'='*62}")


def print_ok(msg):   print(f"  ✅  {msg}")
def print_warn(msg): print(f"  ⚠️   {msg}")
def print_err(msg):  print(f"  ❌  {msg}")


# ── Orbit helpers ─────────────────────────────────────────────────────────────

MU = 398600.4418
RE = 6378.137


def circ_velocity(r_km):
    return math.sqrt(MU / r_km)


def orbit_position(alt_km, angle_deg, inc_deg=0.0):
    r = RE + alt_km
    a = math.radians(angle_deg)
    i = math.radians(inc_deg)
    return (
        r * math.cos(a),
        r * math.sin(a) * math.cos(i),
        r * math.sin(a) * math.sin(i),
    )


def orbit_velocity(alt_km, angle_deg, inc_deg=0.0):
    r  = RE + alt_km
    v  = circ_velocity(r)
    a  = math.radians(angle_deg)
    i  = math.radians(inc_deg)
    return (
        -v * math.sin(a),
         v * math.cos(a) * math.cos(i),
         v * math.cos(a) * math.sin(i),
    )


# ── Telemetry builders ────────────────────────────────────────────────────────

def build_nominal_telemetry(n_sats=50, n_safe_debris=480):
    """
    50 satellites + 480 safe debris (well clear of all satellites).
    No collision-course objects — used as the clean baseline.
    """
    objects    = []
    sat_states = []
    alts = [400, 450, 500, 550, 600]
    incs = [0, 28, 45, 53, 97]

    for i in range(n_sats):
        alt   = alts[i % len(alts)]
        inc   = incs[i % len(incs)]
        angle = (i / n_sats) * 360.0
        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)
        sid = f"SAT-{i+1:03d}"
        objects.append({
            "id": sid, "type": "SATELLITE",
            "r": {"x": round(x,  3), "y": round(y,  3), "z": round(z,  3)},
            "v": {"x": round(vx, 6), "y": round(vy, 6), "z": round(vz, 6)},
        })
        sat_states.append((sid, x, y, z, vx, vy, vz))

    for i in range(n_safe_debris):
        alt   = random.uniform(380, 650)
        angle = random.uniform(0, 360)
        inc   = random.uniform(0, 97)
        x, y, z    = orbit_position(alt, angle, inc)
        vx, vy, vz = orbit_velocity(alt, angle, inc)
        # Offset by 5–50 km so they are safely clear
        x += random.uniform(5, 50)
        y += random.uniform(5, 50)
        z += random.uniform(2, 20)
        objects.append({
            "id": f"DEB-{i+1:04d}", "type": "DEBRIS",
            "r": {"x": round(x,  3), "y": round(y,  3), "z": round(z,  3)},
            "v": {"x": round(vx, 6), "y": round(vy, 6), "z": round(vz, 6)},
        })

    return objects, sat_states


def build_collision_telemetry(sat_states, n_collisions=10):
    """
    Inject n_collisions pieces of debris placed at exactly 0.05 km (50 m)
    directly in front of randomly chosen satellites — well inside the 100 m
    collision threshold.  Each debris piece has the SAME velocity as its
    target satellite so relative velocity is ~0 and miss distance stays ≤ 50 m
    unless the ACM fires an evasion burn.

    Returns:
        list of debris objects to POST to /api/telemetry
        list of (debris_id, sat_id) collision pairs for verification
    """
    collision_pairs = []
    debris_objects  = []

    targets = random.sample(sat_states, min(n_collisions, len(sat_states)))

    for idx, (sid, sx, sy, sz, svx, svy, svz) in enumerate(targets):
        speed = math.sqrt(svx**2 + svy**2 + svz**2)
        if speed < 1e-9:
            continue
        ux, uy, uz = svx / speed, svy / speed, svz / speed

        # Place debris 50 m (0.050 km) directly ahead in velocity direction
        deb_id = f"DEB-CRIT-{idx+1:03d}"
        debris_objects.append({
            "id":   deb_id,
            "type": "DEBRIS",
            "r": {
                "x": round(sx + ux * 0.050, 5),
                "y": round(sy + uy * 0.050, 5),
                "z": round(sz + uz * 0.050, 5),
            },
            # Same velocity → persistent close approach
            "v": {"x": round(svx, 6), "y": round(svy, 6), "z": round(svz, 6)},
        })
        collision_pairs.append((deb_id, sid))

    return debris_objects, collision_pairs


# ── Find visible satellite ────────────────────────────────────────────────────

def _find_visible_satellite(sat_states):
    best_id   = None
    best_elev = -999.0

    for (sid, sx, sy, sz, *_) in sat_states:
        try:
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

    print("  (no sat above 5° mask — scanning for closest-to-horizon)")
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


# ═════════════════════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_health():
    print_section("1. HEALTH CHECK")
    code, data = get("/")
    if code == 200 and "ACM Running" in str(data.get("status", "")):
        print_ok(f"Backend alive: {data}")
    else:
        print_err(f"Backend not responding! Code={code} Body={data}")
        exit(1)


def test_telemetry(objects):
    n_sats = sum(1 for o in objects if o["type"] == "SATELLITE")
    n_deb  = sum(1 for o in objects if o["type"] == "DEBRIS")
    print_section(f"2. TELEMETRY — BASELINE ({n_sats} sats, {n_deb} safe debris)")

    t0 = time.time()
    code, data = post("/api/telemetry", {
        "timestamp": "2026-03-12T08:00:00.000Z",
        "objects":   objects,
    })
    ms = (time.time() - t0) * 1000

    if code == 200 and data.get("status") == "ACK":
        print_ok(f"ACK — {len(objects)} objects ingested in {ms:.1f}ms")
        cdm = data.get("active_cdm_warnings", 0)
        print_ok(f"CDM warnings after baseline load: {cdm}")
        if cdm > 0:
            print_warn("Unexpected conjunctions in baseline — safe debris may be too close")
    else:
        print_err(f"Telemetry FAILED: code={code} body={data}")


def test_collision_injection(collision_debris, collision_pairs):
    """
    Inject collision-course debris and verify the ACM immediately flags CDMs.
    """
    print_section(
        f"3. COLLISION INJECTION — {len(collision_debris)} debris inside 100m threshold"
    )

    t0 = time.time()
    code, data = post("/api/telemetry", {
        "timestamp": "2026-03-12T08:00:01.000Z",
        "objects":   collision_debris,
    })
    ms = (time.time() - t0) * 1000

    if code != 200 or data.get("status") != "ACK":
        print_err(f"Collision debris injection FAILED: code={code} body={data}")
        return

    cdm = data.get("active_cdm_warnings", 0)
    print_ok(f"Injection ACK in {ms:.1f}ms — CDM warnings now: {cdm}")

    if cdm >= len(collision_pairs):
        print_ok(f"All {len(collision_pairs)} collision pairs flagged as CDMs ✓")
    elif cdm > 0:
        print_warn(
            f"Only {cdm}/{len(collision_pairs)} pairs flagged — "
            "conjunction pipeline may not be scanning new debris immediately"
        )
    else:
        print_err(
            "0 CDM warnings after injecting debris at 50m — "
            "conjunction assessment not running on telemetry ingestion"
        )

    print()
    print("  Collision pairs injected:")
    for deb_id, sat_id in collision_pairs:
        print(f"    · {deb_id}  →  {sat_id}")


def test_evasion_and_detection(collision_pairs, n_steps=5, step_s=30):
    """
    Run simulate/step and check:
      - Step 1: collisions_detected > 0 (ACM sees the threat)
      - Steps 2–5: collisions_detected drops toward 0 (evasion working)
      - fleet_metrics.uptime_pct stays reasonable
      - fleet_metrics.total_fuel_used_kg increases (burns fired)
    """
    print_section(
        f"4. EVASION & DETECTION — {n_steps} steps × {step_s}s "
        f"({n_steps*step_s}s simulated)"
    )

    total_collisions = 0
    total_maneuvers  = 0
    first_step_cols  = None
    last_uptime      = None
    last_fuel_used   = 0.0

    for i in range(n_steps):
        t0 = time.time()
        code, data = post("/api/simulate/step", {"step_seconds": step_s})
        ms = (time.time() - t0) * 1000

        if code != 200:
            print_err(f"Step {i+1} FAILED: code={code} body={data}")
            continue

        cols = data.get("collisions_detected", 0)
        mans = data.get("maneuvers_executed",  0)
        conj = data.get("conjunctions_active", 0)
        total_collisions += cols
        total_maneuvers  += mans

        fm   = data.get("fleet_metrics") or {}
        upt  = fm.get("uptime_pct",         "—")
        fuel = fm.get("total_fuel_used_kg",  0.0)
        opt  = fm.get("optimization_ratio",  "—")

        if first_step_cols is None:
            first_step_cols = cols
        last_uptime    = upt
        last_fuel_used = fuel

        icon = "🔴" if cols > 0 else "✅"
        print(
            f"  {icon} Step {i+1} | T+{(i+1)*step_s:3d}s | "
            f"{ms:6.1f}ms | collisions={cols} | "
            f"maneuvers={mans} | conj={conj} | "
            f"uptime={upt}% | fuel_used={fuel:.3f}kg | opt={opt}"
        )

    print()

    # Verdict: did the ACM detect on step 1?
    if first_step_cols is not None and first_step_cols > 0:
        print_ok(
            f"Step 1 detected {first_step_cols} collision(s) — "
            "ACM is scanning correctly"
        )
    else:
        print_err(
            "Step 1 detected 0 collisions even though debris is at 50m — "
            "check predict_conjunctions() threshold and CRITICAL severity logic"
        )

    # Did total maneuvers fire?
    if total_maneuvers > 0:
        print_ok(f"Evasion maneuvers fired: {total_maneuvers} total across {n_steps} steps")
    else:
        print_err(
            "0 maneuvers executed — plan_maneuver() may not be triggering, "
            "or all satellites are in cooldown / blackout"
        )

    # Did fuel actually get used?
    if last_fuel_used > 0:
        print_ok(f"Fleet fuel consumed: {last_fuel_used:.3f} kg (Tsiolkovsky tracking ✓)")
    else:
        print_warn("Fleet shows 0 fuel used — check fleet_metrics in simulate.py")

    # Uptime still reasonable?
    if isinstance(last_uptime, (int, float)) and last_uptime >= 50.0:
        print_ok(f"Fleet uptime after evasions: {last_uptime}%")
    elif isinstance(last_uptime, (int, float)):
        print_warn(
            f"Fleet uptime dropped to {last_uptime}% — "
            "recovery burns may not be returning sats to slot fast enough"
        )
    else:
        print_warn("fleet_metrics not present in step response — add it to simulate.py")


def test_collision_survival(n_steps=15, step_s=60):
    """
    Run a longer sim to verify evasion was durable — after ~15 min
    the injected debris should have drifted clear and collisions_detected = 0.
    """
    print_section(
        f"5. COLLISION SURVIVAL — {n_steps} steps × {step_s}s "
        f"({n_steps*step_s//60} min, verifying sustained 0-collision operation)"
    )

    sustained_clean = 0
    total_cols      = 0

    for i in range(n_steps):
        t0 = time.time()
        code, data = post("/api/simulate/step", {"step_seconds": step_s})
        ms = (time.time() - t0) * 1000

        if code != 200:
            print_err(f"Step {i+1} FAILED: code={code}")
            continue

        cols = data.get("collisions_detected", 0)
        mans = data.get("maneuvers_executed",  0)
        total_cols += cols

        fm   = data.get("fleet_metrics") or {}
        upt  = fm.get("uptime_pct", "—")
        fuel = fm.get("total_fuel_used_kg", "—")

        if cols == 0:
            sustained_clean += 1

        icon = "⚠️ " if cols > 0 else "✅"
        print(
            f"  {icon} Step {i+1:2d} | T+{(i+1)*step_s:5d}s | "
            f"{ms:6.1f}ms | cols={cols} | mans={mans} | "
            f"uptime={upt}% | fuel_used={fuel}kg"
        )

    print()
    if total_cols == 0:
        print_ok(f"PERFECT — 0 collisions across all {n_steps} survival steps")
    elif sustained_clean >= n_steps - 2:
        print_warn(
            f"{total_cols} collision event(s) but system recovered — "
            f"{sustained_clean}/{n_steps} steps clean"
        )
    else:
        print_err(
            f"{total_cols} collision events across {n_steps} steps — "
            "evasion not holding; check recovery burn timing"
        )


def test_maneuver_schedule(sat_states):
    print_section("6. MANEUVER SCHEDULE ENDPOINT")

    vis_id = _find_visible_satellite(sat_states)

    # Valid maneuver
    print(f"  Using {vis_id} for LOS-valid test")
    code, data = post("/api/maneuver/schedule", {
        "satelliteId": vis_id,
        "maneuver_sequence": [{
            "burn_id":       "STRESS_BURN_1",
            "burnTime":      "2026-03-12T14:00:00.000Z",
            "deltaV_vector": {"x": 0.002, "y": 0.010, "z": -0.001},
        }],
    })
    if data.get("status") == "SCHEDULED":
        print_ok(f"Valid maneuver accepted for {vis_id}")
    else:
        reason = data.get("reason", "unknown")
        los_ok = data.get("validation", {}).get("ground_station_los", "?")
        print_err(f"Valid maneuver rejected: {reason} | LOS={los_ok}")

    # Over-limit burn (|ΔV| = 17.3 m/s > 15 m/s limit)
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

    # Unknown satellite
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

    # Cooldown violation (two burns 30s apart — needs 600s gap)
    code4, data4 = post("/api/maneuver/schedule", {
        "satelliteId": vis_id,
        "maneuver_sequence": [
            {
                "burn_id":       "COOL_BURN_A",
                "burnTime":      "2026-03-12T18:00:00.000Z",
                "deltaV_vector": {"x": 0.001, "y": 0.001, "z": 0.0},
            },
            {
                "burn_id":       "COOL_BURN_B",
                "burnTime":      "2026-03-12T18:00:30.000Z",   # only 30s later
                "deltaV_vector": {"x": 0.001, "y": 0.001, "z": 0.0},
            },
        ],
    })
    if data4.get("status") == "REJECTED":
        print_ok(f"Cooldown violation correctly rejected: {data4.get('reason','')}")
    else:
        print_err(f"Cooldown violation NOT rejected: {data4}")


def test_snapshot():
    print_section("7. SNAPSHOT PERFORMANCE")
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
        print_ok(f"Snapshot: {n_sats} sats + {n_deb} debris objects")
    else:
        print_err("Snapshot returned empty or failed")

    print_ok(f"Avg response: {avg_ms:.1f}ms | Max: {max_ms:.1f}ms")
    if max_ms < 100:
        print_ok("EXCELLENT (<100ms)")
    elif max_ms < 500:
        print_warn(f"OK ({max_ms:.0f}ms)")
    else:
        print_err(f"SLOW ({max_ms:.0f}ms) — frontend will lag")


def test_active_maneuvers():
    print_section("8. ACTIVE MANEUVERS ENDPOINT")
    code, data = get("/api/maneuvers/active")
    if code == 200:
        burns = data if isinstance(data, list) else data.get("maneuvers", [])
        print_ok(f"Endpoint working — {len(burns)} burns queued")
        by_type = {}
        for b in burns:
            t = b.get("type", "UNKNOWN")
            by_type[t] = by_type.get(t, 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"     · {t}: {c}")
    else:
        print_err(f"Active maneuvers FAILED: code={code}")


def test_fuel(collision_pairs):
    print_section("9. FUEL DEPLETION — POST-EVASION AUDIT")
    code, snap = get("/api/visualization/snapshot")
    if code != 200:
        print_err("Could not fetch snapshot")
        return

    sats = snap.get("satellites", [])
    if not sats:
        print_warn("No satellites in snapshot")
        return

    # Satellites that were on collision course — check their fuel burned
    collision_sat_ids = {sid for _, sid in collision_pairs}
    collision_sats    = [s for s in sats if s["id"] in collision_sat_ids]
    burned_sats       = [s for s in collision_sats if s.get("fuel_kg", 50.0) < 49.9]

    evading  = [s for s in sats if s.get("status") == "EVADING"]
    eol_sats = [s for s in sats if s.get("status") == "EOL"]
    low_fuel = [s for s in sats if s.get("fuel_kg", 50.0) < 45.0]

    if burned_sats:
        print_ok(
            f"{len(burned_sats)}/{len(collision_sats)} collision-course sats "
            "show fuel burned (evasion confirmed)"
        )
        for s in burned_sats[:5]:
            burned = 50.0 - s.get("fuel_kg", 50.0)
            print(
                f"     · {s['id']} — {s.get('fuel_kg',0):.3f}kg remaining "
                f"({burned:.3f}kg burned) status={s.get('status','?')}"
            )
    else:
        print_warn(
            "No fuel change on collision-course satellites — "
            "evasion burns may not have fired yet (check cooldown / LOS)"
        )

    if evading:
        print_warn(f"Still evading: {len(evading)} sats")
    else:
        print_ok("No satellites stuck in EVADING state")

    if eol_sats:
        print_warn(f"EOL satellites (graveyard burn triggered): {len(eol_sats)}")
        for s in eol_sats[:3]:
            print(f"     · {s['id']} fuel={s.get('fuel_kg',0):.3f}kg")

    if low_fuel:
        print_warn(f"Low fuel (<45kg): {len(low_fuel)} sats")
    else:
        print_ok("Fuel levels healthy (all sats ≥ 45kg)")


def test_events():
    print_section("10. EVENT LOG")
    code, data = get("/api/simulate/events")
    if code != 200:
        code, data = get("/api/events")
    if code == 200:
        events = data.get("events", [])
        count  = data.get("count", len(events))
        print_ok(f"Event log working — {count} events recorded")
        types = {}
        for e in events:
            t = e.get("event", "UNKNOWN")
            types[t] = types.get(t, 0) + 1
        for t, c in sorted(types.items()):
            print(f"     · {t}: {c}")
        # Flag evasion events specifically
        evasion_count = sum(c for t, c in types.items() if "EVASION" in t or "MANEUVER" in t)
        if evasion_count > 0:
            print_ok(f"Evasion/maneuver events logged: {evasion_count}")
        else:
            print_warn("No evasion events in log — planner logging may be broken")
    else:
        print_err(f"Event log FAILED: code={code}")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "█"*62)
    print("  ACM STRESS TEST — National Space Hackathon 2026")
    print("  Collision-scenario edition")
    print("█"*62)

    # Build baseline (no collisions)
    nominal_objects, sat_states = build_nominal_telemetry(n_sats=50, n_safe_debris=480)

    # Build collision-course debris separately
    collision_debris, collision_pairs = build_collision_telemetry(
        sat_states, n_collisions=10
    )

    print(f"\n  Scenario: 50 sats | 480 safe debris | "
          f"{len(collision_pairs)} collision-course debris")
    print(f"  Collision debris placed at 0.050 km (50m) — inside 100m threshold")

    # ── Run tests ─────────────────────────────────────────────────────────────
    test_health()

    # Load baseline first so satellites exist before maneuver test
    test_telemetry(nominal_objects)

    # Maneuver schedule validation (satellites at known initial positions)
    test_maneuver_schedule(sat_states)

    # Inject collision-course debris — ACM should flag CDMs immediately
    test_collision_injection(collision_debris, collision_pairs)

    # Short burst of steps — verify detection and evasion fire
    test_evasion_and_detection(collision_pairs, n_steps=5, step_s=30)

    # Longer run — verify sustained clean operation after evasion
    test_collision_survival(n_steps=15, step_s=60)

    # Standard checks
    test_snapshot()
    test_active_maneuvers()
    test_fuel(collision_pairs)
    test_events()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "█"*62)
    print("  STRESS TEST COMPLETE")
    print("  What to check if failures above:")
    print("  · Test 3 CDM=0  → predict_conjunctions() not running on ingestion")
    print("  · Test 4 cols=0 → CRITICAL threshold or plan_maneuver() not firing")
    print("  · Test 4 mans=0 → LOS blocking all burns, or cooldown too aggressive")
    print("  · Test 5 cols>2 → recovery burns not returning sats to slot fast enough")
    print("  · Test 9 fuel=0 → fleet_metrics missing or fuel model not tracking")
    print("█"*62 + "\n")


if __name__ == "__main__":
    main()