import { motion, AnimatePresence } from 'framer-motion'
import { useAgentStore } from '@/store/agentStore'
import {
  FileText, ScanLine, Music2, Tv2,
  AlignLeft, BarChart2, Code2, CheckCircle2, Loader2,
  type LucideIcon,
} from 'lucide-react'

const TOOLS = [
  { id: 'extract_text',       label: 'PDF Parser',      Icon: FileText,  color: '#8a3ffc' },
  { id: 'ocr',                label: 'OCR Vision',       Icon: ScanLine,  color: '#00d4ff' },
  { id: 'audio_stt',          label: 'Audio STT',        Icon: Music2,    color: '#05e5a5' },
  { id: 'youtube_transcript', label: 'YouTube Fetch',    Icon: Tv2,       color: '#ff3b30' },
  { id: 'summarizer',         label: 'Summarizer',       Icon: AlignLeft, color: '#ffb300' },
  { id: 'sentiment_analysis', label: 'Sentiment AI',     Icon: BarChart2, color: '#b07aff' },
  { id: 'code_explainer',     label: 'Code Explainer',   Icon: Code2,     color: '#00d4ff' },
]

interface ToolCardProps {
  id: string
  label: string
  Icon: LucideIcon
  color: string
  isActive: boolean
  isDone: boolean
  onClick: () => void
}

function ToolCard({ id, label, Icon, color, isActive, isDone, onClick }: ToolCardProps) {
  const { setHoverTarget } = useAgentStore()
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      whileHover={{ scale: 1.04, y: -4 }}
      onMouseEnter={() => setHoverTarget(id)}
      onMouseLeave={() => setHoverTarget(null)}
      onClick={onClick}
      className={`
        relative rounded-xl p-4 min-h-[150px] h-full flex flex-col justify-between cursor-pointer overflow-hidden scanline
        glass border transition-all duration-300
        ${isActive ? 'border-opacity-80 shadow-lg' : 'border-opacity-10'}
        hover:border-opacity-50
      `}
      style={{
        borderColor: isActive ? color : 'rgba(255,255,255,0.06)',
        boxShadow: isActive ? `0 0 28px ${color}55, 0 0 60px ${color}22` : undefined,
      }}
    >
      {/* Active glow background */}
      <AnimatePresence>
        {isActive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 rounded-xl"
            style={{ background: `radial-gradient(ellipse at center, ${color}18 0%, transparent 70%)` }}
          />
        )}
      </AnimatePresence>

      {/* Animated border on active */}
      {isActive && (
        <motion.div
          className="absolute inset-0 rounded-xl pointer-events-none"
          style={{ border: `1px solid ${color}`, opacity: 0.6 }}
          animate={{ opacity: [0.3, 0.9, 0.3] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      )}

      <div className="relative z-10 flex flex-col items-center gap-2 text-center">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{
            background: `${color}22`,
            border: `1px solid ${color}44`,
            boxShadow: isActive ? `0 0 16px ${color}55` : 'none',
          }}
        >
          {isActive && !isDone ? (
            <Loader2 size={18} color={color} className="animate-spin" />
          ) : isDone ? (
            <CheckCircle2 size={18} color={color} />
          ) : (
            <Icon size={18} color={color} />
          )}
        </div>

        <span className="text-[11px] font-display font-semibold leading-tight" style={{ color: isActive ? color : '#8892b5' }}>
          {label}
        </span>

        {isActive && (
          <motion.div
            className="w-full h-0.5 rounded-full"
            style={{ background: color }}
            animate={{ scaleX: [0, 1] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
          />
        )}
      </div>
    </motion.div>
  )
}

export function ToolGrid() {
  const { activeToolCard, planSteps, setPendingToolCommand } = useAgentStore()
  const doneTools = new Set(planSteps.filter((s) => s.status === 'done').map((s) => s.tool))

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3 p-4">
      <div className="col-span-2 sm:col-span-3 xl:col-span-4">
        <p className="text-[10px] font-display uppercase tracking-widest text-gray-600 mb-3">
          Available Tools
        </p>
      </div>
      {TOOLS.map((tool) => (
        <ToolCard
          key={tool.id}
          {...tool}
          isActive={activeToolCard === tool.id}
          isDone={doneTools.has(tool.id)}
          onClick={() => setPendingToolCommand(`/${tool.id.replace('_', '')} `)}
        />
      ))}
    </div>
  )
}
