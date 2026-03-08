/*
  Maneuver Timeline — Gantt-style
  ─────────────────────────────────
  Shows real burn and recovery blocks from active maneuvers.
  Each satellite gets a row with:
    - Orange block  = evasion/scheduled burn
    - Striped block = cooldown (600s)
    - Blue block    = recovery burn
*/

const COOLDOWN_S  = 600
const HORIZON_S   = 3600   // show 1 hour of timeline

function TimelineRow({ sat, maneuvers, simTime }) {
  const satBurns = maneuvers.filter(m => m.satellite === sat.id)

  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 32, gap: 8, marginBottom: 6 }}>

      {/* Sat label */}
      <div style={{
        width: 80, flexShrink: 0,
        fontSize: '0.65rem', color: '#a8d8b0',
        fontFamily: 'Share Tech Mono',
        textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap',
      }}>
        {sat.id}
      </div>

      {/* Timeline track */}
      <div style={{
        flex: 1, height: 22,
        background: '#040e0a',
        border: '1px solid #0d2035',
        borderRadius: 1,
        position: 'relative',
        overflow: 'hidden',
      }}>

        {/* Time grid lines every 15 min */}
        {[0.25, 0.5, 0.75].map(pct => (
          <div key={pct} style={{
            position: 'absolute',
            left: `${pct * 100}%`,
            top: 0, bottom: 0,
            width: 1,
            background: 'rgba(0,255,136,0.06)',
          }} />
        ))}

        {/* Current time indicator */}
        <div style={{
          position: 'absolute',
          left: 0, top: 0, bottom: 0,
          width: 2,
          background: 'rgba(0,255,136,0.5)',
          zIndex: 4,
        }} />

        {/* Render each burn + its cooldown + recovery */}
        {satBurns.map((burn, i) => {
          const burnStart  = burn.execute_at - simTime
          const startPct   = Math.max(0, (burnStart / HORIZON_S) * 100)
          const burnWidthPct = (30 / HORIZON_S) * 100          // 30s burn visual width
          const cooldownPct  = (COOLDOWN_S / HORIZON_S) * 100
          const recStartPct  = startPct + burnWidthPct + cooldownPct

          const isRecovery = burn.type === 'RECOVERY'
          const isEvasion  = !isRecovery

          // Skip if burn is in the past or beyond horizon
          if (startPct > 100) return null

          return (
            <g key={burn.burn_id || i}>

              {/* ── Evasion / Scheduled burn block ─── */}
              {isEvasion && (
                <>
                  <div
                    title={`${burn.burn_id} — EVASION BURN`}
                    style={{
                      position: 'absolute',
                      left: `${startPct}%`,
                      top: 2,
                      width: `${burnWidthPct}%`,
                      minWidth: 8,
                      height: 18,
                      background: 'rgba(255,170,0,0.85)',
                      borderRadius: 2,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      zIndex: 3,
                      cursor: 'default',
                    }}
                  >
                    <span style={{ fontSize: '0.5rem', color: '#000', fontFamily: 'VT323', letterSpacing: '0.05em' }}>
                      BURN
                    </span>
                  </div>

                  {/* Cooldown stripe */}
                  <div style={{
                    position: 'absolute',
                    left: `${startPct + burnWidthPct}%`,
                    top: 2,
                    width: `${cooldownPct}%`,
                    height: 18,
                    background: 'repeating-linear-gradient(90deg, rgba(13,32,53,0.8) 0px, rgba(13,32,53,0.8) 3px, rgba(255,170,0,0.08) 3px, rgba(255,170,0,0.08) 6px)',
                    borderTop: '1px solid rgba(255,170,0,0.2)',
                    borderBottom: '1px solid rgba(255,170,0,0.2)',
                    zIndex: 2,
                    display: 'flex', alignItems: 'center', paddingLeft: 4,
                  }}>
                    <span style={{ fontSize: '0.45rem', color: 'rgba(255,170,0,0.4)', fontFamily: 'VT323' }}>
                      COOLDOWN 600s
                    </span>
                  </div>

                  {/* Recovery burn block */}
                  {recStartPct < 100 && (
                    <div
                      title={`Recovery burn for ${burn.burn_id}`}
                      style={{
                        position: 'absolute',
                        left: `${recStartPct}%`,
                        top: 2,
                        width: `${burnWidthPct}%`,
                        minWidth: 8,
                        height: 18,
                        background: 'rgba(0,170,255,0.85)',
                        borderRadius: 2,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        zIndex: 3,
                        cursor: 'default',
                      }}
                    >
                      <span style={{ fontSize: '0.5rem', color: '#000', fontFamily: 'VT323', letterSpacing: '0.05em' }}>
                        REC
                      </span>
                    </div>
                  )}
                </>
              )}

              {/* ── Standalone recovery burn (from scheduled_burns) ─── */}
              {isRecovery && (
                <div
                  title={`${burn.burn_id} — RECOVERY BURN`}
                  style={{
                    position: 'absolute',
                    left: `${startPct}%`,
                    top: 2,
                    width: `${burnWidthPct}%`,
                    minWidth: 8,
                    height: 18,
                    background: 'rgba(0,170,255,0.85)',
                    borderRadius: 2,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    zIndex: 3,
                  }}
                >
                  <span style={{ fontSize: '0.5rem', color: '#000', fontFamily: 'VT323' }}>
                    REC
                  </span>
                </div>
              )}

            </g>
          )
        })}

        {/* Empty row message */}
        {satBurns.length === 0 && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', paddingLeft: 8,
          }}>
            <span style={{ fontSize: '0.55rem', color: '#1a3a25', fontFamily: 'Share Tech Mono' }}>
              NO BURNS SCHEDULED
            </span>
          </div>
        )}
      </div>

      {/* Status badge */}
      <div className={`badge badge-${
        sat.status?.toLowerCase() === 'nominal'  ? 'nominal'  :
        sat.status?.toLowerCase() === 'evading'  ? 'evading'  :
        sat.status?.toLowerCase() === 'eol'      ? 'eol'      : 'critical'
      }`} style={{ flexShrink: 0, fontSize: '0.55rem', minWidth: 52, textAlign: 'center' }}>
        {sat.status || 'NOMINAL'}
      </div>

    </div>
  )
}

