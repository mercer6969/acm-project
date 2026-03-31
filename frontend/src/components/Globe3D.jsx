import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

const EARTH_RADIUS = 1.0
const DEG          = Math.PI / 180

// ── Altitude shells (km above surface → Three.js scale) ───────────────────────
// LEO: 160–2000 km  |  MEO: 2000–35786 km  |  GEO: ~35786 km
// We compress MEO/GEO logarithmically so they're visible on screen
const ALT_SCALE = 1 / 6378.137   // 1 km → Three.js units

function altToRadius(altKm) {
  if (altKm <= 0)     altKm = 400       // default LEO
  if (altKm <= 2000)  return EARTH_RADIUS + altKm * ALT_SCALE              // LEO: linear
  if (altKm <= 35786) return EARTH_RADIUS + 2000 * ALT_SCALE               // MEO: compressed to LEO shell outer edge
                                          + (altKm - 2000) * ALT_SCALE * 0.15
  return EARTH_RADIUS + 2000 * ALT_SCALE + 33786 * ALT_SCALE * 0.15        // GEO: fixed outer ring
         + (altKm - 35786) * ALT_SCALE * 0.05
}

function latLonToVec3(lat, lon, altKm = 400) {
  const r     = altToRadius(altKm)
  const phi   = (90 - lat) * DEG
  const theta = (lon + 180) * DEG
  return new THREE.Vector3(
    -r * Math.sin(phi) * Math.cos(theta),
     r * Math.cos(phi),
     r * Math.sin(phi) * Math.sin(theta),
  )
}

// ── Ground stations (matches ground_stations.csv in spec) ────────────────────
const GROUND_STATIONS = [
  { id: 'GS-001', name: 'ISTRAC Bengaluru',      lat:  13.0333, lon:  77.5167 },
  { id: 'GS-002', name: 'Svalbard',               lat:  78.2297, lon:  15.4077 },
  { id: 'GS-003', name: 'Goldstone',              lat:  35.4266, lon: -116.890 },
  { id: 'GS-004', name: 'Punta Arenas',           lat: -53.1500, lon:  -70.917 },
  { id: 'GS-005', name: 'IIT Delhi',              lat:  28.5450, lon:   77.193 },
  { id: 'GS-006', name: 'McMurdo Station',        lat: -77.8463, lon:  166.668 },
]

// ── Earth texture + mesh ──────────────────────────────────────────────────────
function createEarth() {
  const geo = new THREE.IcosahedronGeometry(EARTH_RADIUS, 6)
  const loader = new THREE.TextureLoader()
  const tex = loader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
  tex.magFilter = THREE.NearestFilter
  tex.minFilter = THREE.NearestFilter
  tex.generateMipmaps = false
  const mat = new THREE.MeshPhongMaterial({
    map: tex, flatShading: true, shininess: 0,
  })
  return new THREE.Mesh(geo, mat)
}

function createAtmosphere() {
  const geo = new THREE.SphereGeometry(EARTH_RADIUS * 1.06, 24, 24)
  const mat = new THREE.MeshPhongMaterial({
    color: 0x0044aa, transparent: true, opacity: 0.08, side: THREE.BackSide,
  })
  return new THREE.Mesh(geo, mat)
}

function createStars(scene) {
  const geo   = new THREE.BufferGeometry()
  const verts = []
  for (let i = 0; i < 3000; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi   = Math.acos(2 * Math.random() - 1)
    const r     = 40 + Math.random() * 40
    verts.push(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta))
  }
  geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
  scene.add(new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x334455, size: 0.08 })))
}

// ── Altitude shell rings (visual guide for LEO / MEO / GEO) ─────────────────
function createAltitudeShells(scene) {
  const shells = [
    { altKm: 400,   color: 0x003311, label: 'LEO',  opacity: 0.06 },
    { altKm: 2000,  color: 0x002233, label: 'MEO',  opacity: 0.04 },
    { altKm: 35786, color: 0x001122, label: 'GEO',  opacity: 0.03 },
  ]
  shells.forEach(({ altKm, color, opacity }) => {
    const r   = altToRadius(altKm)
    const geo = new THREE.SphereGeometry(r, 32, 32)
    const mat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity, side: THREE.BackSide, wireframe: false,
    })
    scene.add(new THREE.Mesh(geo, mat))

    // Wireframe ring equator
    const ringGeo = new THREE.RingGeometry(r - 0.001, r + 0.001, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: opacity * 3, side: THREE.DoubleSide,
    })
    scene.add(new THREE.Mesh(ringGeo, ringMat))
  })
}

