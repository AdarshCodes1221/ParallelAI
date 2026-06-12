/**
 * RobotScene.tsx — Premium 3D Humanoid AI Assistant
 * 
 * Replaces the 2.5D sprite with a fully 3D, sleek, premium humanoid robot.
 * Features:
 * - Sleek white/silver chassis with dark glass visor
 * - Glowing LED eyes that independently track the cursor
 * - Humanoid arms with shoulders, elbows, and hands
 * - High-quality procedural 3D geometry
 * - Full 3D animations (breathing, head tracking, arm idle, wave, success bounce)
 */

import { useRef, useMemo, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useAgentStore } from '@/store/agentStore'
import { useMouseTracking } from '@/hooks/useMouseTracking'
import gsap from 'gsap'

// ─── Floating particles ───────────────────────────────────
function FloatingParticles({ active }: { active: boolean }) {
  const ref = useRef<THREE.Points>(null!)
  const COUNT = 250
  const [pos, col] = useMemo(() => {
    const p = new Float32Array(COUNT * 3)
    const c = new Float32Array(COUNT * 3)
    for (let i = 0; i < COUNT; i++) {
      const th = Math.random() * Math.PI * 2
      const ph = Math.acos(2 * Math.random() - 1)
      const r  = 1.5 + Math.random() * 1.5
      p[i*3]   = r * Math.sin(ph) * Math.cos(th)
      p[i*3+1] = r * Math.sin(ph) * Math.sin(th) * 0.8
      p[i*3+2] = r * Math.cos(ph)
      const t  = Math.random()
      c[i*3]   = 0.54; c[i*3+1] = 0.25 + t*0.55; c[i*3+2] = 1.0
    }
    return [p, c]
  }, [])
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.getElapsedTime()
    ref.current.rotation.y = t * (active ? 1.5 : 0.25)
    ref.current.rotation.x = Math.sin(t * 0.2) * 0.1
    const m = ref.current.material as THREE.PointsMaterial
    m.opacity = active ? 0.8 : 0.3
    m.size    = active ? 0.03 : 0.015
  })
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[pos, 3]} />
        <bufferAttribute attach="attributes-color"    args={[col, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.015} vertexColors transparent opacity={0.3}
        depthWrite={false} blending={THREE.AdditiveBlending} sizeAttenuation />
    </points>
  )
}

// ─── Holographic orbit ring ───────────────────────────────
function HoloRing({ r, speed, color, tiltX = 0.3, visible = true }: { r: number; speed: number; color: string; tiltX?: number, visible?: boolean }) {
  const ref = useRef<THREE.Mesh>(null!)
  const matRef = useRef<THREE.MeshStandardMaterial>(null!)
  
  useFrame(({ clock }) => {
    if (!visible && matRef.current.opacity <= 0) return
    ref.current.rotation.z = clock.getElapsedTime() * speed
    ref.current.rotation.x = tiltX + Math.sin(clock.getElapsedTime() * 0.2) * 0.1
    
    if (matRef.current) {
      const targetOpacity = visible ? 0.5 : 0
      matRef.current.opacity += (targetOpacity - matRef.current.opacity) * 0.05
    }
  })
  
  return (
    <mesh ref={ref}>
      <torusGeometry args={[r, 0.006, 12, 120]} />
      <meshStandardMaterial ref={matRef} color={color} emissive={color} emissiveIntensity={2.5} transparent opacity={0} />
    </mesh>
  )
}

