import { useEffect, useRef } from 'react'
import * as THREE from 'three'

const EARTH_RADIUS = 1.0
const DEG = Math.PI / 180

/* Convert lat/lon/alt to 3D position */
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

/* Low-poly icosphere for PS2 feel */
function createEarth() {
  const geo = new THREE.IcosahedronGeometry(EARTH_RADIUS, 3) // detail=3 → PS2 chunky
  const mat = new THREE.MeshPhongMaterial({
    color:     0x0a2a1a,
    emissive:  0x001208,
    wireframe: false,
    flatShading: true,          // flat shading = PS2 polygon look
    transparent: true,
    opacity: 0.92,
  })
  return new THREE.Mesh(geo, mat)
}

/* Wireframe grid overlay */
function createGrid() {
  const geo = new THREE.IcosahedronGeometry(EARTH_RADIUS * 1.002, 3)
  const mat = new THREE.MeshBasicMaterial({
    color: 0x0d3020,
    wireframe: true,
    transparent: true,
    opacity: 0.35,
  })
  return new THREE.Mesh(geo, mat)
}

/* Atmosphere glow */
function createAtmosphere() {
  const geo = new THREE.SphereGeometry(EARTH_RADIUS * 1.08, 32, 32)
  const mat = new THREE.MeshPhongMaterial({
    color: 0x00ff88,
    transparent: true,
    opacity: 0.04,
    side: THREE.BackSide,
  })
  return new THREE.Mesh(geo, mat)
}

