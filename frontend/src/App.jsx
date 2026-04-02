import { useState, useEffect, useCallback, useRef } from 'react'
import Globe3D from './components/Globe3D'
import BullseyePlot from './components/BullseyePlot'
import FuelGauges from './components/FuelGauges'
import ManeuverTimeline from './components/ManeuverTimeline'

const API = ''  // proxied via vite → localhost:8000
const POLL_MS = 2000

// Snapshot filter config — tune to trade visibility vs bandwidth
const SNAP_BAND         = 'leo'
const SNAP_PROXIMITY_KM = 500

// Helper: convert Unix timestamp to Greenwich Sidereal Time (radians)
function unixToGast(unixSeconds) {
  // J2000.0 = 946728000 seconds Unix
  const J2000 = 946728000.0
  const days = (unixSeconds - J2000) / 86400.0
  // GMST in degrees
  let gmst = 280.46061837 + 360.98564736629 * days
  gmst = ((gmst % 360) + 360) % 360
  return gmst * Math.PI / 180
}

export default function App() {
  const [snapshot, setSnapshot]       = useState(null)
  const [warnings, setWarnings]       = useState([])
  const [maneuvers, setManeuvers]     = useState([])
  const [selectedSat, setSelectedSat] = useState(null)
  const [simTime, setSimTime]         = useState(0)
  const [connected, setConnected]     = useState(false)
  const [stepLog, setStepLog]         = useState([])
  const [earthRotationY, setEarthRotationY] = useState(0)
  const [rotateEnabled, setRotateEnabled] = useState(true)  // NEW: play/pause
  const pollRef = useRef(null)

  const [snapMeta, setSnapMeta] = useState({ total: 0, shown: 0 })

  // ── Poll snapshot + active maneuvers ──────────────────────────────────────
  const fetchSnapshot = useCallback(async () => {
    try {
      const snapUrl = `${API}/api/visualization/snapshot?band=${SNAP_BAND}&proximity_km=${SNAP_PROXIMITY_KM}`

      const [snapRes, manRes] = await Promise.all([
        fetch(snapUrl),
        fetch(`${API}/api/maneuvers/active`),
      ])

      if (!snapRes.ok) throw new Error(snapRes.status)

      const snapData = await snapRes.json()
      setSnapshot(snapData)
      setSimTime(snapData.sim_time_s ?? 0)
      setConnected(true)
      setSnapMeta({
        total: snapData.debris_total ?? snapData.debris_cloud?.length ?? 0,
        shown: snapData.debris_shown ?? snapData.debris_cloud?.length ?? 0,
      })

      // Update Earth rotation based on simulation timestamp (snap to correct orientation)
      if (snapData.unix_timestamp) {
        const gast = unixToGast(snapData.unix_timestamp)
        setEarthRotationY(gast)
      } else if (snapData.sim_time_s !== undefined) {
        // Fallback: assume start epoch J2000
        const unixEstimate = 946728000 + snapData.sim_time_s
        const gast = unixToGast(unixEstimate)
        setEarthRotationY(gast)
      }

      if (manRes.ok) {
        const manData = await manRes.json()
        setManeuvers(manData.maneuvers ?? [])
      }

      if (!selectedSat && snapData.satellites?.length > 0) {
        setSelectedSat(snapData.satellites[0])
      }
    } catch {
      setConnected(false)
    }
  }, [selectedSat])

  useEffect(() => {
    fetchSnapshot()
    pollRef.current = setInterval(fetchSnapshot, POLL_MS)
    return () => clearInterval(pollRef.current)
  }, [fetchSnapshot])

  // ── Advance simulation by 60s ──────────────────────────────────────────────
  const stepSim = async () => {
    try {
      const res  = await fetch(`${API}/api/simulate/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_seconds: 60 }),
      })
      const data = await res.json()

      setStepLog(prev => [{
        t: data.new_timestamp ?? 0,
        collisions: data.collisions_detected,
        maneuvers: data.maneuvers_executed,
      }, ...prev].slice(0, 8))

      if (data.warnings != null) {
        setWarnings(data.warnings)
      }

      if (data.maneuvers?.length > 0) {
        setManeuvers(prev => {
          const existing = new Set(prev.map(m => m.burn_id))
          const newOnes  = data.maneuvers.filter(m => !existing.has(m.burn_id))
          return [...newOnes, ...prev].slice(0, 50)
        })
      }

      fetchSnapshot()  // this will recalc earthRotationY based on new sim time
    } catch (e) {
      console.error('Step failed', e)
    }
  }

  const sats        = snapshot?.satellites ?? []
  const debrisCloud = snapshot?.debris_cloud ?? []

  return (
    <div style={{
      width: '100vw', height: '100vh',
      display: 'grid',
      gridTemplateColumns: '220px 1fr 220px',
      gridTemplateRows: '44px 1fr 180px',
      gap: 2,
      background: '#02080d',
      padding: 4,
    }}>

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <div style={{
        gridColumn: '1 / -1',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 12px',
        borderBottom: '1px solid #0d3020',
        background: '#040a0f',
      }}>
        <div style={{ fontFamily: 'VT323', fontSize: '1.5rem', color: '#00ff88', letterSpacing: '0.2em' }}>
          ◈ ORBITAL INSIGHT — ACM v1.0
          <span className="blink" style={{ marginLeft: 8, fontSize: '1rem' }}>_</span>
        </div>

        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.7rem', fontFamily: 'Share Tech Mono' }}>
            <div style={{
              width: 7, height: 7, borderRadius: '50%',
              background: connected ? '#00ff88' : '#ff3333',
              boxShadow: connected ? '0 0 6px #00ff88' : '0 0 6px #ff3333',
            }} />
            <span style={{ color: connected ? '#00ff88' : '#ff3333' }}>
              {connected ? 'BACKEND LIVE' : 'OFFLINE'}
            </span>
          </div>

          <div style={{ fontSize: '0.7rem', color: '#3a6a4a', fontFamily: 'Share Tech Mono' }}>
            SATS: <span style={{ color: '#00ff88' }}>{sats.length}</span>
            &nbsp;|&nbsp;
            DEBRIS: <span style={{ color: '#ff3333' }}>{debrisCloud.length}</span>
            {snapMeta.total > snapMeta.shown && (
              <span style={{ color: '#3a6a4a' }}>/{snapMeta.total}</span>
            )}
            &nbsp;|&nbsp;
            BURNS: <span style={{ color: '#ffaa00' }}>{maneuvers.length}</span>
            &nbsp;|&nbsp;
            T+<span style={{ color: '#ffaa00' }}>{Math.floor(simTime / 60)}m</span>
          </div>

          {/* NEW: Rotation toggle button */}
          <button
            onClick={() => setRotateEnabled(v => !v)}
            style={{
              fontFamily: 'VT323', fontSize: '1rem',
              background: 'transparent',
              border: `1px solid ${rotateEnabled ? '#00ff88' : '#ffaa00'}`,
              color: rotateEnabled ? '#00ff88' : '#ffaa00',
              padding: '2px 14px',
              cursor: 'pointer',
              letterSpacing: '0.1em',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.target.style.background = rotateEnabled ? 'rgba(0,255,136,0.1)' : 'rgba(255,170,0,0.1)'}
            onMouseLeave={e => e.target.style.background = 'transparent'}
          >
            {rotateEnabled ? '⏸ ROTATION' : '▶ ROTATION'}
          </button>

          <button
            onClick={stepSim}
            style={{
              fontFamily: 'VT323', fontSize: '1rem',
              background: 'transparent',
              border: '1px solid #00ff88',
              color: '#00ff88',
              padding: '2px 14px',
              cursor: 'pointer',
              letterSpacing: '0.1em',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.target.style.background = 'rgba(0,255,136,0.1)'}
            onMouseLeave={e => e.target.style.background = 'transparent'}
          >
            ▶ STEP +60s
          </button>
        </div>
      </div>

      {/* ── Left panel: satellite list ───────────────────────────────────────── */}
      <div className="panel" style={{ overflowY: 'auto' }}>
        <div className="panel-title">CONSTELLATION</div>
        <div style={{ padding: '6px 8px' }}>
          {sats.length === 0 && (
            <div style={{ color: '#3a6a4a', fontFamily: 'VT323', fontSize: '0.9rem', padding: 8 }}>
              NO SATELLITES<br />POST TELEMETRY
            </div>
          )}
          {sats.map(sat => {
            const isSelected = selectedSat?.id === sat.id
            const hasWarning = warnings.some(w => w.satellite === sat.id)
            const hasBurn    = maneuvers.some(m => m.satellite === sat.id)
            return (
              <div
                key={sat.id}
                onClick={() => setSelectedSat(sat)}
                style={{
                  padding: '6px 8px', marginBottom: 3, cursor: 'pointer',
                  background: isSelected ? 'rgba(0,255,136,0.07)' : 'transparent',
                  border: isSelected ? '1px solid #0d3020' : '1px solid transparent',
                  borderRadius: 1, transition: 'all 0.15s',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: 'Share Tech Mono', fontSize: '0.72rem', color: isSelected ? '#00ff88' : '#a8d8b0' }}>
                    {hasWarning && <span style={{ color: '#ff3333' }}>⚠ </span>}
                    {hasBurn && !hasWarning && <span style={{ color: '#ffaa00' }}>🔥 </span>}
                    {sat.id}
                  </span>
                  <span className={`badge badge-${
                    sat.status?.toLowerCase() === 'nominal' ? 'nominal' :
                    sat.status?.toLowerCase() === 'evading' ? 'evading' :
                    sat.status?.toLowerCase() === 'eol'     ? 'eol'     : 'critical'
                  }`} style={{ fontSize: '0.55rem' }}>
                    {sat.status}
                  </span>
                </div>
                <div style={{ fontSize: '0.6rem', color: '#3a6a4a', marginTop: 2 }}>
                  {sat.lat?.toFixed(2)}° {sat.lon?.toFixed(2)}°
                  &nbsp;|&nbsp;
                  <span style={{ color: sat.fuel_kg < 5 ? '#ff3333' : sat.fuel_kg < 15 ? '#ffaa00' : '#3a6a4a' }}>
                    ⛽{sat.fuel_kg?.toFixed(1)}kg
                  </span>
                  {hasBurn && (
                    <span style={{ color: '#ffaa00', marginLeft: 4 }}>
                      · {maneuvers.filter(m => m.satellite === sat.id).length} burn(s)
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Event log */}
        <div className="panel-title" style={{ marginTop: 8 }}>EVENT LOG</div>
        <div style={{ padding: '4px 8px', fontFamily: 'Share Tech Mono', fontSize: '0.6rem', color: '#3a6a4a' }}>
          {stepLog.length === 0 && <div style={{ color: '#1a3a25' }}>AWAITING STEPS...</div>}
          {stepLog.map((log, i) => (
            <div key={i} style={{ marginBottom: 4, borderLeft: '2px solid #0d2035', paddingLeft: 6 }}>
              <div style={{ color: log.collisions > 0 ? '#ff3333' : '#00ff88' }}>
                {log.collisions > 0 ? `⚠ ${log.collisions} COLLISION` : '✓ CLEAR'}
                {log.maneuvers > 0 && (
                  <span style={{ color: '#ffaa00', marginLeft: 6 }}>· {log.maneuvers} burn(s)</span>
                )}
              </div>
              <div style={{ color: '#1a4a2a' }}>T+{Math.floor((log.t ?? 0) / 60)}m</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Centre: 3D Globe ─────────────────────────────────────────────────── */}
      <div className="panel" style={{ position: 'relative' }}>
        <Globe3D
          satellites={sats}
          debrisCloud={debrisCloud}
          selectedSat={selectedSat}
          earthRotationY={earthRotationY}
          rotateEnabled={rotateEnabled}
        />
        <div style={{
          position: 'absolute', top: 8, left: 8,
          fontFamily: 'VT323', fontSize: '0.85rem', color: 'rgba(0,255,136,0.4)',
          pointerEvents: 'none',
        }}>
          ECI / J2000 &nbsp;|&nbsp; DRAG TO ROTATE &nbsp;|&nbsp; SCROLL TO ZOOM
        </div>
        <div style={{
          position: 'absolute', bottom: 8, right: 8,
          fontFamily: 'VT323', fontSize: '0.85rem', color: 'rgba(0,255,136,0.3)',
          pointerEvents: 'none',
        }}>
          🟢 SAT &nbsp; 🔴 DEBRIS
        </div>
      </div>

      {/* ── Right panel: Bullseye ─────────────────────────────────────────────── */}
      <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="panel-title">CONJUNCTION PLOT</div>
        <div style={{ flex: 1 }}>
          <BullseyePlot warnings={warnings} selectedSat={selectedSat} />
        </div>
        {selectedSat && (
          <div style={{
            padding: '4px 10px', borderTop: '1px solid #0d2035',
            fontSize: '0.6rem', color: '#3a6a4a', fontFamily: 'Share Tech Mono',
          }}>
            THREATS: <span style={{ color: warnings.filter(w => w.satellite === selectedSat?.id).length > 0 ? '#ff3333' : '#00ff88' }}>
              {warnings.filter(w => w.satellite === selectedSat?.id).length}
            </span>
            &nbsp;|&nbsp;
            BURNS QUEUED: <span style={{ color: '#ffaa00' }}>
              {maneuvers.filter(m => m.satellite === selectedSat?.id).length}
            </span>
          </div>
        )}
      </div>

      {/* ── Bottom left: Fuel gauges ─────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-title">FUEL & RESOURCES</div>
        <div style={{ height: 'calc(100% - 32px)' }}>
          <FuelGauges satellites={sats} />
        </div>
      </div>

      {/* ── Bottom centre + right: Gantt timeline ────────────────────────────── */}
      <div className="panel" style={{ gridColumn: '2 / -1' }}>
        <div className="panel-title">
          MANEUVER TIMELINE
          {maneuvers.length > 0 && (
            <span style={{ fontSize: '0.7rem', color: '#ffaa00', marginLeft: 8 }}>
              {maneuvers.length} ACTIVE
            </span>
          )}
        </div>
        <div style={{ height: 'calc(100% - 32px)' }}>
          <ManeuverTimeline
            satellites={sats}
            maneuvers={maneuvers}
            simTime={simTime}
          />
        </div>
      </div>

    </div>
  )
}