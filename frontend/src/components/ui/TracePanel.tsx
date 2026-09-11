import { motion, AnimatePresence } from 'framer-motion'
import { useState, useEffect, useCallback } from 'react'
import { useAgentStore } from '@/store/agentStore'

import { Route, Terminal, FileCode2, DollarSign, CheckCircle2, Loader2, Clock, Copy, Check, Sparkles } from 'lucide-react'

// ── Cost Widget ────────────────────────────────────────────
function CostWidget() {
  const { cost } = useAgentStore()
  if (!cost) return null

  const isLocal = cost.provider?.toLowerCase().includes('ollama') ||
                  cost.provider?.toLowerCase().includes('local') ||
                  cost.estimated_cost_usd === 0

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: 'auto' }}
        className="glass border border-border rounded-xl p-3 mb-4"
      >
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] font-display uppercase tracking-widest text-gray-600 flex items-center gap-1">
            <DollarSign size={10} className="text-green" /> Cost Accounting
          </p>
          {isLocal && (
            <span className="text-[9px] bg-green/10 text-green border border-green/30 rounded px-1.5 py-0.2 flex items-center gap-1 font-mono">
              <Sparkles size={9} /> 100% Free / Local
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'Active Provider', value: cost.provider || 'Ollama (Local)' },
            { label: 'Input Tokens', value: (cost.input_tokens_est ?? 0).toLocaleString() },
            { label: 'Output Tokens', value: (cost.output_tokens_est ?? 0).toLocaleString() },
            {
              label: 'API Charge',
              value: isLocal ? '$0.00 (Local Inference)' : `$${cost.estimated_cost_usd.toFixed(6)}`,
              highlight: true
            },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="bg-black/20 rounded-lg p-2">
              <p className="text-[9px] text-gray-600">{label}</p>
              <p className={`text-xs font-semibold mt-0.5 truncate ${highlight ? 'text-green' : 'text-gray-300'}`}>{value}</p>
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
    <p className="text-gray-700 text-xs italic text-center py-4">Submit a query or upload a file to view current plan</p>
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
                {Object.entries(step.arguments ?? {}).map(([k, v]) => `${k}: ${String(v).slice(0, 20)}`).join(' · ') || 'current turn execution'}
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
    <p className="text-gray-700 text-xs italic text-center py-2">No execution logs yet...</p>
  )
  return (
    <div className="bg-black/50 rounded-xl p-3 font-mono text-[10px] text-green-400 leading-relaxed max-h-72 overflow-y-auto">
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
          <span className="text-white font-bold">TOOL: {s.tool.toUpperCase()}</span>
          {' '}[{s.execution_duration_sec}s]<br />
          <span className="text-green-500 pl-3">↳ {String(s.output_preview).slice(0, 150)}...</span>
        </div>
      ))}
    </div>
  )
}

// ── Extracted Files ────────────────────────────────────────
interface StoredDocument {
  id: string
  filename: string
  modality?: string
  extracted_text?: string
  confidence?: number
  duration_seconds?: number
  page_count?: number
  chunk_count?: number
  created_at?: string
  status?: string
}

