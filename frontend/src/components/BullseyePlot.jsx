import { useEffect, useRef } from 'react'

/*
  Conjunction "Bullseye" Plot
  ─────────────────────────────
  Center = selected satellite
  Radial  = distance in km (0 at centre = collision)
  Colour  = severity (green / yellow / red)
*/
export default function BullseyePlot({ warnings, selectedSat }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width  = canvas.offsetWidth
    const H = canvas.height = canvas.offsetHeight
    const cx = W / 2, cy = H / 2
    const maxR = Math.min(cx, cy) - 16

    ctx.clearRect(0, 0, W, H)

    // ── Background rings ────────────────────────────────────────────────────
    const rings = [
      { km: 0.1,  label: '100m', color: 'rgba(255,51,51,0.5)' },
      { km: 1.0,  label: '1km',  color: 'rgba(255,170,0,0.35)' },
      { km: 5.0,  label: '5km',  color: 'rgba(0,255,136,0.2)' },
    ]

    rings.forEach(({ km, label, color }, i) => {
      const r = (km / 5.0) * maxR
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.strokeStyle = color
      ctx.lineWidth = i === 0 ? 1.5 : 1
      ctx.setLineDash(i === 0 ? [] : [4, 4])
      ctx.stroke()
      ctx.setLineDash([])

      // Label
      ctx.fillStyle = color
      ctx.font = '10px Share Tech Mono'
      ctx.fillText(label, cx + r + 3, cy - 3)
    })

    // ── Crosshair ───────────────────────────────────────────────────────────
    ctx.strokeStyle = 'rgba(0,255,136,0.15)'
    ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(cx, cy - maxR); ctx.lineTo(cx, cy + maxR); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(cx - maxR, cy); ctx.lineTo(cx + maxR, cy); ctx.stroke()

    // ── No selection placeholder ─────────────────────────────────────────────
    if (!selectedSat) {
      ctx.fillStyle = 'rgba(0,255,136,0.2)'
      ctx.font = '14px VT323'
      ctx.textAlign = 'center'
      ctx.fillText('SELECT SATELLITE', cx, cy)
      return
    }

    // ── Plot debris warnings ─────────────────────────────────────────────────
    const satWarnings = warnings.filter(w => w.satellite === selectedSat.id)

    satWarnings.forEach(w => {
      const dist  = w.distance_km ?? 5
      const r     = Math.min((dist / 5.0) * maxR, maxR)

      // Angle based on debris id hash (deterministic spread)
      const hash  = w.debris.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
      const angle = ((hash % 360) * Math.PI) / 180

      const dx = cx + r * Math.cos(angle)
      const dy = cy + r * Math.sin(angle)

      const color = w.severity === 'CRITICAL' ? '#ff3333'
                  : w.severity === 'RED'      ? '#ff6600'
                  : '#ffaa00'

      // Outer glow
      const grd = ctx.createRadialGradient(dx, dy, 0, dx, dy, 10)
      grd.addColorStop(0, color + 'cc')
      grd.addColorStop(1, color + '00')
      ctx.beginPath()
      ctx.arc(dx, dy, 10, 0, Math.PI * 2)
      ctx.fillStyle = grd
      ctx.fill()

      // Dot
      ctx.beginPath()
      ctx.arc(dx, dy, 4, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()

      // Label
      ctx.fillStyle = color
      ctx.font = '9px Share Tech Mono'
      ctx.textAlign = 'left'
      ctx.fillText(w.debris, dx + 7, dy + 3)
    })

    // ── Centre satellite dot ─────────────────────────────────────────────────
    ctx.beginPath()
    ctx.arc(cx, cy, 5, 0, Math.PI * 2)
    ctx.fillStyle = '#00ff88'
    ctx.fill()

    ctx.fillStyle = '#00ff88'
    ctx.font = '11px Share Tech Mono'
    ctx.textAlign = 'center'
    ctx.fillText(selectedSat.id, cx, cy - 10)

    // ── Empty state ──────────────────────────────────────────────────────────
    if (satWarnings.length === 0) {
      ctx.fillStyle = 'rgba(0,255,136,0.3)'
      ctx.font = '13px VT323'
      ctx.textAlign = 'center'
      ctx.fillText('NO THREATS DETECTED', cx, cy + 20)
    }

  }, [warnings, selectedSat])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  )
}