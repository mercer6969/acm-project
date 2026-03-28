import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

const EARTH_RADIUS = 1.0
const DEG = Math.PI / 180

function latLonToVec3(lat, lon, altKm) {
  const scale = EARTH_RADIUS + (altKm / 6378.137) * EARTH_RADIUS
  const phi   = (90 - lat) * DEG
  const theta = (lon + 180) * DEG
  return new THREE.Vector3(
    -scale * Math.sin(phi) * Math.cos(theta),
     scale * Math.cos(phi),
     scale * Math.sin(phi) * Math.sin(theta)
  )
}

function createMouthwashingEarth() {
  const geo = new THREE.IcosahedronGeometry(EARTH_RADIUS, 6)
  const textureLoader = new THREE.TextureLoader()
  const earthTexture = textureLoader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
  earthTexture.magFilter = THREE.NearestFilter
  earthTexture.minFilter = THREE.NearestFilter
  earthTexture.generateMipmaps = false

  const mat = new THREE.MeshPhongMaterial({
    map:         earthTexture,
    flatShading: true,
    shininess:   0,
    emissive:    new THREE.Color(0x000000),
  })
  return new THREE.Mesh(geo, mat)
}

function createAtmosphere() {
  const geo = new THREE.SphereGeometry(EARTH_RADIUS * 1.06, 24, 24)
  const mat = new THREE.MeshPhongMaterial({
    color:       0x0044aa,
    transparent: true,
    opacity:     0.08,
    side:        THREE.BackSide,
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
    verts.push(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(theta),
    )
  }
  geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
  scene.add(new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x334455, size: 0.08 })))
}

/* ── PS1-style satellite model--needs update*/
function createSatelliteModel(color = 0x00ff88) {
  const group = new THREE.Group()
  const flat  = (c) => new THREE.MeshPhongMaterial({
    color: c, flatShading: true, shininess: 0,
    emissive: new THREE.Color(c).multiplyScalar(0.12),
  })

  // ── Main bus body — rectangular box like real satellites ──────────────────
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.022, 0.022, 0.028), flat(color))
  group.add(body)

  // ── Solar panel arms — thin struts extending from sides ───────────────────
  const armMat = flat(0x888888)
  const armL = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.002, 0.002), armMat)
  armL.position.set(-0.020, 0, 0)
  group.add(armL)

  const armR = armL.clone()
  armR.position.set(0.020, 0, 0)
  group.add(armR)

  // ── Solar panels — large flat rectangles, dark blue cells ─────────────────
  const panelMat = new THREE.MeshPhongMaterial({
    color: 0x1a2e6e, flatShading: true, shininess: 50,
    emissive: new THREE.Color(0x1109e1),
    specular: new THREE.Color(0x334688),
  })

  // Panel grid lines for realism
  const panelL = new THREE.Mesh(new THREE.BoxGeometry(0.042, 0.001, 0.028), panelMat)
  panelL.position.set(-0.051, 0, 0)
  group.add(panelL)

  const panelR = panelL.clone()
  panelR.position.set(0.051, 0, 0)
  group.add(panelR)

  // Panel cell lines — flat on panel face, visible from viewer side
const cellMat = new THREE.MeshBasicMaterial({ color: 0x0bfeff })

// Horizontal dividers (run across full panel width)
for (let i = -2; i <= 2; i++) {
  const hStrip = new THREE.Mesh(new THREE.BoxGeometry(0.042, 0.0015, 0.001), cellMat)
  hStrip.position.set(-0.051, 0.0015, i * 0.007)
  group.add(hStrip)
  const hStripR = hStrip.clone()
  hStripR.position.set(0.051, 0.0015, i * 0.007)
  group.add(hStripR)
}

// Vertical dividers (run along panel height)
for (let i = -2; i <= 2; i++) {
  const vStrip = new THREE.Mesh(new THREE.BoxGeometry(0.001, 0.0015, 0.028), cellMat)
  vStrip.position.set(-0.051 + i * 0.010, 0.0015, 0)
  group.add(vStrip)
  const vStripR = vStrip.clone()
  vStripR.position.set(0.051 + i * 0.010, 0.0015, 0)
  group.add(vStripR)
}

  // ── High-gain dish antenna — low poly cone ────────────────────────────────
  const dishBase = new THREE.Mesh(
    new THREE.CylinderGeometry(0.001, 0.001, 0.012, 4),
    flat(0x999999)
  )
  dishBase.position.set(0, 0, 0.020)
  dishBase.rotateX(Math.PI / 2)
  group.add(dishBase)

  const dish = new THREE.Mesh(
    new THREE.ConeGeometry(0.010, 0.008, 6, 1, true),
    new THREE.MeshPhongMaterial({ color: 0xcccccc, flatShading: true, side: THREE.DoubleSide })
  )
  dish.position.set(0, 0, 0.030)
  dish.rotateX(Math.PI / 2)
  group.add(dish)

  // ── Star tracker / sensor nub on top ─────────────────────────────────────
  const sensor = new THREE.Mesh(
    new THREE.BoxGeometry(0.005, 0.006, 0.005),
    flat(0x444444)
  )
  sensor.position.set(0, 0.014, -0.005)
  group.add(sensor)

  // ── Thruster nozzles — tiny cylinders on bottom ───────────────────────────
  const nozzleMat = flat(0x666666)
  const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.002, 0.003, 0.005, 4), nozzleMat)
  nozzle.position.set(0, -0.014, 0)
  group.add(nozzle)

  return group
}
/* ── Instanced debris cloud — reuse mesh, only resize if count changes */
function createDebrisCloud(scene, count) {
  const geo  = new THREE.TetrahedronGeometry(0.003, 0)
  const mat  = new THREE.MeshBasicMaterial({ color: 0xff2200 })
  const mesh = new THREE.InstancedMesh(geo, mat, Math.max(count, 1))
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
  scene.add(mesh)
  return mesh
}

