import { motion, AnimatePresence } from 'framer-motion'
import { useState } from 'react'
import { useAgentStore } from '@/store/agentStore'
import { Route, Terminal, FileCode2, DollarSign, CheckCircle2, Loader2, Clock } from 'lucide-react'

// ── Cost Widget ────────────────────────────────────────────
function CostWidget() {
  const { cost } = useAgentStore()
  if (!cost) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: 'auto' }}
        className="glass border border-border rounded-xl p-3 mb-4"
      >
        <p className="text-[10px] font-display uppercase tracking-widest text-gray-600 flex items-center gap-1 mb-2">
          <DollarSign size={10} className="text-green" /> Cost Estimate
        </p>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'Provider', value: cost.provider },
            { label: 'Input Tokens', value: (cost.input_tokens_est ?? 0).toLocaleString() },
            { label: 'Output Tokens', value: (cost.output_tokens_est ?? 0).toLocaleString() },
            { label: 'Est. Cost', value: cost.estimated_cost_usd > 0 ? `$${cost.estimated_cost_usd.toFixed(5)}` : '$0.00 (Free)', highlight: true },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="bg-black/20 rounded-lg p-2">
              <p className="text-[9px] text-gray-600">{label}</p>
              <p className={`text-xs font-semibold mt-0.5 ${highlight ? 'text-green' : 'text-gray-300'}`}>{value}</p>
            </div>
          ))}
        </div>
      </motion.div>
    </AnimatePresence>
  )
}