export default function ManeuverTimeline({ satellites, maneuvers, simTime }) {

  const activeSats = satellites?.filter(s =>
    maneuvers.some(m => m.satellite === s.id) || s.status !== 'NOMINAL'
  ) ?? []

  const allSats = satellites ?? []

  return (
    <div style={{ padding: '6px 12px', height: '100%', display: 'flex', flexDirection: 'column', gap: 4 }}>

      {/* Column headers */}
      <div style={{ display: 'flex', gap: 8, fontSize: '0.55rem', color: '#1a4a2a', fontFamily: 'Share Tech Mono' }}>
        <div style={{ width: 80 }}>SAT</div>
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', paddingRight: 60 }}>
          <span style={{ color: 'rgba(0,255,136,0.4)' }}>▌NOW</span>
          <span>+15m</span>
          <span>+30m</span>
          <span>+45m</span>
          <span>+60m</span>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, fontSize: '0.55rem', fontFamily: 'Share Tech Mono', marginBottom: 2 }}>
        <span><span style={{ color: '#ffaa00' }}>▬</span> EVASION BURN</span>
        <span><span style={{ color: 'rgba(255,170,0,0.3)' }}>▬</span> COOLDOWN</span>
        <span><span style={{ color: '#00aaff' }}>▬</span> RECOVERY BURN</span>
      </div>

      {/* Satellite rows — show active ones first, then the rest */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {allSats.length === 0 && (
          <div style={{ color: '#1a3a25', fontFamily: 'VT323', fontSize: '1rem', padding: 8 }}>
            NO SATELLITES TRACKED
          </div>
        )}
        {/* Active satellites first */}
        {activeSats.map(sat => (
          <TimelineRow key={sat.id} sat={sat} maneuvers={maneuvers} simTime={simTime} />
        ))}
        {/* Remaining nominal satellites */}
        {allSats
          .filter(s => !activeSats.find(a => a.id === s.id))
          .map(sat => (
            <TimelineRow key={sat.id} sat={sat} maneuvers={maneuvers} simTime={simTime} />
          ))
        }
      </div>

      {/* Footer */}
      <div style={{
        borderTop: '1px solid #0d2035', paddingTop: 4,
        fontSize: '0.55rem', color: '#3a6a4a', fontFamily: 'Share Tech Mono',
        display: 'flex', justifyContent: 'space-between',
      }}>
        <span>SIM T+{Math.floor(simTime / 60)}m {simTime % 60}s</span>
        <span>
          <span style={{ color: '#ffaa00' }}>{maneuvers.filter(m => m.type !== 'RECOVERY').length}</span> evasion
          &nbsp;|&nbsp;
          <span style={{ color: '#00aaff' }}>{maneuvers.filter(m => m.type === 'RECOVERY').length}</span> recovery
        </span>
      </div>

    </div>
  )
}