// ── Terminator line (day/night boundary) ─────────────────────────────────────
function createTerminator(scene, simTimeSec = 0) {
  // Sun direction: rotates around Earth over ~24h
  // GST0 = 280.46° at J2000, advances at 360.985°/day
  const GST_DEG_PER_S = 360.98564724 / 86164.1
  const gst = ((280.46061837 + GST_DEG_PER_S * simTimeSec) % 360) * DEG
  const sunDir = new THREE.Vector3(Math.cos(gst), 0, Math.sin(gst)).normalize()

  // Terminator = great circle perpendicular to sun direction
  const points = []
  const up     = new THREE.Vector3(0, 1, 0)
  const perp1  = new THREE.Vector3().crossVectors(sunDir, up).normalize()
  const perp2  = new THREE.Vector3().crossVectors(sunDir, perp1).normalize()
  const r      = EARTH_RADIUS * 1.002

  for (let i = 0; i <= 128; i++) {
    const angle = (i / 128) * Math.PI * 2
    const p = new THREE.Vector3()
      .addScaledVector(perp1, Math.cos(angle) * r)
      .addScaledVector(perp2, Math.sin(angle) * r)
    points.push(p)
  }

  const geo = new THREE.BufferGeometry().setFromPoints(points)
  return new THREE.Line(geo, new THREE.LineBasicMaterial({
    color: 0xff6600, transparent: true, opacity: 0.5,
  }))
}

// ── Ground station markers ────────────────────────────────────────────────────
function createGroundStations(scene) {
  const markers = []
  GROUND_STATIONS.forEach(gs => {
    const pos = latLonToVec3(gs.lat, gs.lon, 10) // just above surface

    // Diamond marker
    const geo  = new THREE.OctahedronGeometry(0.008, 0)
    const mat  = new THREE.MeshBasicMaterial({ color: 0x00ffff })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.position.copy(pos)
    scene.add(mesh)

    // Uplink cone
    const coneGeo = new THREE.ConeGeometry(0.015, 0.06, 6, 1, true)
    const coneMat = new THREE.MeshBasicMaterial({
      color: 0x00ffff, transparent: true, opacity: 0.12, side: THREE.DoubleSide,
    })
    const cone = new THREE.Mesh(coneGeo, coneMat)
    cone.position.copy(pos)
    cone.lookAt(0, 0, 0)
    cone.rotateX(Math.PI / 2)
    cone.translateZ(-0.03)
    scene.add(cone)

    markers.push({ mesh, cone, gs })
  })
  return markers
}

// ── Satellite model ───────────────────────────────────────────────────────────
function createSatelliteModel(color = 0x00ff88) {
  const group = new THREE.Group()
  const flat  = c => new THREE.MeshPhongMaterial({
    color: c, flatShading: true, shininess: 0,
    emissive: new THREE.Color(c).multiplyScalar(0.12),
  })

  group.add(new THREE.Mesh(new THREE.BoxGeometry(0.022, 0.022, 0.028), flat(color)))

  const armMat = flat(0x888888)
  ;[-0.020, 0.020].forEach(x => {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.002, 0.002), armMat)
    arm.position.set(x, 0, 0)
    group.add(arm)
  })

  const panelMat = new THREE.MeshPhongMaterial({
    color: 0x1a2e6e, flatShading: true, shininess: 50,
    emissive: new THREE.Color(0x1109e1), specular: new THREE.Color(0x334688),
  })
  ;[-0.051, 0.051].forEach(x => {
    const panel = new THREE.Mesh(new THREE.BoxGeometry(0.042, 0.001, 0.028), panelMat)
    panel.position.set(x, 0, 0)
    group.add(panel)
  })

  const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.002, 0.003, 0.005, 4), flat(0x666666))
  nozzle.position.set(0, -0.014, 0)
  group.add(nozzle)

  return group
}

// ── Debris InstancedMesh ──────────────────────────────────────────────────────
function createDebrisCloud(scene, count) {
  const geo  = new THREE.TetrahedronGeometry(0.003, 0)
  const mat  = new THREE.MeshBasicMaterial({ color: 0xff2200 })
  const mesh = new THREE.InstancedMesh(geo, mat, Math.max(count, 1))
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
  scene.add(mesh)
  return mesh
}

