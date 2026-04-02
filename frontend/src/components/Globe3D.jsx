import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

const EARTH_RADIUS = 1.0
const DEG = Math.PI / 180

// Ground stations from spec §5.5.1
const GROUND_STATIONS = [
  { id: 'GS-001', name: 'ISTRAC\nBengaluru',  lat:  13.0333, lon:   77.5167 },
  { id: 'GS-002', name: 'Svalbard',           lat:  78.2298, lon:   15.4078 },
  { id: 'GS-003', name: 'Goldstone',          lat:  35.4267, lon: -116.8900 },
  { id: 'GS-004', name: 'Punta\nArenas',      lat: -52.9333, lon:  -70.8500 },
  { id: 'GS-005', name: 'IIT Delhi',          lat:  28.5450, lon:   77.1926 },
  { id: 'GS-006', name: 'McMurdo',            lat: -77.8464, lon:  166.6683 }
]

function latLonToVec3(lat, lon, altKm) {
  const scale = EARTH_RADIUS + (altKm / 6378.137) * EARTH_RADIUS
  const phi   = (90 - lat) * DEG
  
  // REVERT: Back to 180. This perfectly aligns with Three.js SphereGeometry UVs.
  const theta = (lon + 180) * DEG 
  
  return new THREE.Vector3(
    -scale * Math.sin(phi) * Math.cos(theta),
     scale * Math.cos(phi),
     scale * Math.sin(phi) * Math.sin(theta)
  )
}
function createMouthwashingEarth() {
  // FIX: Use SphereGeometry so the equirectangular map wraps correctly
  const geo = new THREE.SphereGeometry(EARTH_RADIUS, 64, 64)
  
  const textureLoader = new THREE.TextureLoader()
  const earthTexture = textureLoader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
  earthTexture.magFilter = THREE.NearestFilter
  earthTexture.minFilter = THREE.NearestFilter
  earthTexture.generateMipmaps = false
  
  const mat = new THREE.MeshPhongMaterial({
    map: earthTexture, 
    flatShading: true, // You can leave this true for a faceted retro look, or false for a smooth globe
    shininess: 0,
    emissive: new THREE.Color(0x000000),
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

/* ── Ground station beacon ─────────────────────────────────────────────────── */
function createGroundStationMarker(lat, lon) {
  const group = new THREE.Group()
  const pos   = latLonToVec3(lat, lon, 5) // slightly above surface

  // Base disc — flat cylinder on the surface
  const discGeo = new THREE.CylinderGeometry(0.012, 0.012, 0.002, 8)
  const discMat = new THREE.MeshBasicMaterial({ color: 0x00ffff })
  const disc    = new THREE.Mesh(discGeo, discMat)
  group.add(disc)

  // Upright spike — antenna mast
  const spikeGeo = new THREE.CylinderGeometry(0.001, 0.002, 0.025, 4)
  const spikeMat = new THREE.MeshBasicMaterial({ color: 0x00ffff })
  const spike    = new THREE.Mesh(spikeGeo, spikeMat)
  spike.position.y = 0.013
  group.add(spike)

  // Dish — cone pointing outward (away from Earth)
  const dishGeo = new THREE.ConeGeometry(0.010, 0.014, 6, 1, true)
  const dishMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide })
  const dish    = new THREE.Mesh(dishGeo, dishMat)
  dish.position.y = 0.032
  group.add(dish)

  // Outer pulse ring — glowing halo
  const ringGeo = new THREE.RingGeometry(0.018, 0.024, 12)
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.6,
  })
  const ring = new THREE.Mesh(ringGeo, ringMat)
  group.add(ring)

  // Second larger ring for emphasis
  const ring2Geo = new THREE.RingGeometry(0.028, 0.032, 12)
  const ring2Mat = new THREE.MeshBasicMaterial({
    color: 0x00aaff, side: THREE.DoubleSide, transparent: true, opacity: 0.35,
  })
  const ring2 = new THREE.Mesh(ring2Geo, ring2Mat)
  group.add(ring2)

  // Position group on Earth surface and orient outward
  group.position.copy(pos)
  group.lookAt(0, 0, 0)
  group.rotateX(Math.PI / 2)   // flip so spike points away from Earth

  return group
}