export default function Globe3D({ satellites, debrisCloud, selectedSat, onSelectSat }) {
  const mountRef   = useRef(null)
  const sceneRef   = useRef(null)
  const satMeshes  = useRef({})
  const debrisMesh = useRef(null)
  const frameRef   = useRef(null)
  const earthRef   = useRef(null)

  /* ── Init scene ──────────────────────────────────────────────────────────── */
  useEffect(() => {
    const W = mountRef.current.clientWidth
    const H = mountRef.current.clientHeight

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true }) // no AA = PS2
    renderer.setSize(W, H)
    renderer.setPixelRatio(1)  // intentionally 1x for chunky pixel look
    mountRef.current.appendChild(renderer.domElement)

    // Scene + camera
    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, W / H, 0.01, 100)
    camera.position.set(0, 0, 2.8)
    sceneRef.current = { scene, camera, renderer }

    // Lighting
    const ambient = new THREE.AmbientLight(0x00ff88, 0.15)
    const sun     = new THREE.DirectionalLight(0xffffff, 0.8)
    sun.position.set(5, 3, 5)
    scene.add(ambient, sun)

    // Star field
    const starGeo = new THREE.BufferGeometry()
    const starVerts = []
    for (let i = 0; i < 3000; i++) {
      const v = new THREE.Vector3(
        (Math.random() - 0.5) * 80,
        (Math.random() - 0.5) * 80,
        (Math.random() - 0.5) * 80
      )
      if (v.length() > 5) starVerts.push(v.x, v.y, v.z)
    }
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starVerts, 3))
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x334433, size: 0.04 }))
    scene.add(stars)

    // Earth
    const earth = createEarth()
    const grid  = createGrid()
    const atmo  = createAtmosphere()
    earthRef.current = earth
    scene.add(earth, grid, atmo)

    // Equator ring
    const ringGeo = new THREE.TorusGeometry(EARTH_RADIUS * 1.01, 0.001, 4, 64)
    const ringMat = new THREE.MeshBasicMaterial({ color: 0x00ff88, transparent: true, opacity: 0.2 })
    scene.add(new THREE.Mesh(ringGeo, ringMat))

    // Mouse drag to rotate
    let isDragging = false, prevMouse = { x: 0, y: 0 }
    const onDown = e => { isDragging = true; prevMouse = { x: e.clientX, y: e.clientY } }
    const onUp   = () => { isDragging = false }
    const onMove = e => {
  if (!isDragging) return
  const dx = e.clientX - prevMouse.x
  const dy = e.clientY - prevMouse.y

  // Rotate the whole scene group, not just earth
  scene.rotation.y += dx * 0.005
  scene.rotation.x += dy * 0.005
  prevMouse = { x: e.clientX, y: e.clientY }
}
    renderer.domElement.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('mousemove', onMove)

    // Scroll to zoom
    const onWheel = e => {
      camera.position.z = Math.max(1.5, Math.min(5, camera.position.z + e.deltaY * 0.002))
    }
    renderer.domElement.addEventListener('wheel', onWheel)

    // Animate
    const animate = () => {
      frameRef.current = requestAnimationFrame(animate)
      if (!isDragging) earth.rotation.y += 0.0008
      grid.rotation.copy(earth.rotation)
      atmo.rotation.copy(earth.rotation)
      renderer.render(scene, camera)
    }
    animate()

    // Resize
    const onResize = () => {
      const w = mountRef.current?.clientWidth  || W
      const h = mountRef.current?.clientHeight || H
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

  /* ── Update debris cloud (instanced mesh for perf) ───────────────────────── */
  useEffect(() => {
    if (!sceneRef.current || !debrisCloud) return
    const { scene } = sceneRef.current

    // Remove old
    if (debrisMesh.current) {
      scene.remove(debrisMesh.current)
      debrisMesh.current.geometry.dispose()
    }

    if (debrisCloud.length === 0) return

    const count = debrisCloud.length
    const geo   = new THREE.SphereGeometry(0.003, 3, 3)  // tiny low-poly sphere
    const mat   = new THREE.MeshBasicMaterial({ color: 0xff3333 })
    const mesh  = new THREE.InstancedMesh(geo, mat, count)

    const dummy = new THREE.Object3D()
    debrisCloud.forEach(([, lat, lon, alt], i) => {
      const pos = latLonToVec3(lat, lon, alt)
      dummy.position.copy(pos)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
    debrisMesh.current = mesh
    scene.add(mesh)
  }, [debrisCloud])

  /* ── Update satellite markers ────────────────────────────────────────────── */
  useEffect(() => {
    if (!sceneRef.current || !satellites) return
    const { scene } = sceneRef.current

    // Remove old sat meshes
    Object.values(satMeshes.current).forEach(m => scene.remove(m))
    satMeshes.current = {}

    satellites.forEach(sat => {
      const pos    = latLonToVec3(sat.lat, sat.lon, sat.alt_km || 400)
      const isSelected = selectedSat?.id === sat.id

      // Satellite body — diamond shape (low-poly)
      const geo  = new THREE.OctahedronGeometry(isSelected ? 0.022 : 0.015, 0)
      const color = sat.status === 'EVADING'  ? 0xffaa00
                  : sat.status === 'EOL'       ? 0x666666
                  : sat.status === 'CRITICAL'  ? 0xff3333
                  : 0x00ff88
      const mat  = new THREE.MeshBasicMaterial({ color, wireframe: false })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.copy(pos)
      mesh.userData = { sat }

      // Pulse ring for selected
      if (isSelected) {
        const rGeo = new THREE.RingGeometry(0.025, 0.03, 6)
        const rMat = new THREE.MeshBasicMaterial({ color: 0x00ff88, side: THREE.DoubleSide, transparent: true, opacity: 0.6 })
        const ring = new THREE.Mesh(rGeo, rMat)
        ring.position.copy(pos)
        ring.lookAt(0, 0, 0)
        scene.add(ring)
        satMeshes.current[`${sat.id}_ring`] = ring
      }

      scene.add(mesh)
      satMeshes.current[sat.id] = mesh
    })
  }, [satellites, selectedSat])

  return (
    <div
      ref={mountRef}
      style={{ width: '100%', height: '100%', cursor: 'grab' }}
    />
  )
}