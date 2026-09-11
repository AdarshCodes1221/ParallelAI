import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Cpu,
  ArrowLeft,
  Wifi,
  WifiOff,
  AlertCircle,
  ChevronDown,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  Search,
  MessageSquare,
  Wrench,
  Activity,
  History,
  LogOut,
  LogIn,
  KeyRound,
} from 'lucide-react'
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
    currentChatId,
    currentChatTitle,
    createNewChat,
    restoreChat,
    renameChat,
    deleteChat,
    user,
    logout,
    setAuthModalOpen,
    setAuthMode,
  } = useAgentStore()

  const [mobileTab, setMobileTab] = useState<'chat' | 'tools' | 'trace' | 'history'>('chat')
  const [historySearch, setHistorySearch] = useState('')
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  // Health check & backend sync
  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then(() => setApiStatus('online'))
      .catch(() => setApiStatus('offline'))
  }, [setApiStatus])

  // Welcome message & wave
  useEffect(() => {
    const state = useAgentStore.getState()
    if (state.messages.length === 0) {
      state.addMessage({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        role: 'assistant',
        text: "👋 Hi! I'm your **Multimodal AI Agent**.\n\nUpload **PDFs**, **images**, **audio** or type any question — I'll execute the right local tools and grounded retrieval automatically.",
      })
      state.setRobotState('wave')
      setTimeout(() => state.setRobotState('idle'), 3500)
    }
  }, [])

  const startRenaming = (id: string, current: string) => {
    setEditingSessionId(id)
    setEditingTitle(current)
  }

  const saveRenaming = (id: string) => {
    if (editingTitle.trim()) {
      renameChat(id, editingTitle.trim())
    }
    setEditingSessionId(null)
    setEditingTitle('')
  }

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(historySearch.toLowerCase())
  )

  const statusInfo = {
    loading: { icon: <AlertCircle size={12} />, text: 'Checking…', color: '#ffb300' },
    online: { icon: <Wifi size={12} />, text: 'API Online', color: '#05e5a5' },
    demo: { icon: <AlertCircle size={12} />, text: 'Demo Mode', color: '#ffb300' },
    offline: { icon: <WifiOff size={12} />, text: 'API Offline', color: '#ff3b30' },
  }[apiStatus]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex flex-col lg:flex-row h-screen w-screen overflow-hidden bg-bg text-gray-100"
    >
      {/* ── Mobile Tab Navigation Bar (visible < lg) ── */}
      <div className="lg:hidden flex items-center justify-between border-b border-border bg-panel px-3 py-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-gradient-to-br from-purple to-blue flex items-center justify-center">
            <Cpu size={12} />
          </div>
          <span className="font-display font-bold text-xs">Parallel AI</span>
        </div>
        <div className="flex items-center gap-1">
          {[
            { id: 'chat', label: 'Chat', Icon: MessageSquare },
            { id: 'tools', label: 'Tools', Icon: Wrench },
            { id: 'trace', label: 'Trace', Icon: Activity },
            { id: 'history', label: 'History', Icon: History },
          ].map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setMobileTab(id as typeof mobileTab)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                mobileTab === id ? 'bg-purple text-white shadow' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Icon size={12} />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Left sidebar: Robot + Tools (visible on desktop or mobile 'tools' tab) ── */}
      <aside
        className={`
        ${mobileTab === 'tools' ? 'flex' : 'hidden lg:flex'}
        w-full lg:w-72 flex-shrink-0 flex-col h-full border-r border-border bg-bg/80 backdrop-blur-xl overflow-y-auto
      `}
      >
        {/* Logo & User Profile Pill */}
        <div className="px-4 py-3 border-b border-border flex-shrink-0 relative">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple to-blue flex items-center justify-center neon-shadow">
                <Cpu size={16} />
              </div>
              <div>
                <p className="font-display font-bold text-sm leading-none">Parallel AI</p>
                <p className="text-[10px] text-gray-500 font-mono tracking-wider">v2.0.0</p>
              </div>
            </div>

            {/* Profile Dropdown Trigger */}
            <div className="relative">
              {user ? (
                <button
                  onClick={() => setUserMenuOpen(!userMenuOpen)}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-800/80 border border-slate-700 hover:border-cyan-500/50 text-xs text-slate-200 transition"
                  title={user.email}
                >
                  <div className="w-4 h-4 rounded-full bg-cyan-500 flex items-center justify-center text-[9px] font-bold text-slate-950">
                    {(user.name || user.email).charAt(0).toUpperCase()}
                  </div>
                  <span className="max-w-[70px] truncate font-medium">
                    {user.name || user.email.split('@')[0]}
                  </span>
                  <ChevronDown size={11} className="text-slate-400" />
                </button>
              ) : (
                <button
                  onClick={() => {
                    setAuthMode('login')
                    setAuthModalOpen(true)
                  }}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20 text-xs font-semibold transition"
                >
                  <LogIn size={11} />
                  <span>Sign In</span>
                </button>
              )}

              {/* User Dropdown Menu */}
              <AnimatePresence>
                {userMenuOpen && user && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: 5 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: 5 }}
                    className="absolute right-0 top-full mt-2 w-56 p-2 rounded-xl bg-slate-900/95 border border-slate-700 shadow-2xl backdrop-blur-xl z-50 text-xs text-slate-200"
                  >
                    <div className="px-2.5 py-2 border-b border-slate-800 mb-1">
                      <p className="font-semibold text-white truncate">{user.name || 'User'}</p>
                      <p className="text-[10px] text-slate-400 truncate">{user.email}</p>
                    </div>
                    <button
                      onClick={() => {
                        setAuthMode('change_password')
                        setAuthModalOpen(true)
                        setUserMenuOpen(false)
                      }}
                      className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800/60 transition text-left"
                    >
                      <KeyRound size={13} className="text-cyan-400" />
                      <span>Change Password</span>
                    </button>
                    <button
                      onClick={() => {
                        logout()
                        setUserMenuOpen(false)
                      }}
                      className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-red-400 hover:bg-red-950/30 transition text-left mt-1 border-t border-slate-800/80"
                    >
                      <LogOut size={13} />
                      <span>Sign Out</span>
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* 3D Robot — compact in sidebar */}
        <div className="relative flex-shrink-0" style={{ height: 210 }}>
          <Robot3D className="w-full h-full" compact />
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2">
            <motion.div
              animate={{ opacity: robotState === 'thinking' ? [1, 0.4, 1] : 1 }}
              transition={{ duration: 0.8, repeat: robotState === 'thinking' ? Infinity : 0 }}
              className="text-[9px] px-2 py-0.5 rounded-full font-display font-bold uppercase tracking-wider"
              style={{
                background:
                  robotState === 'thinking' ? 'rgba(255,153,60,0.15)' : 'rgba(5,229,165,0.1)',
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
            <label className="text-[9px] font-display font-bold uppercase tracking-widest text-gray-600 mb-1 block">
              AI Model Provider
            </label>
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
              <ChevronDown
                size={12}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"
              />
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

      {/* ── Center: Chat (visible on desktop or mobile 'chat' tab) ── */}
      <main
        className={`
        ${mobileTab === 'chat' ? 'flex' : 'hidden lg:flex'}
        flex-1 flex flex-col min-w-0 w-full h-full
      `}
      >
        <ChatPanel />
      </main>

      {/* ── Right-Center: Trace (visible on desktop or mobile 'trace' tab) ── */}
      <aside
        className={`
        ${mobileTab === 'trace' ? 'flex' : 'hidden xl:flex'}
        w-full xl:w-80 flex-shrink-0 flex-col h-full bg-bg/60 backdrop-blur-xl border-r border-border
      `}
      >
        <TracePanel />
      </aside>

      {/* ── Far Right: Chat History (visible on desktop or mobile 'history' tab) ── */}
      <aside
        className={`
        ${mobileTab === 'history' ? 'flex' : 'hidden xl:flex'}
        w-full xl:w-64 flex-shrink-0 flex-col h-full border-r border-border bg-bg/80 backdrop-blur-xl flex flex-col
      `}
      >
        <div className="px-4 py-3.5 border-b border-border flex-shrink-0">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div>
              <p className="text-[10px] uppercase tracking-widest text-gray-600 font-bold">History</p>
              <p className="text-sm font-semibold truncate max-w-[130px]">{currentChatTitle}</p>
            </div>
            <button
              onClick={() => {
                createNewChat()
                setMobileTab('chat')
              }}
              className="inline-flex items-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-[10px] font-semibold text-cyan-300 hover:bg-cyan-500/20 transition-colors flex-shrink-0"
              title="Start a new conversation"
            >
              <Plus size={11} /> New
            </button>
          </div>

          {/* Search bar */}
          <div className="relative">
            <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder="Search chats…"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              className="w-full pl-7 pr-2.5 py-1 rounded-md bg-black/30 border border-border text-[11px] text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
            />
          </div>
        </div>

        {/* History list - scrollable */}
        <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
          <div className="space-y-2">
            {filteredSessions.length > 0 ? (
              filteredSessions.map((session) => {
                const isEditing = editingSessionId === session.id
                const isCurrent = currentChatId === session.id

                return (
                  <div
                    key={session.id}
                    className={`group flex items-start justify-between gap-2 rounded-lg border p-2.5 transition ${
                      isCurrent
                        ? 'border-cyan-500/50 bg-cyan-950/20 shadow-sm'
                        : 'border-border bg-black/20 hover:border-slate-700 hover:bg-black/40'
                    }`}
                  >
                    {isEditing ? (
                      <div className="flex items-center gap-1 w-full">
                        <input
                          type="text"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') saveRenaming(session.id)
                            if (e.key === 'Escape') setEditingSessionId(null)
                          }}
                          className="flex-1 px-1.5 py-0.5 bg-slate-950 border border-cyan-500 rounded text-xs text-white focus:outline-none"
                          autoFocus
                        />
                        <button
                          onClick={() => saveRenaming(session.id)}
                          className="p-1 text-emerald-400 hover:bg-emerald-950/40 rounded"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          onClick={() => setEditingSessionId(null)}
                          className="p-1 text-slate-400 hover:bg-slate-800 rounded"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={() => {
                            restoreChat(session.id)
                            setMobileTab('chat')
                          }}
                          className="text-left flex-1 min-w-0"
                          title="Load this conversation"
                        >
                          <p
                            className={`text-xs font-semibold truncate ${
                              isCurrent ? 'text-cyan-300' : 'text-gray-200'
                            }`}
                          >
                            {session.title}
                          </p>
                          <p className="text-[9px] text-gray-500 mt-0.5 truncate">
                            {new Date(session.updatedAt).toLocaleDateString('en-US', {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </p>
                        </button>

                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition flex-shrink-0">
                          <button
                            onClick={() => startRenaming(session.id, session.title)}
                            className="p-1 text-gray-400 hover:text-cyan-300 transition"
                            title="Rename chat"
                          >
                            <Edit2 size={11} />
                          </button>
                          <button
                            onClick={() => deleteChat(session.id)}
                            className="p-1 text-gray-400 hover:text-red-400 transition"
                            title="Delete chat"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )
              })
            ) : (
              <p className="text-[10px] text-gray-600 text-center py-4 italic">
                {historySearch ? 'No chats match your search.' : 'No previous chats yet.'}
              </p>
            )}
          </div>
        </div>
      </aside>
    </motion.div>
  )
}