// ── Main component

export default function Globe3D({ satellites = [], debrisCloud = [], selectedSat = null, onSelectSat = null }) {
  const mountRef   = useRef(null)
  const sceneRef   = useRef(null)
  const earthRef   = useRef(null)
  const frameRef   = useRef(null)
  const satModels  = useRef({})
  const debrisMesh     = useRef(null)
  const debrisCapacity = useRef(0)  // tracks allocated InstancedMesh size

  /*  Init scene */
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
    const fillLight = new THREE.DirectionalLight(0x112244, 0.2)
    fillLight.position.set(-3, -1, -2)
    scene.add(fillLight)
    scene.add(new THREE.AmbientLight(0x0a0f18, 0.2))



    const earthGroup = new THREE.Group()
    const earth      = createMouthwashingEarth()
    earthGroup.add(earth)
    earthRef.current = earthGroup
    scene.add(earthGroup)

    scene.add(createAtmosphere())
    createStars(scene)

    // Camera 
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

    // ── Satellite click-to-select via raycaster ───────────────────────────────
    const raycaster = new THREE.Raycaster()
    const mouse     = new THREE.Vector2()
    let   mouseDownPos = { x: 0, y: 0 }

    const onClickSelect = (e) => {
      // Only fire if mouse didn't move (i.e. it's a click, not a drag)
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
        // Walk up to find which sat group was hit
        let obj = hits[0].object
        while (obj.parent && obj.parent.type !== 'Scene') obj = obj.parent
        const entry = meshes.find(x => x.mesh === obj)
        if (entry) {
          const sat = satellites.find(s => s.id === entry.id)
          if (sat) onSelectSat(sat)
        }
      }
    }

    const onMouseDownRecord = (e) => { mouseDownPos = { x: e.clientX, y: e.clientY } }
    renderer.domElement.addEventListener('mousedown', onMouseDownRecord)
    renderer.domElement.addEventListener('click', onClickSelect)

    const animate = () => {
      frameRef.current = requestAnimationFrame(animate)
      if (!isDragging && earthRef.current) earthRef.current.rotation.y += 0.001
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

  /*Update debris — reuse InstancedMesh; only reallocate if count grows */
  useEffect(() => {
    if (!sceneRef.current || !debrisCloud) return
    const { scene } = sceneRef.current

    const count = debrisCloud.length
    if (count === 0) {
      // Hide existing mesh rather than remove — avoids GC churn
      if (debrisMesh.current) debrisMesh.current.count = 0
      return
    }

    // Reallocate only when capacity is exceeded (growing debris set)
    if (!debrisMesh.current || debrisCapacity.current < count) {
      if (debrisMesh.current) {
        scene.remove(debrisMesh.current)
        debrisMesh.current.geometry.dispose()
      }
      debrisMesh.current = createDebrisCloud(scene, count)
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
    // Only render the visible slice (handles shrinking sets without realloc)
    mesh.count = count
    mesh.instanceMatrix.needsUpdate = true
  }, [debrisCloud])

  /* satellite update pls  */
  useEffect(() => {
    if (!sceneRef.current || !satellites) return
    const { scene } = sceneRef.current

    Object.values(satModels.current).forEach(m => scene.remove(m))
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

      //  ring
      if (isSelected) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(0.034, 0.042, 5),
          new THREE.MeshBasicMaterial({
            color: 0x00ff88, side: THREE.DoubleSide,
            transparent: true, opacity: 0.85,
          })
        )
        ring.position.copy(pos)
        ring.lookAt(0, 0, 0)
        scene.add(ring)
        satModels.current[`${sat.id}_ring`] = ring
      }

      // Orbit 
      const trailVerts = []
      for (let i = 1; i <= 10; i++) {
        trailVerts.push(...latLonToVec3(sat.lat, sat.lon - i * 2.5, sat.alt_km || 400).toArray())
      }
      const trailGeo = new THREE.BufferGeometry()
      trailGeo.setAttribute('position', new THREE.Float32BufferAttribute(trailVerts, 3))
      const trail = new THREE.Points(trailGeo, new THREE.PointsMaterial({
        color, size: 0.005, transparent: true, opacity: 0.4,
      }))
      scene.add(trail)
      satModels.current[`${sat.id}_trail`] = trail

      scene.add(model)
      satModels.current[sat.id] = model
    })
  }, [satellites, selectedSat])

  /*Render */
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', backgroundColor: '#000', overflow: 'hidden' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      
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

      {/* Topleft terminal box */}
      <div style={{
        position: 'absolute', top: 30, left: 30,
        backgroundColor: '#161814',
        padding: '12px 16px',
        color: '#dfdfcb',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 18, fontWeight: 'bold',
        letterSpacing: 1, textShadow: '1px 1px #000',
        zIndex: 12, pointerEvents: 'none',
        boxShadow: '2px 2px 0px rgba(0,0,0,0.5)',
      }}>
        SECTOR LEO //<br />
        EARTH //<br />
        SATS: {satellites.length} &nbsp;|&nbsp; DEBRIS: {debrisCloud.length}
      </div>

      {/* Bottomright tag */}
      <div style={{
        position: 'absolute', bottom: 30, right: 30,
        backgroundColor: '#161814',
        padding: '10px 14px',
        color: '#dfdfcb',
        fontFamily: '"Courier New", Courier, monospace',
        fontSize: 16, fontWeight: 'bold',
        letterSpacing: 1, textShadow: '1px 1px #000',
        zIndex: 12, pointerEvents: 'none',
        boxShadow: '2px 2px 0px rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        ACM_VIEW_001 &nbsp;✦
      </div>
    </div>
  )
}