/* ── Satellite model ─────────────────────────────────────────────────────────── */
function createSatelliteModel(color = 0x00ff88) {
  const group = new THREE.Group()
  const flat  = (c) => new THREE.MeshPhongMaterial({
    color: c, flatShading: true, shininess: 0,
    emissive: new THREE.Color(c).multiplyScalar(0.15),
  })
  group.add(new THREE.Mesh(new THREE.BoxGeometry(0.020, 0.009, 0.013), flat(color)))
  const wing = new THREE.Mesh(new THREE.BoxGeometry(0.030, 0.002, 0.011), flat(0x112255))
  const wL = wing.clone(); wL.position.set(-0.025, 0, 0); group.add(wL)
  const wR = wing.clone(); wR.position.set( 0.025, 0, 0); group.add(wR)
  const dish = new THREE.Mesh(new THREE.ConeGeometry(0.005, 0.008, 4), flat(0x777777))
  dish.position.set(0, 0.011, 0); dish.rotateX(Math.PI); group.add(dish)
  return group
}

/* ── Instanced debris ─────────────────────────────────────────────────────────── */
function createDebrisCloud(parent, count) {
  const geo  = new THREE.TetrahedronGeometry(0.003, 0)
  const mat  = new THREE.MeshBasicMaterial({ color: 0xff2200 })
  const mesh = new THREE.InstancedMesh(geo, mat, Math.max(count, 1))
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
  parent.add(mesh)   // add to earthGroup so it rotates with Earth
  return mesh
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Globe3D({ satellites = [], debrisCloud = [], selectedSat = null, earthRotationY = 0, rotateEnabled = true }) {
  const mountRef   = useRef(null)
  const sceneRef   = useRef(null)
  const earthRef   = useRef(null)   // the earthGroup that rotates
  const frameRef   = useRef(null)
  const satModels  = useRef({})
  const debrisMesh = useRef(null)
  const gsMarkers  = useRef([])

  /* ── Init scene ─────────────────────────────────────────────────────────── */
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
    const fill = new THREE.DirectionalLight(0x112244, 0.2)
    fill.position.set(-3, -1, -2)
    scene.add(fill)
    scene.add(new THREE.AmbientLight(0x0a0f18, 0.2))

    // Earth group — everything that rotates together
    const earthGroup = new THREE.Group()
    earthGroup.add(createMouthwashingEarth())
    earthRef.current = earthGroup
    scene.add(earthGroup)

    scene.add(createAtmosphere())
    createStars(scene)

    // ── Ground station markers (added to earthGroup so they rotate with Earth)
    GROUND_STATIONS.forEach(gs => {
      const marker = createGroundStationMarker(gs.lat, gs.lon)
      earthGroup.add(marker)
      gsMarkers.current.push(marker)
    })

    // Camera orbit
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
      dist.v = Math.max(1.4, Math.min(6, dist.v + e.deltaY * 0.002))
      updateCam()
    }

    renderer.domElement.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('mousemove', onMove)
    renderer.domElement.addEventListener('wheel', onWheel)

    // Pulse animation for ground station rings (no Earth rotation here)
    let t = 0
    const animate = () => {
      frameRef.current = requestAnimationFrame(animate)
      t += 0.05
      gsMarkers.current.forEach((gs, idx) => {
        const ring2 = gs.children[4]
        if (ring2 && ring2.material) {
          ring2.material.opacity = 0.2 + 0.2 * Math.sin(t + idx * 1.2)
        }
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
      renderer.dispose()
      if (mountRef.current) mountRef.current.innerHTML = ''
    }
  }, [])

  // ── Snap Earth rotation to a specific value (from prop) ─────────────────
  useEffect(() => {
    if (earthRef.current) {
      earthRef.current.rotation.y = earthRotationY
    }
  }, [earthRotationY])

  // ── Continuous rotation when enabled ────────────────────────────────────
  useEffect(() => {
    if (!rotateEnabled) return
    let lastTimestamp = 0
    const step = 0.001 // rotation per frame (~0.06 rad/s at 60fps)
    let animFrame
    const animateRotation = () => {
      if (earthRef.current) {
        earthRef.current.rotation.y += step
      }
      animFrame = requestAnimationFrame(animateRotation)
    }
    animFrame = requestAnimationFrame(animateRotation)
    return () => cancelAnimationFrame(animFrame)
  }, [rotateEnabled])

  /* ── Update debris cloud ─────────────────────────────────────────────────── */
  useEffect(() => {
    if (!sceneRef.current || !earthRef.current || !debrisCloud) return
    const earthGroup = earthRef.current

    if (debrisMesh.current) {
      earthGroup.remove(debrisMesh.current)
      debrisMesh.current.geometry.dispose()
      debrisMesh.current = null
    }
    if (debrisCloud.length === 0) return

    const mesh  = createDebrisCloud(earthGroup, debrisCloud.length)
    const dummy = new THREE.Object3D()
    debrisCloud.forEach(([, lat, lon, alt], i) => {
      dummy.position.copy(latLonToVec3(lat, lon, alt))
      dummy.lookAt(0, 0, 0)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
    debrisMesh.current = mesh
  }, [debrisCloud])

  /* ── Update satellite models ─────────────────────────────────────────────── */
  useEffect(() => {
    if (!sceneRef.current || !earthRef.current || !satellites) return
    const earthGroup = earthRef.current

    Object.values(satModels.current).forEach(m => earthGroup.remove(m))
    satModels.current = {}

    satellites.forEach(sat => {
      const pos        = latLonToVec3(sat.lat, sat.lon, sat.alt_km || 400)
      const isSelected = selectedSat?.id === sat.id
      const color      = sat.status === 'EVADING'  ? 0xffaa00
                       : sat.status === 'EOL'       ? 0x555555
                       : sat.status === 'CRITICAL'  ? 0xff2200
                       : 0x00ee77

      const model = createSatelliteModel(color)
      model.position.copy(pos)
      model.lookAt(0, 0, 0)
      model.rotateX(Math.PI / 2)
      if (isSelected) model.scale.setScalar(1.8)

      if (isSelected) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(0.034, 0.042, 5),
          new THREE.MeshBasicMaterial({
            color: 0x00ff88, side: THREE.DoubleSide, transparent: true, opacity: 0.85,
          })
        )
        ring.position.copy(pos)
        ring.lookAt(0, 0, 0)
        earthGroup.add(ring)
        satModels.current[`${sat.id}_ring`] = ring
      }

      // Orbit trail
      const trailVerts = []
      for (let i = 1; i <= 10; i++) {
        trailVerts.push(...latLonToVec3(sat.lat, sat.lon - i * 2.5, sat.alt_km || 400).toArray())
      }
      const trailGeo = new THREE.BufferGeometry()
      trailGeo.setAttribute('position', new THREE.Float32BufferAttribute(trailVerts, 3))
      const trail = new THREE.Points(trailGeo, new THREE.PointsMaterial({
        color, size: 0.005, transparent: true, opacity: 0.4,
      }))
      earthGroup.add(trail)
      satModels.current[`${sat.id}_trail`] = trail

      earthGroup.add(model)
      satModels.current[sat.id] = model
    })
  }, [satellites, selectedSat])

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', backgroundColor: '#000', overflow: 'hidden' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      {/* CRT Scanlines */}
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

      {/* Top-left terminal */}
      <div style={{
        position: 'absolute', top: 30, left: 30,
        backgroundColor: '#161814', padding: '12px 16px', color: '#dfdfcb',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 18, fontWeight: 'bold', letterSpacing: 1, textShadow: '1px 1px #000',
        zIndex: 12, pointerEvents: 'none', boxShadow: '2px 2px 0px rgba(0,0,0,0.5)',
      }}>
        SECTOR LEO //<br />
        EARTH //<br />
        SATS: {satellites.length} &nbsp;|&nbsp; DEBRIS: {debrisCloud.length}
      </div>

      {/* Ground station legend */}
      <div style={{
        position: 'absolute', top: 30, right: 30,
        backgroundColor: '#161814', padding: '8px 12px', color: '#00ffff',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 12, letterSpacing: 1,
        zIndex: 12, pointerEvents: 'none', boxShadow: '2px 2px 0px rgba(0,0,0,0.5)',
        borderLeft: '2px solid #00ffff',
      }}>
        <div style={{ color: '#00ffff', marginBottom: 4, fontWeight: 'bold' }}>⬡ GROUND STATIONS</div>
        {GROUND_STATIONS.map(gs => (
          <div key={gs.id} style={{ fontSize: 11, color: '#88dddd', marginBottom: 2 }}>
            {gs.id} · {gs.name.replace('\n', ' ')}
          </div>
        ))}
      </div>

      {/* Bottom-right tag */}
      <div style={{
        position: 'absolute', bottom: 30, right: 30,
        backgroundColor: '#161814', padding: '10px 14px', color: '#dfdfcb',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 16, fontWeight: 'bold', letterSpacing: 1, textShadow: '1px 1px #000',
        zIndex: 12, pointerEvents: 'none', boxShadow: '2px 2px 0px rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        ACM_VIEW_001 &nbsp;✦
      </div>
    </div>
  )
}