// ─── Ground glow disc ─────────────────────────────────────
function GroundGlow() {
  const ref = useRef<THREE.Mesh>(null!)
  const { robotState } = useAgentStore()
  
  useFrame(({ clock }) => {
    if (!ref.current) return
    const mat = ref.current.material as THREE.MeshStandardMaterial
    const t = clock.getElapsedTime()
    
    if (robotState === 'thinking') {
      mat.emissiveIntensity = 0.5 + Math.sin(t * 6) * 0.2
      mat.color.setHex(0xaaaaaa)
      mat.emissive.setHex(0xaaaaaa)
    } else if (robotState === 'done') {
      mat.emissiveIntensity = 0.6 + Math.sin(t * 8) * 0.3
      mat.color.setHex(0xdddddd)
      mat.emissive.setHex(0xdddddd)
    } else {
      mat.emissiveIntensity = 0.3 + Math.sin(t * 1.5) * 0.1
      mat.color.setHex(0x444444)
      mat.emissive.setHex(0x444444)
    }
  })
  
  return (
    <mesh ref={ref} position={[0, -1.1, 0]} rotation={[-Math.PI/2, 0, 0]}>
      <circleGeometry args={[1.2, 64]} />
      <meshStandardMaterial color="#8a3ffc" emissive="#8a3ffc" emissiveIntensity={0.3}
        transparent opacity={0.15} depthWrite={false} />
    </mesh>
  )
}

// ─── Materials ───
const MATS = {
  chassis: <meshStandardMaterial color="#ffffff" roughness={0.15} metalness={0.2} />,
  joint:   <meshStandardMaterial color="#333333" roughness={0.6} metalness={0.5} />,
  visor:   <meshStandardMaterial color="#050505" roughness={0.05} metalness={0.9} envMapIntensity={2.0} />,
  eye:     <meshStandardMaterial color="#00d4ff" emissive="#00d4ff" emissiveIntensity={3} toneMapped={false} />
}