// ── Crash/explosion particle system ──────────────────────────────────────────
class CrashExplosion {
  constructor(scene, position) {
    this.scene    = scene
    this.position = position.clone()
    this.age      = 0
    this.maxAge   = 120  // frames
    this.particles = []
    this.meshes   = []

    const COUNT = 80

    // Core flash sphere
    const flashGeo = new THREE.SphereGeometry(0.01, 6, 6)
    const flashMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true })
    this.flash = new THREE.Mesh(flashGeo, flashMat)
    this.flash.position.copy(position)
    scene.add(this.flash)

    // Debris particles flying outward
    for (let i = 0; i < COUNT; i++) {
      const size = 0.003 + Math.random() * 0.006
      const geo  = i % 3 === 0
        ? new THREE.TetrahedronGeometry(size, 0)
        : new THREE.BoxGeometry(size, size, size)
      const mat  = new THREE.MeshBasicMaterial({
        color: [0xff4400, 0xff8800, 0xffcc00, 0xffffff, 0xff0000][Math.floor(Math.random() * 5)],
        transparent: true,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.copy(position)

      // Random velocity outward
      const vel = new THREE.Vector3(
        (Math.random() - 0.5) * 0.04,
        (Math.random() - 0.5) * 0.04,
        (Math.random() - 0.5) * 0.04,
      )
      // Bias outward from Earth center
      const outward = position.clone().normalize().multiplyScalar(0.02 * Math.random())
      vel.add(outward)

      scene.add(mesh)
      this.particles.push({ mesh, vel, spin: Math.random() * 0.3 - 0.15 })
      this.meshes.push(mesh)
    }

    // Shockwave ring
    const ringGeo = new THREE.RingGeometry(0.001, 0.012, 16)
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xff6600, transparent: true, opacity: 0.9, side: THREE.DoubleSide,
    })
    this.ring = new THREE.Mesh(ringGeo, ringMat)
    this.ring.position.copy(position)
    this.ring.lookAt(0, 0, 0)
    scene.add(this.ring)
    this.meshes.push(this.ring)
    this.meshes.push(this.flash)
  }

  tick() {
    this.age++
    const t       = this.age / this.maxAge        // 0→1
    const easeOut = 1 - Math.pow(1 - t, 2)

    // Flash: bright then fade
    const flashScale = 1 + easeOut * 8
    this.flash.scale.setScalar(flashScale)
    this.flash.material.opacity = Math.max(0, 1 - t * 3)

    // Shockwave ring expands and fades
    const ringScale = 1 + easeOut * 20
    this.ring.scale.setScalar(ringScale)
    this.ring.material.opacity = Math.max(0, 0.9 - t * 2)

    // Particles: move, spin, fade
    this.particles.forEach(({ mesh, vel, spin }) => {
      mesh.position.add(vel.clone().multiplyScalar(1 - t * 0.5))  // slow down
      mesh.rotation.x += spin
      mesh.rotation.y += spin * 0.7
      mesh.material.opacity = Math.max(0, 1 - t * 1.2)
    })

    return this.age < this.maxAge
  }

  destroy() {
    this.meshes.forEach(m => {
      this.scene.remove(m)
      m.geometry.dispose()
      m.material.dispose()
    })
    this.particles.forEach(({ mesh }) => {
      this.scene.remove(mesh)
      mesh.geometry.dispose()
      mesh.material.dispose()
    })
  }
}

// ── Orbit trail (stores real position history) ────────────────────────────────
// We keep a ring buffer of positions per satellite
const TRAIL_LENGTH  = 30   // history points
const trailHistories = {}  // satId → Vector3[]