function ExtractedFiles() {
  const { currentChatId, extractedFiles } = useAgentStore()
  const [serverDocs, setServerDocs] = useState<StoredDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const fetchDocuments = useCallback(async () => {
    setLoading(true)
    try {
      // First try current session documents
      let res = await fetch(`/api/documents?session_id=${currentChatId}`, {
        credentials: 'include',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
      let data = await res.json()
      let docs: StoredDocument[] = data.documents || []

      // If current session has no docs yet, also fetch user documents
      if (docs.length === 0) {
        res = await fetch('/api/documents', {
          credentials: 'include',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
        data = await res.json()
        docs = data.documents || []
      }

      setServerDocs(docs.filter((d: StoredDocument) => d.extracted_text && d.extracted_text.trim()))
    } catch (e) {
      console.warn('Failed to fetch server documents:', e)
    } finally {
      setLoading(false)
    }
  }, [currentChatId])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchDocuments()
  }, [currentChatId, extractedFiles, fetchDocuments])

  const copyText = (key: string, text: string) => {
    navigator.clipboard.writeText(text)
    setCopiedKey(key)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const downloadText = (filename: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename.replace(/\.[^/.]+$/, '')}_extracted.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Combine server documents and local ephemeral extractions (avoiding duplicates)
  const combinedItems: Array<{
    id: string
    title: string
    modality: string
    content: string
    confidence: number
    duration?: number
    pages?: number
    timestamp?: string
    status: string
  }> = []

  const seen = new Set<string>()

  for (const doc of serverDocs) {
    if (doc.extracted_text && !seen.has(doc.id)) {
      seen.add(doc.id)
      combinedItems.push({
        id: doc.id,
        title: doc.filename || 'Extracted Document',
        modality: doc.modality || 'document',
        content: doc.extracted_text,
        confidence: doc.confidence ?? 1.0,
        duration: doc.duration_seconds,
        pages: doc.page_count,
        timestamp: doc.created_at,
        status: doc.status || 'READY',
      })
    }
  }

  for (const [idx, f] of extractedFiles.entries()) {
    const key = `local-${f.source}-${idx}`
    if (!seen.has(key) && f.content) {
      seen.add(key)
      combinedItems.push({
        id: key,
        title: f.source.replace(/_/g, ' ').toUpperCase(),
        modality: f.source,
        content: f.content,
        confidence: f.confidence ?? 1.0,
        status: 'READY',
      })
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] uppercase font-mono tracking-wider text-gray-500">
          {combinedItems.length} Stored Extractions
        </span>
        <button
          onClick={fetchDocuments}
          className="text-[10px] text-purple-light hover:text-white flex items-center gap-1 font-mono transition"
          title="Reload extractions from backend"
        >
          <Clock size={10} /> Refresh
        </button>
      </div>

      {loading && !combinedItems.length ? (
        <div className="flex items-center justify-center py-8 text-gray-600 gap-2 text-xs">
          <Loader2 size={14} className="animate-spin text-purple-light" />
          <span>Loading extractions from Redis storage...</span>
        </div>
      ) : combinedItems.length === 0 ? (
        <p className="text-gray-700 text-xs italic text-center py-6">
          Upload a PDF, Image, Audio, or YouTube link to view and persist extracted data
        </p>
      ) : (
        combinedItems.map((item) => (
          <div key={item.id} className="glass border border-border rounded-xl overflow-hidden shadow-lg">
            <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-black/30">
              <div className="flex items-center gap-1.5 min-w-0">
                <FileCode2 size={12} className="text-purple-light flex-shrink-0" />
                <span className="text-xs font-display font-semibold text-gray-200 uppercase tracking-wider truncate">
                  {item.title}
                </span>
              </div>

              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span className="text-[9px] bg-purple/10 text-purple-light border border-purple/30 rounded px-1.5 py-0.5 font-mono uppercase">
                  {item.modality}
                </span>

                {item.duration ? (
                  <span className="text-[9px] bg-blue/10 text-blue border border-blue/30 rounded px-1.5 py-0.5 font-mono">
                    {item.duration}s
                  </span>
                ) : null}

                {item.pages ? (
                  <span className="text-[9px] bg-blue/10 text-blue border border-blue/30 rounded px-1.5 py-0.5 font-mono">
                    {item.pages}p
                  </span>
                ) : null}

                <span className="text-[9px] bg-green/10 text-green border border-green/30 rounded px-1.5 py-0.5 font-mono">
                  {Math.round(item.confidence * 100)}%
                </span>

                <button
                  onClick={() => copyText(item.id, item.content)}
                  className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition"
                  title="Copy extracted text"
                >
                  {copiedKey === item.id ? <Check size={11} className="text-green" /> : <Copy size={11} />}
                </button>

                <button
                  onClick={() => downloadText(item.title, item.content)}
                  className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition text-[10px]"
                  title="Download as .txt file"
                >
                  ↓
                </button>
              </div>
            </div>

            <pre className="text-[11px] text-gray-300 font-mono p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-56 overflow-y-auto leading-relaxed bg-black/20 selection:bg-purple/30">
              {item.content}
            </pre>
          </div>
        ))
      )}
    </div>
  )
}

// ── Trace Panel ────────────────────────────────────────────
export function TracePanel() {
  const [tab, setTab] = useState<'plan' | 'files' | 'logs'>('plan')

  const tabs = [
    { id: 'plan',  label: 'Tool Plan', Icon: Route },
    { id: 'files', label: 'Extracted', Icon: FileCode2 },
    { id: 'logs',  label: 'Logs',      Icon: Terminal },
  ] as const

  return (
    <div className="flex flex-col h-full">
      {/* Tabs header */}
      <div className="flex border-b border-border flex-shrink-0 bg-bg/40">
        {tabs.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`
              flex-1 flex items-center justify-center gap-1.5 py-3.5 text-xs font-display font-semibold
              border-b-2 transition-all duration-200
              ${tab === id ? 'border-purple text-purple-light bg-purple/5' : 'border-transparent text-gray-600 hover:text-gray-300'}
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
          {tab === 'files' && (
            <motion.div key="files" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ExtractedFiles />
            </motion.div>
          )}
          {tab === 'logs' && (
            <motion.div key="logs" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ExecutionLogs />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}


