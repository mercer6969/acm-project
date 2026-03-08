import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const INITIAL_FUEL = 50.0  // kg

function FuelBar({ sat }) {
  const pct     = Math.max(0, (sat.fuel_kg / INITIAL_FUEL) * 100)
  const color   = pct > 30 ? '#00ff88' : pct > 10 ? '#ffaa00' : '#ff3333'
  const isLow   = pct <= 10

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: '0.7rem', color: '#a8d8b0', letterSpacing: '0.05em' }}>
          {sat.id}
        </span>
        <span style={{ fontSize: '0.7rem', color, fontFamily: 'VT323', fontSize: '0.9rem' }}>
          {sat.fuel_kg?.toFixed(2)} kg
          {isLow && <span style={{ color: '#ff3333', marginLeft: 6 }} className="blink">⚠ LOW</span>}
        </span>
      </div>
      <div style={{
        height: 6,
        background: '#0b1825',
        border: '1px solid #0d2035',
        borderRadius: 1,
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: color,
          boxShadow: `0 0 6px ${color}88`,
          transition: 'width 0.4s ease',
        }} />
      </div>
    </div>
  )
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#040a0f',
      border: '1px solid #0d3020',
      padding: '4px 8px',
      fontFamily: 'Share Tech Mono',
      fontSize: '0.7rem',
      color: '#00ff88',
    }}>
      <div>{payload[0]?.payload?.id}</div>
      <div>Fuel: {payload[0]?.value?.toFixed(2)} kg</div>
    </div>
  )
}

export default function FuelGauges({ satellites }) {
  if (!satellites || satellites.length === 0) {
    return (
      <div style={{ padding: 12, color: '#3a6a4a', fontFamily: 'VT323', fontSize: '1rem' }}>
        AWAITING TELEMETRY...
      </div>
    )
  }

  const chartData = satellites.map(s => ({
    id: s.id.replace('SAT-', 'S-'),
    fuel: s.fuel_kg,
  }))

  return (
    <div style={{ padding: '8px 12px', height: '100%', display: 'flex', flexDirection: 'column', gap: 8 }}>

      {/* Individual fuel bars */}
      <div style={{ flex: 1, overflowY: 'auto', paddingRight: 4 }}>
        {satellites.map(sat => <FuelBar key={sat.id} sat={sat} />)}
      </div>

      {/* Fleet bar chart */}
      <div style={{ height: 80, borderTop: '1px solid #0d2035', paddingTop: 8 }}>
        <div style={{ fontSize: '0.65rem', color: '#3a6a4a', marginBottom: 4, letterSpacing: '0.1em' }}>
          FLEET FUEL OVERVIEW
        </div>
        <ResponsiveContainer width="100%" height={60}>
          <BarChart data={chartData} barSize={8}>
            <XAxis dataKey="id" tick={{ fill: '#3a6a4a', fontSize: 8, fontFamily: 'Share Tech Mono' }} axisLine={false} tickLine={false} />
            <YAxis hide domain={[0, 50]} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,255,136,0.05)' }} />
            <Bar dataKey="fuel" radius={[1,1,0,0]}>
              {chartData.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.fuel > 15 ? '#00ff88' : entry.fuel > 5 ? '#ffaa00' : '#ff3333'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}