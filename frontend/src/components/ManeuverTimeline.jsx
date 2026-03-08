/*
  Maneuver Timeline — Gantt-style
  Shows burn windows, cooldowns, and scheduled recoveries per satellite
*/

const COOLDOWN_S = 600

function TimelineRow({ sat, maneuvers, simTime }) {
  const satManeuvers = maneuvers.filter(m => m.satellite === sat.id)

  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 28, gap: 8, marginBottom: 4 }}>
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
        flex: 1, height: 18,
        background: '#071018',
        border: '1px solid #0d2035',
        borderRadius: 1,
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Current time indicator */}
        <div style={{
          position: 'absolute',
          left: '0%',
          top: 0, bottom: 0,
          width: 1,
          background: '#00ff8888',
          zIndex: 3,
        }} />

        {satManeuvers.map((m, i) => {
          if (m.status !== 'MANEUVER_PLANNED') return null

          // Evasion block — at current time (left edge)
          const evasionW = 8
          // Recovery block — after cooldown
          const recoveryOffset = ((COOLDOWN_S + 60) / 3600) * 100
          const recoveryW = 8

          return (
            <div key={i}>
              {/* Evasion burn */}
              <div style={{
                position: 'absolute',
                left: '1%', top: 2,
                width: `${evasionW}%`, height: 14,
                background: 'rgba(255,170,0,0.7)',
                borderRadius: 1,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: '0.5rem', color: '#000', fontFamily: 'VT323' }}>BURN</span>
              </div>

              {/* Cooldown bar */}
              <div style={{
                position: 'absolute',
                left: `${1 + evasionW}%`, top: 2,
                width: `${recoveryOffset - evasionW - 1}%`, height: 14,
                background: 'repeating-linear-gradient(90deg, #0d2035 0px, #0d2035 4px, transparent 4px, transparent 8px)',
                borderTop: '1px solid #1a3a25',
                borderBottom: '1px solid #1a3a25',
              }} />

              {/* Recovery burn */}
              <div style={{
                position: 'absolute',
                left: `${1 + recoveryOffset}%`, top: 2,
                width: `${recoveryW}%`, height: 14,
                background: 'rgba(0,170,255,0.7)',
                borderRadius: 1,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: '0.5rem', color: '#000', fontFamily: 'VT323' }}>REC</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Status badge */}
      <div className={`badge badge-${sat.status?.toLowerCase() === 'nominal' ? 'nominal' : sat.status?.toLowerCase() === 'evading' ? 'evading' : sat.status?.toLowerCase() === 'eol' ? 'eol' : 'critical'}`}
        style={{ flexShrink: 0, fontSize: '0.6rem' }}>
        {sat.status || 'NOMINAL'}
      </div>
    </div>
  )
}

export default function ManeuverTimeline({ satellites, maneuvers, simTime }) {
  if (!satellites || satellites.length === 0) {
    return (
      <div style={{ padding: 12, color: '#3a6a4a', fontFamily: 'VT323', fontSize: '1rem' }}>
        NO SATELLITES TRACKED
      </div>
    )
  }

  return (
    <div style={{ padding: '8px 12px', height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, fontSize: '0.6rem', color: '#3a6a4a' }}>
        <div style={{ width: 80 }}>SAT</div>
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between' }}>
          <span>NOW</span>
          <span style={{ color: 'rgba(255,170,0,0.7)' }}>▬ BURN</span>
          <span style={{ color: '#0d2035' }}>▬▬ COOLDOWN</span>
          <span style={{ color: 'rgba(0,170,255,0.7)' }}>▬ RECOVERY</span>
          <span>+1HR</span>
        </div>
      </div>

      {/* Rows */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {satellites.map(sat => (
          <TimelineRow
            key={sat.id}
            sat={sat}
            maneuvers={maneuvers}
            simTime={simTime}
          />
        ))}
      </div>

      {/* Legend */}
      <div style={{
        borderTop: '1px solid #0d2035',
        paddingTop: 6,
        fontSize: '0.6rem',
        color: '#3a6a4a',
        fontFamily: 'Share Tech Mono',
      }}>
        SIM T+{Math.floor(simTime / 60)}m &nbsp;|&nbsp; {maneuvers.length} maneuver(s) scheduled
      </div>
    </div>
  )
}