function updateTrail(scene, satModels, sat, pos) {
  if (!trailHistories[sat.id]) trailHistories[sat.id] = []
  const hist = trailHistories[sat.id]
  hist.push(pos.clone())
  if (hist.length > TRAIL_LENGTH) hist.shift()

  // Remove old trail
  const oldTrail = satModels[`${sat.id}_trail`]
  if (oldTrail) {
    scene.remove(oldTrail)
    oldTrail.geometry.dispose()
  }

  if (hist.length < 2) return

  const geo = new THREE.BufferGeometry().setFromPoints(hist)
  const mat = new THREE.LineBasicMaterial({
    color: sat.status === 'EVADING' ? 0xffaa00 : 0x00ff88,
    transparent: true, opacity: 0.35,
  })
  const line = new THREE.Line(geo, mat)
  scene.add(line)
  satModels[`${sat.id}_trail`] = line
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Globe3D({
  satellites   = [],
  debrisCloud  = [],
  selectedSat  = null,
  onSelectSat  = null,
  collisions   = [],     // [{position: {lat, lon, alt_km}}, ...] from simulate step
  simTimeSec   = 0,
}) {
  const mountRef       = useRef(null)
  const sceneRef       = useRef(null)
  const earthRef       = useRef(null)
  const frameRef       = useRef(null)
  const satModels      = useRef({})
  const debrisMesh     = useRef(null)
  const debrisCapacity = useRef(0)
  const explosions     = useRef([])
  const terminatorRef  = useRef(null)
  const gsMarkersRef   = useRef([])

  // ── Scene init ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const W = mountRef.current.clientWidth
    const H = mountRef.current.clientHeight

    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false })
    renderer.setSize(W, H)
    renderer.setPixelRatio(0.6)
    renderer.setClearColor(0x020a10)
    mountRef.current.appendChild(renderer.domElement)

    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, W / H, 0.01, 200)
    camera.position.set(0, 0, 2.8)
    camera.lookAt(0, 0, 0)

    sceneRef.current = { scene, camera, renderer }

    // Lighting
    const sun = new THREE.DirectionalLight(0xffeedd, 1.8)
    sun.position.set(4, 2, 3)
    scene.add(sun)
    scene.add(new THREE.DirectionalLight(0x112244, 0.2).position.set(-3, -1, -2) && new THREE.DirectionalLight(0x112244, 0.2))
    scene.add(new THREE.AmbientLight(0x0a0f18, 0.2))

    // Earth
    const earthGroup = new THREE.Group()
    earthGroup.add(createEarth())
    earthRef.current = earthGroup
    scene.add(earthGroup)
    scene.add(createAtmosphere())
    createStars(scene)

    // Altitude shells
    createAltitudeShells(scene)

    // Ground stations
    gsMarkersRef.current = createGroundStations(scene)

    // Terminator (initial)
    const term = createTerminator(scene, 0)
    terminatorRef.current = term
    scene.add(term)

    // Camera controls
    let isDragging = false
    let prevMouse  = { x: 0, y: 0 }
    const sph      = { theta: 0.5, phi: 1.3 }
    const dist     = { v: 2.8 }

    const updateCam = () => {
      camera.position.set(
        dist.v * Math.sin(sph.phi) * Math.sin(sph.theta),
        dist.v * Math.cos(sph.phi),
        dist.v * Math.sin(sph.phi) * Math.cos(sph.theta),
      )
      camera.lookAt(0, 0, 0)
    }
    updateCam()

    const onDown  = e => { isDragging = true; prevMouse = { x: e.clientX, y: e.clientY } }
    const onUp    = () => { isDragging = false }
    const onMove  = e => {
      if (!isDragging) return
      sph.theta -= (e.clientX - prevMouse.x) * 0.006
      sph.phi    = Math.max(0.1, Math.min(Math.PI - 0.1, sph.phi + (e.clientY - prevMouse.y) * 0.006))
      updateCam()
      prevMouse = { x: e.clientX, y: e.clientY }
    }
    const onWheel = e => {
      dist.v = Math.max(1.3, Math.min(6, dist.v + e.deltaY * 0.002))
      updateCam()
    }

    renderer.domElement.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('mousemove', onMove)
    renderer.domElement.addEventListener('wheel', onWheel)

    // Click-to-select satellite
    const raycaster = new THREE.Raycaster()
    const mouse     = new THREE.Vector2()
    let   mouseDownPos = { x: 0, y: 0 }

    const onMouseDownRecord = e => { mouseDownPos = { x: e.clientX, y: e.clientY } }
    const onClickSelect = e => {
      if (Math.abs(e.clientX - mouseDownPos.x) > 4 || Math.abs(e.clientY - mouseDownPos.y) > 4) return
      if (!onSelectSat) return
      const rect = renderer.domElement.getBoundingClientRect()
      mouse.x =  ((e.clientX - rect.left)  / rect.width)  * 2 - 1
      mouse.y = -((e.clientY - rect.top)   / rect.height) * 2 + 1
      raycaster.setFromCamera(mouse, camera)

      const meshes = Object.entries(satModels.current)
        .filter(([k]) => !k.endsWith('_trail') && !k.endsWith('_ring'))
        .map(([k, m]) => ({ id: k, mesh: m }))

      const hits = raycaster.intersectObjects(meshes.map(x => x.mesh), true)
      if (hits.length > 0) {
        let obj = hits[0].object
        while (obj.parent && obj.parent.type !== 'Scene') obj = obj.parent
        const entry = meshes.find(x => x.mesh === obj)
        if (entry) {
          const sat = satellites.find(s => s.id === entry.id)
          if (sat) onSelectSat(sat)
        }
      }
    }

    renderer.domElement.addEventListener('mousedown', onMouseDownRecord)
    renderer.domElement.addEventListener('click', onClickSelect)

    // Animate — tick explosions every frame
    const animate = () => {
      frameRef.current = requestAnimationFrame(animate)
      if (!isDragging && earthRef.current) earthRef.current.rotation.y += 0.001

      // Tick active explosions
      explosions.current = explosions.current.filter(ex => {
        const alive = ex.tick()
        if (!alive) ex.destroy()
        return alive
      })

      renderer.render(scene, camera)
    }
    animate()

    const onResize = () => {
      if (!mountRef.current) return
      const w = mountRef.current.clientWidth
      const h = mountRef.current.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(frameRef.current)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('click', onClickSelect)
      renderer.domElement.removeEventListener('mousedown', onMouseDownRecord)
      renderer.dispose()
      if (mountRef.current) mountRef.current.innerHTML = ''
    }
  }, [])

  // ── Update terminator when simTime changes ────────────────────────────────
  useEffect(() => {
    if (!sceneRef.current) return
    const { scene } = sceneRef.current
    if (terminatorRef.current) {
      scene.remove(terminatorRef.current)
      terminatorRef.current.geometry.dispose()
    }
    const term = createTerminator(scene, simTimeSec)
    terminatorRef.current = term
    scene.add(term)
  }, [simTimeSec])

  // ── Trigger crash explosions for new collisions ───────────────────────────
  useEffect(() => {
    if (!sceneRef.current || !collisions?.length) return
    const { scene } = sceneRef.current
    collisions.forEach(col => {
      const lat   = col?.lat   ?? col?.position?.lat   ?? 0
      const lon   = col?.lon   ?? col?.position?.lon   ?? 0
      const alt   = col?.alt_km ?? col?.position?.alt_km ?? 400
      const pos   = latLonToVec3(lat, lon, alt)
      explosions.current.push(new CrashExplosion(scene, pos))
    })
  }, [collisions])

  // ── Update debris ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sceneRef.current || !debrisCloud) return
    const { scene } = sceneRef.current
    const count = debrisCloud.length

    if (count === 0) {
      if (debrisMesh.current) debrisMesh.current.count = 0
      return
    }

    if (!debrisMesh.current || debrisCapacity.current < count) {
      if (debrisMesh.current) {
        scene.remove(debrisMesh.current)
        debrisMesh.current.geometry.dispose()
      }
      debrisMesh.current  = createDebrisCloud(scene, count)
      debrisCapacity.current = count
    }

    const mesh  = debrisMesh.current
    const dummy = new THREE.Object3D()
    debrisCloud.forEach(([, lat, lon, alt], i) => {
      dummy.position.copy(latLonToVec3(lat, lon, alt))
      dummy.lookAt(0, 0, 0)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    })
    mesh.count = count
    mesh.instanceMatrix.needsUpdate = true
  }, [debrisCloud])

  // ── Update satellites ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!sceneRef.current || !satellites) return
    const { scene } = sceneRef.current

    // Remove old satellite meshes (keep trails — they have their own cleanup)
    Object.entries(satModels.current).forEach(([k, m]) => {
      if (!k.endsWith('_trail')) scene.remove(m)
    })
    // Keep trail refs but clear non-trail models
    const newModels = {}
    Object.entries(satModels.current).forEach(([k, v]) => {
      if (k.endsWith('_trail')) newModels[k] = v
    })
    satModels.current = newModels

    satellites.forEach(sat => {
      const altKm = sat.alt_km ?? 400
      const pos   = latLonToVec3(sat.lat, sat.lon, altKm)

      const isSelected = selectedSat?.id === sat.id
      const color =
        sat.status === 'EVADING'  ? 0xffaa00 :
        sat.status === 'EOL'      ? 0x555555 :
        sat.status === 'CRITICAL' ? 0xff2200 : 0x00ee77

      const model = createSatelliteModel(color)
      model.position.copy(pos)
      model.lookAt(0, 0, 0)
      model.rotateX(Math.PI / 2)
      if (isSelected) model.scale.setScalar(1.8)

      // Selection ring
      if (isSelected) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(0.034, 0.042, 5),
          new THREE.MeshBasicMaterial({ color: 0x00ff88, side: THREE.DoubleSide, transparent: true, opacity: 0.85 }),
        )
        ring.position.copy(pos)
        ring.lookAt(0, 0, 0)
        scene.add(ring)
        satModels.current[`${sat.id}_ring`] = ring
      }

      // Real orbit trail from history
      updateTrail(scene, satModels.current, sat, pos)

      scene.add(model)
      satModels.current[sat.id] = model
    })
  }, [satellites, selectedSat])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', backgroundColor: '#000', overflow: 'hidden' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      {/* CRT scanline overlay */}
      <div style={{
        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
        pointerEvents: 'none',
        background: `linear-gradient(rgba(18,16,16,0) 50%, rgba(0,0,0,0.25) 50%),
                     linear-gradient(90deg, rgba(255,0,0,0.06), rgba(0,255,0,0.02), rgba(0,0,255,0.06))`,
        backgroundSize: '100% 4px, 3px 100%',
        zIndex: 10,
      }} />

      {/* Vignette */}
      <div style={{
        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
        pointerEvents: 'none',
        background: 'radial-gradient(circle, rgba(0,0,0,0) 50%, rgba(0,0,0,0.85) 100%)',
        zIndex: 11,
      }} />

      {/* HUD top-left */}
      <div style={{
        position: 'absolute', top: 30, left: 30,
        backgroundColor: '#0a1208cc',
        border: '1px solid #1a3a20',
        padding: '10px 14px',
        color: '#dfdfcb',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 14, letterSpacing: 1,
        zIndex: 12, pointerEvents: 'none',
      }}>
        SECTOR LEO/MEO/GEO //<br />
        SATS: <span style={{ color: '#00ff88' }}>{satellites.length}</span>
        &nbsp;|&nbsp;
        DEBRIS: <span style={{ color: '#ff3333' }}>{debrisCloud.length}</span><br />
        <span style={{ color: '#00ccff', fontSize: 11 }}>◈ GND STATIONS: {GROUND_STATIONS.length}</span>
      </div>

      {/* Legend bottom-right */}
      <div style={{
        position: 'absolute', bottom: 30, right: 30,
        backgroundColor: '#0a1208cc',
        border: '1px solid #1a3a20',
        padding: '8px 12px',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 12, zIndex: 12, pointerEvents: 'none',
      }}>
        <div style={{ color: '#00ee77' }}>▸ SAT NOMINAL</div>
        <div style={{ color: '#ffaa00' }}>▸ SAT EVADING</div>
        <div style={{ color: '#ff2200' }}>▸ SAT CRITICAL</div>
        <div style={{ color: '#ff2200', opacity: 0.7 }}>▸ DEBRIS</div>
        <div style={{ color: '#00ccff' }}>◈ GROUND STN</div>
        <div style={{ color: '#ff6600' }}>── TERMINATOR</div>
      </div>

      {/* Altitude shell labels */}
      <div style={{
        position: 'absolute', top: '50%', right: 12,
        transform: 'translateY(-50%)',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 10, color: 'rgba(0,255,136,0.3)',
        zIndex: 12, pointerEvents: 'none',
        display: 'flex', flexDirection: 'column', gap: 18,
      }}>
        <div>GEO</div>
        <div>MEO</div>
        <div>LEO</div>
      </div>

      {/* Drag hint */}
      <div style={{
        position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
        fontFamily: 'VT323', fontSize: '0.85rem', color: 'rgba(0,255,136,0.3)',
        pointerEvents: 'none', zIndex: 12,
      }}>
        DRAG TO ROTATE &nbsp;|&nbsp; SCROLL TO ZOOM &nbsp;|&nbsp; CLICK SAT TO SELECT
      </div>
    </div>
  )
}