// ─── 3D Humanoid Mesh ─────────────────────────────────────
function HumanoidMesh({ mouse }: { mouse: React.MutableRefObject<{x:number;y:number}> }) {
  const rootRef = useRef<THREE.Group>(null!)
  const headRef = useRef<THREE.Group>(null!)
  const armLRef = useRef<THREE.Group>(null!)
  const armRRef = useRef<THREE.Group>(null!)
  const eyeLRef = useRef<THREE.Mesh>(null!)
  const eyeRRef = useRef<THREE.Mesh>(null!)
  const chestGlowRef = useRef<THREE.Mesh>(null!)
  
  const { robotState, hoverTarget } = useAgentStore()
  
  const blinkTimer = useRef(0)

  const toolCoordinates: Record<string, { x: number, y: number }> = {
    'extract_text': { x: -0.6, y: 0.5 },
    'ocr': { x: 0.6, y: 0.5 },
    'audio_stt': { x: -0.6, y: -0.2 },
    'youtube_transcript': { x: 0.6, y: -0.2 },
    'summarizer': { x: -0.6, y: -0.6 },
    'sentiment_analysis': { x: 0.6, y: -0.6 },
    'code_explainer': { x: 0, y: -0.7 }
  }

  useEffect(() => {
    if (!rootRef.current || !headRef.current) return

    gsap.killTweensOf(rootRef.current.position)
    gsap.killTweensOf(rootRef.current.rotation)

    if (robotState === 'done') {
      gsap.to(rootRef.current.position, { y: 0.25, duration: 0.25, yoyo: true, repeat: 3, ease: 'power2.out' })
      gsap.to(rootRef.current.rotation, { x: 0.15, duration: 0.2, yoyo: true, repeat: 3 })
    } else if (robotState === 'wave') {
      gsap.to(rootRef.current.position, { y: 0.15, duration: 0.35, yoyo: true, repeat: 1, ease: 'power2.out' })
      gsap.to(rootRef.current.rotation, { z: 0.15, duration: 0.25, yoyo: true, repeat: 3 })
    } else if (robotState === 'thinking') {
      gsap.to(rootRef.current.rotation, { z: 0.1, x: -0.1, duration: 0.6, ease: 'sine.inOut' })
      gsap.to(rootRef.current.position, { y: 0.1, duration: 0.8, ease: 'sine.inOut' })
    } else {
      gsap.to(rootRef.current.rotation, { z: 0, x: 0, duration: 0.7, ease: 'sine.inOut' })
    }
  }, [robotState])

  useFrame(({ clock }, delta) => {
    const t = clock.getElapsedTime()
    const s = robotState

    // ── Breathing (Y bobbing) ──
    const breathSpeed = s === 'thinking' ? 2.5 : 1.2
    const breathAmp = s === 'thinking' ? 0.04 : 0.02
    
    // Settle non-animated Y position back to breathing baseline
    if (s !== 'done' && s !== 'wave' && s !== 'thinking') {
      rootRef.current.position.y += ((Math.sin(t * breathSpeed) * breathAmp) - rootRef.current.position.y) * 0.1
    }

    // ── Target Coordinates (Hover vs Mouse) ──
    let targetYaw = mouse.current.x * 0.6
    let targetPitch = mouse.current.y * 0.4
    
    if (hoverTarget && toolCoordinates[hoverTarget]) {
      targetYaw = toolCoordinates[hoverTarget].x
      targetPitch = toolCoordinates[hoverTarget].y
    } else if (s === 'thinking') {
      targetYaw = 0.2
      targetPitch = -0.2
    }

    // ── Head Rotation (Smooth Tracking) ──
    const lag = s === 'thinking' ? 0.04 : 0.1
    headRef.current.rotation.y += (targetYaw - headRef.current.rotation.y) * lag
    headRef.current.rotation.x += (targetPitch - headRef.current.rotation.x) * lag

    // Subtle idle head wobble
    if (s === 'idle' && !hoverTarget) {
      headRef.current.rotation.z = Math.sin(t * 0.5) * 0.03
      headRef.current.rotation.y += Math.sin(t * 0.3) * 0.02
    }

    // ── Eyeball Tracking (Move slightly within visor) ──
    // Map yaw/pitch to slight eye translation to simulate pupils looking around
    const eyeMaxMoveX = 0.04
    const eyeMaxMoveY = 0.02
    const eyeTargetX = Math.max(-eyeMaxMoveX, Math.min(eyeMaxMoveX, targetYaw * 0.1))
    const eyeTargetY = Math.max(-eyeMaxMoveY, Math.min(eyeMaxMoveY, -targetPitch * 0.1))
    
    eyeLRef.current.position.x += ((-0.08 + eyeTargetX) - eyeLRef.current.position.x) * 0.2
    eyeLRef.current.position.y += ((0.02 + eyeTargetY) - eyeLRef.current.position.y) * 0.2
    eyeRRef.current.position.x += ((0.08 + eyeTargetX) - eyeRRef.current.position.x) * 0.2
    eyeRRef.current.position.y += ((0.02 + eyeTargetY) - eyeRRef.current.position.y) * 0.2

    // ── Blinking (Scale Y of eyes to 0 rapidly) ──
    blinkTimer.current += delta
    const blinkInterval = s === 'thinking' ? 2.0 : 4.0
    let blinkScale = 1.0
    if (blinkTimer.current > blinkInterval) {
      if (blinkTimer.current > blinkInterval + 0.15) {
        blinkTimer.current = Math.random() * -1.5
      } else {
        blinkScale = 0.1 // Closed
      }
    }
    eyeLRef.current.scale.y = blinkScale
    eyeRRef.current.scale.y = blinkScale

    // ── Arm Animations ──
    if (s === 'wave') {
      armRRef.current.rotation.z = Math.sin(t * 12) * 0.4 - 2.5 // Wave hand up high
      armRRef.current.rotation.x = -0.5
      armLRef.current.rotation.z += (0.4 - armLRef.current.rotation.z) * 0.1
    } else if (s === 'done') {
      armRRef.current.rotation.z = Math.sin(t * 10) * 0.3 - 2.8 // Excited arms up
      armLRef.current.rotation.z = -Math.sin(t * 10) * 0.3 + 2.8
    } else {
      // Idle arms gently sway
      armRRef.current.rotation.z += (-0.2 + Math.sin(t * 1.1) * 0.05 - armRRef.current.rotation.z) * 0.1
      armRRef.current.rotation.x += (Math.sin(t * 0.7) * 0.1 - armRRef.current.rotation.x) * 0.1
      armLRef.current.rotation.z += (0.2 - Math.sin(t * 1.2) * 0.05 - armLRef.current.rotation.z) * 0.1
      armLRef.current.rotation.x += (Math.sin(t * 0.8) * 0.1 - armLRef.current.rotation.x) * 0.1
    }

    // ── Chest Glow ──
    if (chestGlowRef.current) {
      const mat = chestGlowRef.current.material as THREE.MeshStandardMaterial
      if (s === 'thinking') {
        mat.emissive.setHex(0x888888)
        mat.emissiveIntensity = 1 + Math.sin(t * 5) * 1.5
      } else if (s === 'done') {
        mat.emissive.setHex(0xdddddd)
        mat.emissiveIntensity = 2 + Math.sin(t * 10) * 1
      } else {
        mat.emissive.setHex(0x444444)
        mat.emissiveIntensity = 0.5 + Math.sin(t * 2) * 0.5
      }
    }
  })

  return (
    <group ref={rootRef} position={[0, 0, 0]}>
      {/* ── Torso ── */}
      <mesh position={[0, -0.2, 0]} castShadow>
        <capsuleGeometry args={[0.26, 0.4, 16, 32]} />
        {MATS.chassis}
      </mesh>
      
      {/* Chest Ring Indicator */}
      <mesh position={[0, -0.1, 0.22]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.08, 0.015, 16, 32]} />
        <meshStandardMaterial color="#333" />
      </mesh>
      <mesh ref={chestGlowRef} position={[0, -0.1, 0.22]} rotation={[Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.07, 32]} />
        <meshStandardMaterial color="#00d4ff" emissive="#00d4ff" emissiveIntensity={1} />
      </mesh>

      {/* ── Head ── */}
      <group ref={headRef} position={[0, 0.35, 0]}>
        {/* Neck Joint */}
        <mesh position={[0, -0.15, 0]}>
          <cylinderGeometry args={[0.08, 0.1, 0.1, 16]} />
          {MATS.joint}
        </mesh>
        
        {/* Main Head Dome */}
        <mesh castShadow>
          <sphereGeometry args={[0.25, 32, 32]} />
          {MATS.chassis}
        </mesh>

        {/* Visor Cutout/Glass */}
        <mesh position={[0, 0.02, 0.12]} scale={[1.1, 0.6, 0.7]}>
          <sphereGeometry args={[0.24, 32, 32, 0, Math.PI * 2, 0, Math.PI / 2.5]} />
          {MATS.visor}
        </mesh>

        {/* Eyes inside Visor */}
        <mesh ref={eyeLRef} position={[-0.08, 0.02, 0.26]}>
          <capsuleGeometry args={[0.025, 0.02, 16, 16]} />
          {MATS.eye}
        </mesh>
        <mesh ref={eyeRRef} position={[0.08, 0.02, 0.26]}>
          <capsuleGeometry args={[0.025, 0.02, 16, 16]} />
          {MATS.eye}
        </mesh>
        
        {/* Ear Antennas */}
        {[-0.25, 0.25].map((x, i) => (
          <group key={i} position={[x, 0, 0]} rotation={[0, 0, x > 0 ? -Math.PI/2 : Math.PI/2]}>
            <mesh position={[0, 0.05, 0]}>
              <cylinderGeometry args={[0.02, 0.03, 0.1]} />
              {MATS.joint}
            </mesh>
            <mesh position={[0, 0.12, 0]}>
              <sphereGeometry args={[0.03, 16, 16]} />
              <meshStandardMaterial color="#00d4ff" emissive="#00d4ff" emissiveIntensity={1} />
            </mesh>
          </group>
        ))}
      </group>

      {/* ── Left Arm ── */}
      <group position={[-0.32, -0.05, 0]} ref={armLRef}>
        {/* Shoulder */}
        <mesh><sphereGeometry args={[0.08, 16, 16]} />{MATS.joint}</mesh>
        {/* Upper Arm */}
        <mesh position={[-0.08, -0.15, 0]} rotation={[0, 0, -0.3]}>
          <capsuleGeometry args={[0.04, 0.2, 16, 16]} />{MATS.chassis}
        </mesh>
        {/* Elbow */}
        <mesh position={[-0.14, -0.3, 0]}><sphereGeometry args={[0.05, 16, 16]} />{MATS.joint}</mesh>
        {/* Lower Arm */}
        <mesh position={[-0.14, -0.42, 0.05]} rotation={[0.4, 0, 0]}>
          <capsuleGeometry args={[0.035, 0.18, 16, 16]} />{MATS.chassis}
        </mesh>
        {/* Hand */}
        <mesh position={[-0.14, -0.55, 0.1]}><sphereGeometry args={[0.06, 16, 16]} />{MATS.joint}</mesh>
      </group>

      {/* ── Right Arm ── */}
      <group position={[0.32, -0.05, 0]} ref={armRRef}>
        {/* Shoulder */}
        <mesh><sphereGeometry args={[0.08, 16, 16]} />{MATS.joint}</mesh>
        {/* Upper Arm */}
        <mesh position={[0.08, -0.15, 0]} rotation={[0, 0, 0.3]}>
          <capsuleGeometry args={[0.04, 0.2, 16, 16]} />{MATS.chassis}
        </mesh>
        {/* Elbow */}
        <mesh position={[0.14, -0.3, 0]}><sphereGeometry args={[0.05, 16, 16]} />{MATS.joint}</mesh>
        {/* Lower Arm */}
        <mesh position={[0.14, -0.42, 0.05]} rotation={[0.4, 0, 0]}>
          <capsuleGeometry args={[0.035, 0.18, 16, 16]} />{MATS.chassis}
        </mesh>
        {/* Hand */}
        <mesh position={[0.14, -0.55, 0.1]}><sphereGeometry args={[0.06, 16, 16]} />{MATS.joint}</mesh>
      </group>
      
      {/* ── Hover Thruster Base ── */}
      <mesh position={[0, -0.55, 0]}>
        <cylinderGeometry args={[0.18, 0.12, 0.1, 32]} />
        {MATS.joint}
      </mesh>
      <mesh position={[0, -0.6, 0]}>
        <cylinderGeometry args={[0.1, 0.05, 0.05, 32]} />
        <meshStandardMaterial color="#00d4ff" emissive="#00d4ff" emissiveIntensity={2} />
      </mesh>

    </group>
  )
}

