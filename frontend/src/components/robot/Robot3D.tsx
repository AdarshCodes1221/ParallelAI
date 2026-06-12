import { Canvas } from '@react-three/fiber'
import { Suspense } from 'react'
import { RobotSceneContent } from './RobotScene'

interface Props {
  className?: string
  style?: React.CSSProperties
  compact?: boolean
}

export function Robot3D({ className = '', style, compact = false }: Props) {
  return (
    <Canvas
      className={className}
      style={style}
      camera={{ position: [0, 0.15, 4.2], fov: compact ? 36 : 44 }}
      gl={{
        antialias: true,
        alpha: true,            // transparent background — page bg shows through
        powerPreference: 'high-performance',
      }}
      dpr={[1, 1.5]}
      onCreated={({ gl }) => {
        gl.setClearColor(0x000000, 0)  // fully transparent clear
      }}
    >
      <Suspense fallback={null}>
        <RobotSceneContent />
      </Suspense>
    </Canvas>
  )
}
