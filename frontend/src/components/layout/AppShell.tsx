import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { Cpu, ArrowLeft, Wifi, WifiOff, AlertCircle, ChevronDown, Plus, Trash2 } from 'lucide-react'
import { useAgentStore, GEMINI_MODELS } from '@/store/agentStore'
import type { GeminiModelValue } from '@/store/agentStore'
import { Robot3D } from '@/components/robot/Robot3D'
import { ToolGrid } from '@/components/ui/ToolGrid'
import { ChatPanel } from '@/components/ui/ChatPanel'
import { TracePanel } from '@/components/ui/TracePanel'

export function AppShell() {
  const {
    setPage,
    apiStatus,
    setApiStatus,
    robotState,
    selectedModel,
    setSelectedModel,
    sessions,
    currentChatTitle,
    messages,
    createNewChat,
    restoreChat,
    deleteChat,
  } = useAgentStore()

  // Health check
  useEffect(() => {
    fetch('http://localhost:8000/health')
      .then((r) => r.json())
      .then((d) => {
        if (d.gemini_configured || d.openai_configured) setApiStatus('online')
        else setApiStatus('demo')
      })
      .catch(() => setApiStatus('offline'))
  }, [setApiStatus])

  // Welcome message & wave
  useEffect(() => {
    const state = useAgentStore.getState()
    const alreadyHasWelcome = state.messages.some((m) =>
      m.role === 'assistant' && m.text.includes("Hi! I'm your **Multimodal AI Agent**")
    )
    if (!alreadyHasWelcome) {
      state.addMessage({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        role: 'assistant',
        text: "👋 Hi! I'm your **Multimodal AI Agent**.\n\nUpload **PDFs**, **images**, **audio** or just type a question — I'll plan and execute the right tools automatically.",
      })
      state.setRobotState('wave')
      setTimeout(() => state.setRobotState('idle'), 3500)
    }
  }, [])

  const statusInfo = {
    loading: { icon: <AlertCircle size={12} />, text: 'Checking…',   color: '#ffb300' },
    online:  { icon: <Wifi size={12} />,        text: 'API Online',  color: '#05e5a5' },
    demo:    { icon: <AlertCircle size={12} />, text: 'Demo Mode',   color: '#ffb300' },
    offline: { icon: <WifiOff size={12} />,     text: 'API Offline', color: '#ff3b30' },
  }[apiStatus]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex h-screen w-screen overflow-hidden"
    >
      {/* ── Left sidebar: Robot + Tools (FIXED) ── */}
      <aside className="w-72 flex-shrink-0 flex flex-col h-full border-r border-border bg-bg/80 backdrop-blur-xl overflow-y-auto">

        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-border flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple to-blue flex items-center justify-center neon-shadow">
            <Cpu size={16} />
          </div>
          <div>
            <p className="font-display font-bold text-sm leading-none">Parallel AI</p>
            <p className="text-[10px] text-gray-500 font-mono tracking-wider">v2.0.0</p>
          </div>
        </div>

        {/* 3D Robot — compact in sidebar */}
        <div className="relative flex-shrink-0" style={{ height: 240 }}>
          <Robot3D className="w-full h-full" compact />
          {/* State badge */}
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2">
            <motion.div
              animate={{ opacity: robotState === 'thinking' ? [1, 0.4, 1] : 1 }}
              transition={{ duration: 0.8, repeat: robotState === 'thinking' ? Infinity : 0 }}
              className="text-[9px] px-2 py-0.5 rounded-full font-display font-bold uppercase tracking-wider"
              style={{
                background: robotState === 'thinking' ? 'rgba(255,153,60,0.15)' : 'rgba(5,229,165,0.1)',
                border: `1px solid ${robotState === 'thinking' ? '#ff993c' : '#05e5a5'}44`,
                color: robotState === 'thinking' ? '#ff993c' : '#05e5a5',
              }}
            >
              {robotState === 'thinking' ? '⚡ Thinking…' : robotState === 'done' ? '✓ Done' : '● Idle'}
            </motion.div>
          </div>
        </div>

        {/* Model Selector */}
        <div className="px-3 pb-3 pt-1 flex-shrink-0">
          <div className="relative">
            <label className="text-[9px] font-display font-bold uppercase tracking-widest text-gray-600 mb-1 block">AI Model</label>
            <div className="relative">
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value as GeminiModelValue)}
                className="w-full appearance-none bg-black/30 border border-border rounded-lg px-3 py-2 text-[11px] text-gray-200 font-mono cursor-pointer focus:outline-none focus:border-purple transition-colors"
                style={{ backgroundImage: 'none' }}
              >
                {GEMINI_MODELS.map((m) => (
                  <option key={m.value} value={m.value} className="bg-[#0d0d14] text-gray-200">
                    {m.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* Tool cards */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <ToolGrid />
        </div>

        {/* Footer: status + back */}
        <div className="border-t border-border px-4 py-3 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-1.5 text-[11px]" style={{ color: statusInfo.color }}>
            {statusInfo.icon}
            {statusInfo.text}
          </div>
          <button
            onClick={() => setPage('landing')}
            className="flex items-center gap-1 text-[11px] text-gray-600 hover:text-gray-300 transition-colors"
          >
            <ArrowLeft size={11} /> Home
          </button>
        </div>
      </aside>

      {/* ── Center: Chat ── */}
      <main className="flex-1 flex flex-col min-w-0 border-r border-border">
        <ChatPanel />
      </main>

      {/* ── Right-Center: Trace ── */}
      <aside className="w-80 flex-shrink-0 flex flex-col h-full bg-bg/60 backdrop-blur-xl border-r border-border">
        <TracePanel />
      </aside>

      {/* ── Far Right: Chat History ── */}
      <aside className="w-64 flex-shrink-0 flex flex-col h-full border-r border-border bg-bg/80 backdrop-blur-xl">
        <div className="px-4 py-3.5 border-b border-border flex-shrink-0">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div>
              <p className="text-[10px] uppercase tracking-widest text-gray-600">History</p>
              <p className="text-sm font-semibold truncate">{currentChatTitle}</p>
            </div>
            <button
              onClick={createNewChat}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[10px] font-semibold text-gray-200 hover:border-purple hover:text-purple transition-colors flex-shrink-0"
              title="Start a new conversation"
            >
              <Plus size={11} /> New
            </button>
          </div>
        </div>

        {/* History list - scrollable */}
        <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
          <div className="space-y-2">
            {sessions.length > 0 ? sessions.map((session) => (
              <div
                key={session.id}
                className="group flex items-start justify-between gap-2 rounded-lg border border-border bg-black/20 p-2.5 transition hover:border-purple hover:bg-black/40"
              >
                <button
                  onClick={() => restoreChat(session.id)}
                  className="text-left flex-1 min-w-0"
                  title="Load this conversation"
                >
                  <p className="text-xs font-semibold text-gray-200 truncate">{session.title}</p>
                  <p className="text-[9px] text-gray-600 mt-0.5 truncate">
                    {new Date(session.updatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </p>
                </button>
                <button
                  onClick={() => deleteChat(session.id)}
                  className="text-gray-600 hover:text-red transition flex-shrink-0 opacity-0 group-hover:opacity-100"
                  title="Delete this conversation"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            )) : (
              <p className="text-[10px] text-gray-600 text-center py-4 italic">No previous chats yet.\nStart a conversation!</p>
            )}
          </div>
        </div>
      </aside>
    </motion.div>
  )
}