// ─────────────────────────────────────────────────────────
// Scene root — exported, placed inside <Canvas> in Robot3D
// ─────────────────────────────────────────────────────────
export function RobotSceneContent() {
  const mouse = useMouseTracking()
  const { robotState } = useAgentStore()
  const active = robotState !== 'idle'

  return (
    <>
      {/* Premium Studio Lighting */}
      <ambientLight intensity={0.6} color="#ffffff" />
      <directionalLight position={[2, 5, 5]} intensity={1.5} color="#ffffff" castShadow />
      <directionalLight position={[-3, 2, -2]} intensity={0.8} color="#a0c0ff" />
      
      {/* Colored rim lights for depth */}
      <pointLight position={[-3, 1, 1]} intensity={1.0} color="#ffffff" distance={8} />
      <pointLight position={[3, -1, 2]} intensity={0.8} color="#aaaaaa" distance={8} />

      {/* Holographic orbit rings (animated opacity) */}
      <HoloRing r={1.6} speed={0.45} color="#666666" tiltX={0.35} visible={active} />
      <HoloRing r={2.0}  speed={-0.3} color="#aaaaaa" tiltX={-0.2} visible={active} />
      <HoloRing r={2.4} speed={0.18} color="#dddddd" tiltX={0.55} visible={active} />

      {/* Dense neural particles */}
      <FloatingParticles active={active} />

      {/* Premium 3D Humanoid Mascot */}
      <HumanoidMesh mouse={mouse} />

      {/* Interactive Ground Glow */}
      <GroundGlow />
    </>
  )
}