// ── Plan Steps ─────────────────────────────────────────────
function PlanSteps() {
  const { planSteps } = useAgentStore()
  if (!planSteps.length) return (
    <p className="text-gray-700 text-xs italic text-center py-4">Submit a query to see the agent tool chain</p>
  )

  return (
    <div className="flex flex-col gap-2">
      {planSteps.map((step, idx) => {
        const isRunning = step.status === 'running'
        const isDone    = step.status === 'done'
        const color = isRunning ? '#00d4ff' : isDone ? '#05e5a5' : '#1a1f3a'

        return (
          <motion.div
            key={step.step}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: idx * 0.05 }}
            className="relative flex gap-3"
          >
            {/* Connector line */}
            {idx < planSteps.length - 1 && (
              <div className="absolute left-[13px] top-7 w-px h-full" style={{ background: color, opacity: 0.3 }} />
            )}

            {/* Step number */}
            <div
              className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold transition-all duration-300"
              style={{ background: `${color}22`, border: `1px solid ${color}66`, color }}
            >
              {isRunning ? <Loader2 size={12} className="animate-spin" /> : isDone ? <CheckCircle2 size={12} /> : step.step}
            </div>

            {/* Info */}
            <div
              className="flex-1 rounded-xl p-2.5 text-xs mb-1 transition-all duration-300"
              style={{
                background: isRunning ? `${color}10` : 'rgba(14,16,34,0.6)',
                border: `1px solid ${color}33`,
                boxShadow: isRunning ? `0 0 16px ${color}25` : undefined,
              }}
            >
              <p className="font-display font-bold" style={{ color }}>
                {step.tool.replace(/_/g, ' ').toUpperCase()}
              </p>
              <p className="text-gray-600 text-[10px] mt-0.5 font-mono truncate">
                {Object.entries(step.arguments ?? {}).map(([k, v]) => `${k}: ${String(v).slice(0, 20)}`).join(' · ') || 'no args'}
              </p>
              {step.started_at && (
                <p className="text-[9px] mt-1 text-gray-500 font-mono">Started: {new Date(step.started_at).toLocaleTimeString()}</p>
              )}
              {isDone && step.execution_duration_sec != null && (
                <p className="text-[9px] mt-1 flex items-center gap-1" style={{ color }}>
                  <Clock size={8} /> {step.execution_duration_sec}s · {step.output_preview}
                </p>
              )}
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

// ── Execution Logs ─────────────────────────────────────────
function ExecutionLogs() {
  const { planSteps, messages } = useAgentStore()
  
  if (!messages.length && !planSteps.length) return (
    <p className="text-gray-700 text-xs italic text-center py-2">No logs yet...</p>
  )
  return (
    <div className="bg-black/50 rounded-xl p-3 font-mono text-[10px] text-green-400 leading-relaxed max-h-64 overflow-y-auto">
      {/* Print chat messages as logs */}
      {messages.map((m) => (
        <div key={m.id} className="mb-2">
          <span className="text-gray-500">[{new Date().toLocaleTimeString()}]</span>{' '}
          <span className={m.role === 'user' ? 'text-purple-400 font-bold' : 'text-blue-400 font-bold'}>
            {m.role === 'user' ? 'USER' : 'AGENT'}:
          </span>{' '}
          <span className="text-gray-300">
            {m.role === 'assistant' && !m.text && m.streaming ? '...' : m.text.slice(0, 200) + (m.text.length > 200 ? '...' : '')}
          </span>
          {m.files && m.files.length > 0 && (
            <div className="text-gray-500 pl-4 mt-0.5">↳ Attached: {m.files.join(', ')}</div>
          )}
        </div>
      ))}

      {/* Print tool executions */}
      {planSteps.filter(s => s.status === 'done').map((s) => (
        <div key={`tool-${s.step}`} className="mb-2 border-l border-green-900 pl-2 ml-1">
          <span className="text-gray-500">&gt;</span>{' '}
          <span className="text-white font-bold">TOOL EXECUTED: {s.tool}</span>
          {' '}[{s.execution_duration_sec}s]<br />
          <span className="text-green-500 pl-3">↳ {String(s.output_preview).slice(0, 150)}...</span>
        </div>
      ))}
    </div>
  )
}

// ── Extracted Files ────────────────────────────────────────
function ExtractedFiles() {
  const { extractedFiles } = useAgentStore()
  if (!extractedFiles.length) return (
    <p className="text-gray-700 text-xs italic text-center py-4">No files parsed yet</p>
  )
  return (
    <div className="flex flex-col gap-2">
      {extractedFiles.map((f) => (
        <div key={f.source} className="glass border border-border rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-black/20">
            <span className="text-xs font-display font-semibold text-gray-300">{f.source}</span>
            <span className="text-[9px] bg-green/10 text-green border border-green/30 rounded px-1.5 py-0.5">
              {Math.round(f.confidence * 100)}%
            </span>
          </div>
          <pre className="text-[10px] text-gray-500 font-mono p-3 overflow-x-auto whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
            {f.content}
          </pre>
        </div>
      ))}
    </div>
  )
}

// ── Trace Panel ────────────────────────────────────────────
export function TracePanel() {
  const [tab, setTab] = useState<'plan' | 'logs' | 'files'>('plan')

  const tabs = [
    { id: 'plan',  label: 'Tool Plan', Icon: Route },
    { id: 'logs',  label: 'Logs',      Icon: Terminal },
    { id: 'files', label: 'Extracted', Icon: FileCode2 },
  ] as const

  return (
    <div className="flex flex-col h-full">
      {/* Tabs header */}
      <div className="flex border-b border-border flex-shrink-0">
        {tabs.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`
              flex-1 flex items-center justify-center gap-1.5 py-3.5 text-xs font-display font-semibold
              border-b-2 transition-all duration-200
              ${tab === id ? 'border-purple text-purple-light' : 'border-transparent text-gray-700 hover:text-gray-400'}
            `}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        <CostWidget />

        <AnimatePresence mode="wait">
          {tab === 'plan' && (
            <motion.div key="plan" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <PlanSteps />
            </motion.div>
          )}
          {tab === 'logs' && (
            <motion.div key="logs" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ExecutionLogs />
            </motion.div>
          )}
          {tab === 'files' && (
            <motion.div key="files" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ExtractedFiles />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
