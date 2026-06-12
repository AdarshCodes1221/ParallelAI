import { useEffect, useRef } from 'react'
import { motion, useScroll, useTransform } from 'framer-motion'
import { Zap, ArrowRight, PlayCircle, Layers, GitBranch, HelpCircle, Activity, Box, Search, Shield, Cpu, ExternalLink, MessageSquare, Terminal } from 'lucide-react'
import { useAgentStore } from '@/store/agentStore'
import { Robot3D } from '@/components/robot/Robot3D'

// ── Particle canvas background (Refined, monochrome) ──
function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!
    let animId: number

    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    const PARTICLE_COUNT = 100
    const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
      x:    Math.random() * canvas.width,
      y:    Math.random() * canvas.height,
      r:    Math.random() * 1.5 + 0.2,
      vx:   (Math.random() - 0.5) * 0.2,
      vy:   -Math.random() * 0.3 - 0.05,
      life: Math.random() * 300 + 100,
      age:  Math.random() * 300,
    }))

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      particles.forEach((p) => {
        p.x   += p.vx
        p.y   += p.vy
        p.age += 1
        if (p.age >= p.life) {
          p.x   = Math.random() * canvas.width
          p.y   = canvas.height + 10
          p.age = 0
          p.vx  = (Math.random() - 0.5) * 0.2
          p.vy  = -Math.random() * 0.3 - 0.05
          p.life = Math.random() * 300 + 100
        }
        const alpha = Math.max(0, 1 - p.age / p.life)
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255, 255, 255, ${alpha * 0.15})`
        ctx.fill()
      })
      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(animId); window.removeEventListener('resize', resize) }
  }, [])

  return <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none" style={{ zIndex: 0 }} />
}

const NAV_LINKS = ['Features']

const FEATURES = [
  { Icon: Layers,     title: 'Multimodal Input',     desc: 'Process PDF, Audio, Images, and Text concurrently in a single execution pipeline.' },
  { Icon: GitBranch,  title: 'Autonomous Routing',   desc: 'Intent-driven orchestration dynamically routes queries to the appropriate tools.' },
  { Icon: Activity,   title: 'Execution Trace',      desc: 'Transparent reasoning logs with real-time token tracking and latency metrics.' },
  { Icon: Shield,     title: 'Enterprise Ready',     desc: 'Dockerized, highly concurrent FastAPI backend built for production workloads.' },
]

export function LandingPage() {
  const { setPage } = useAgentStore()
  const { scrollYProgress } = useScroll()
  const opacity = useTransform(scrollYProgress, [0, 0.2], [1, 0])

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="relative min-h-screen bg-black text-[#ededed] font-sans overflow-x-hidden selection:bg-[#333] selection:text-white">
      <ParticleBackground />

      {/* ── Navigation ── */}
      <nav className="fixed top-0 w-full z-50 flex items-center justify-between px-8 py-4 backdrop-blur-md bg-black/40 border-b border-white/5">
        <div className="flex items-center gap-3 cursor-pointer" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <div className="w-7 h-7 bg-white rounded-md flex items-center justify-center">
            <span className="text-black font-bold text-xs">PA</span>
          </div>
          <span className="font-semibold text-sm tracking-wide">Parallel AI</span>
        </div>
        <div className="hidden md:flex items-center gap-8 text-sm text-[#888]">
          {NAV_LINKS.map((l) => (
            <button key={l} onClick={() => scrollToSection(l.toLowerCase().replace(/ /g, '-'))} className="hover:text-white transition-colors">
              {l}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setPage('app')}
            className="px-4 py-1.5 rounded-md text-sm font-medium bg-white text-black hover:bg-gray-200 transition-colors shadow-[0_0_15px_rgba(255,255,255,0.1)]"
          >
            Launch Agent
          </button>
        </div>
      </nav>

      <main className="relative z-10 pt-32 pb-24 px-8 max-w-7xl mx-auto flex flex-col gap-32">
        
        {/* ── Hero Section ── */}
        <section id="hero" className="flex flex-col md:flex-row items-center gap-12 min-h-[75vh]">
          <div className="flex-1 space-y-6">
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-[#111] border border-white/10 text-[#aaa]"
            >
              <Cpu size={14} /> Enterprise Grade Architecture
            </motion.div>
            
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="text-5xl md:text-7xl font-semibold tracking-tight leading-[1.1]"
            >
              Autonomous <br />
              <span className="text-[#888]">Multimodal Agent</span>
            </motion.h1>
            
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-lg text-[#888] max-w-xl leading-relaxed"
            >
              The platform for cognitive reasoning across PDF, Audio, Image, and Code inputs. 
              Parallel AI dynamically plans, chains tools, and extracts insights natively.
            </motion.p>
            
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="flex items-center gap-4 pt-4"
            >
              <button
                onClick={() => setPage('app')}
                className="px-6 py-3 rounded-md bg-white text-black font-medium hover:bg-gray-200 transition-colors flex items-center gap-2"
              >
                Try Parallel AI <ArrowRight size={16} />
              </button>
              <button
                onClick={() => scrollToSection('demo')}
                className="px-6 py-3 rounded-md bg-[#111] border border-white/10 text-white font-medium hover:bg-[#1a1a1a] transition-colors flex items-center gap-2"
              >
                <PlayCircle size={16} /> Watch Demo
              </button>
            </motion.div>
          </div>
          
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.8 }}
            className="flex-1 w-full relative h-[500px] bg-[#0a0a0a] rounded-2xl border border-white/10 overflow-hidden shadow-[0_0_40px_rgba(255,255,255,0.03)]"
          >
            {/* Absolute Mascot positioning inside Hero */}
            <Robot3D className="w-full h-full" />
          </motion.div>
        </section>

        {/* ── Features Section ── */}
        <section id="features" className="space-y-12 pt-12">
          <div className="space-y-4">
            <h2 className="text-3xl font-semibold tracking-tight">Capabilities</h2>
            <p className="text-[#888] max-w-2xl">Engineered to handle complex cognitive tasks without explicit human instruction.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {FEATURES.map((f, i) => (
              <div key={i} className="p-6 rounded-xl bg-[#0a0a0a] border border-white/5 hover:border-white/15 transition-colors">
                <div className="w-10 h-10 rounded-lg bg-[#111] border border-white/10 flex items-center justify-center mb-6">
                  <f.Icon size={18} className="text-[#ccc]" />
                </div>
                <h3 className="font-medium mb-2">{f.title}</h3>
                <p className="text-sm text-[#777] leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-white/5 bg-[#050505] py-8 px-8 flex justify-between items-center text-xs text-[#555]">
        <div>&copy; {new Date().getFullYear()} Parallel AI. All rights reserved.</div>
        <div className="flex gap-4">
          <a href="#" className="hover:text-white transition-colors">Privacy</a>
          <a href="#" className="hover:text-white transition-colors">Terms</a>
          <a href="#" className="hover:text-white transition-colors">GitHub</a>
        </div>
      </footer>
    </div>
  )
}
