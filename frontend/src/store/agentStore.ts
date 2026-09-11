import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Purge any legacy persisted user chat/session/message data from localStorage on startup
if (typeof window !== 'undefined') {
  try {
    const raw = localStorage.getItem('agent-chat-storage')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed?.state) {
        let dirty = false
        for (const k of ['messages', 'sessions', 'currentChatId', 'currentChatTitle', 'extractedFiles', 'planSteps', 'cost', 'user', 'authStatus']) {
          if (k in parsed.state) {
            delete parsed.state[k]
            dirty = true
          }
        }
        if (dirty) {
          localStorage.setItem('agent-chat-storage', JSON.stringify(parsed))
        }
      }
    }
  } catch {
    // ignore storage access errors
  }
}

export type RobotState = 'idle' | 'thinking' | 'done' | 'wave' | 'audio'
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'
export type AuthMode = 'login' | 'signup' | 'forgot' | 'reset' | 'change_password'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  files?: string[]
  streaming?: boolean
  audioUrl?: string
}

export interface ToolStep {
  step: number
  tool: string
  arguments: Record<string, unknown>
  started_at?: string
  execution_duration_sec?: number
  output_preview?: string
  status: 'pending' | 'running' | 'done'
}

export interface CostInfo {
  provider: string
  input_tokens_est: number
  output_tokens_est: number
  estimated_cost_usd: number
}

export interface ExtractedFile {
  source: string
  content: string
  confidence: number
}

export interface ChatSession {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
  planSteps: ToolStep[]
  extractedFiles: ExtractedFile[]
  cost: CostInfo | null
}

// Available AI models
export const GEMINI_MODELS = [
  { value: 'ollama/llama3.2:3b', label: 'Ollama Llama 3.2:3B 🦙 (100% Local / Free)' },
  { value: 'models/gemini-2.5-flash', label: 'Gemini 2.5 Flash ⚡' },
  { value: 'models/gemini-2.5-pro', label: 'Gemini 2.5 Pro 🧠' },
  { value: 'models/gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  { value: 'models/gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash Lite (Free)' },
  { value: 'models/gemini-3.5-flash', label: 'Gemini 3.5 Flash ✨' },
] as const

export type GeminiModelValue = typeof GEMINI_MODELS[number]['value']

export interface User {
  id: string
  email: string
  name?: string
  created_at?: string
}

// Helper to extract CSRF cookie from document.cookie
export function getCsrfToken(): string {
  if (typeof document === 'undefined') return ''
  const match = document.cookie.match(/(^|;)\s*csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[2]) : ''
}

// Robust error response reader
async function parseErrorResponse(res: Response, defaultMsg: string): Promise<string> {
  try {
    const contentType = res.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      const data = await res.json()
      if (typeof data.detail === 'string') {
        const lower = data.detail.toLowerCase()
        if (lower.includes('already exists') || lower.includes('already registered')) {
          return 'An account with this email already exists. Sign in instead.'
        }
        return data.detail
      }
      if (Array.isArray(data.detail)) {
        return data.detail.map((e: Record<string, unknown>) => String(e.msg || JSON.stringify(e))).join(', ')
      }
      if (data.message) return data.message
    }
    const text = await res.text()
    if (text && !text.startsWith('<')) {
      if (text.toLowerCase().includes('already exists') || text.toLowerCase().includes('already registered')) {
        return 'An account with this email already exists. Sign in instead.'
      }
      return text.slice(0, 200)
    }
  } catch {
    // fallback
  }
  return defaultMsg
}

let _signupInFlight = false
let _loginInFlight = false
let _authEpoch = 0
let _fetchSessionsEpoch = 0

interface AgentStore {
  // Navigation & Auth
  page: 'landing' | 'app'
  setPage: (p: 'landing' | 'app') => void
  user: User | null
  authStatus: AuthStatus
  authModalOpen: boolean
  authMode: AuthMode
  setAuthModalOpen: (open: boolean) => void
  setAuthMode: (mode: AuthMode) => void
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string, name?: string) => Promise<{ status: string; message: string; user?: User }>
  logout: () => Promise<void>
  forgotPassword: (email: string) => Promise<string>
  resetPassword: (token: string, newPassword: string) => Promise<string>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  checkAuth: () => Promise<void>
  fetchSessions: () => Promise<void>
  resetUserScopedState: () => void

  // Robot
  robotState: RobotState
  setRobotState: (s: RobotState) => void
  activeToolCard: string | null
  setActiveToolCard: (t: string | null) => void
  hoverTarget: string | null
  setHoverTarget: (t: string | null) => void
  pendingToolCommand: string | null
  setPendingToolCommand: (t: string | null) => void

  // Chat session metadata
  currentChatId: string
  currentChatTitle: string
  currentChatCreatedAt: number
  sessions: ChatSession[]
  createNewChat: () => void
  restoreChat: (sessionId: string) => Promise<void>
  renameChat: (sessionId: string, newTitle: string) => Promise<void>
  deleteChat: (sessionId: string) => Promise<void>
  clearCurrentConversation: () => void
  setCurrentChatTitle: (title: string) => void
  saveCurrentSessionToHistory: () => void

  // Chat
  messages: Message[]
  addMessage: (m: Message) => void
  appendToken: (id: string, token: string) => void
  setAudioUrl: (id: string, url: string) => void

  // Plan & trace
  planSteps: ToolStep[]
  setPlanSteps: (steps: ToolStep[]) => void
  updateStepStatus: (step: number, status: 'running' | 'done', duration?: number, preview?: string) => void
  cost: CostInfo | null
  setCost: (c: CostInfo | null) => void
  extractedFiles: ExtractedFile[]
  setExtractedFiles: (f: ExtractedFile[]) => void

  // API status
  apiStatus: 'loading' | 'online' | 'demo' | 'offline'
  setApiStatus: (s: 'loading' | 'online' | 'demo' | 'offline') => void

  // Model selection
  selectedModel: GeminiModelValue
  setSelectedModel: (m: GeminiModelValue) => void
}

const deriveTitle = (text: string) => {
  const normalized = text.trim().toLowerCase()
  if (!normalized) return 'New Chat'
  if (normalized.includes('resume')) return 'Resume Analysis'
  if (normalized.includes('summarize')) return 'PDF Summary'
  if (normalized.includes('transcribe') || normalized.includes('audio') || normalized.includes('speech')) return 'Audio Transcription'
  if (normalized.includes('youtube') || normalized.includes('video')) return 'YouTube Summary'
  if (normalized.includes('code')) return 'Code Review'
  if (normalized.includes('sentiment')) return 'Sentiment Analysis'
  return normalized
    .split(/\s+/)
    .slice(0, 4)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

const createEmptyChat = () => {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return {
    currentChatId: id,
    currentChatTitle: 'New Chat',
    currentChatCreatedAt: Date.now(),
    messages: [] as Message[],
    planSteps: [] as ToolStep[],
    cost: null as CostInfo | null,
    extractedFiles: [] as ExtractedFile[],
  }
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      page: 'landing',
      setPage: (page) => set({ page }),

      user: null,
      authStatus: 'loading',
      authModalOpen: false,
      authMode: 'login',
      setAuthModalOpen: (authModalOpen) => set({ authModalOpen }),
      setAuthMode: (authMode) => set({ authMode }),

      resetUserScopedState: () => {
        const fresh = createEmptyChat()
        set({
          user: null,
          authStatus: 'unauthenticated',
          currentChatId: fresh.currentChatId,
          currentChatTitle: fresh.currentChatTitle,
          currentChatCreatedAt: fresh.currentChatCreatedAt,
          messages: [],
          planSteps: [],
          cost: null,
          extractedFiles: [],
          sessions: [],
          activeToolCard: null,
          hoverTarget: null,
          pendingToolCommand: null,
          robotState: 'idle',
        })
      },

      login: async (email: string, password: string) => {
        if (_loginInFlight) return
        _loginInFlight = true
        const epoch = ++_authEpoch
        try {
          const res = await fetch('/api/auth/login', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify({ email, password }),
          })
          if (!res.ok) {
            const errMsg = await parseErrorResponse(res, 'Login failed. Please check your credentials.')
            throw new Error(errMsg)
          }
          if (epoch !== _authEpoch) return
          const data = await res.json()
          get().resetUserScopedState()
          set({ user: data.user, authStatus: 'authenticated', page: 'app' })
          await get().fetchSessions()
        } finally {
          _loginInFlight = false
        }
      },

      signup: async (email: string, password: string, name?: string) => {
        if (_signupInFlight) return { status: 'in_flight', message: '' }
        _signupInFlight = true
        try {
          const res = await fetch('/api/auth/signup', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify({ email, password, name }),
          })
          if (!res.ok) {
            const errMsg = await parseErrorResponse(res, 'Registration failed. Please check your details.')
            throw new Error(errMsg)
          }
          const data = await res.json()
          // CRITICAL: Registration does NOT authenticate the user or create a chat/session
          return data
        } finally {
          _signupInFlight = false
        }
      },

      logout: async () => {
        ++_authEpoch
        try {
          const csrf = getCsrfToken()
          await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'X-CSRF-Token': csrf,
              'X-Requested-With': 'XMLHttpRequest',
            },
          })
        } catch {
          // ignore network errors on logout
        }
        get().resetUserScopedState()
        set({ page: 'landing' })
      },

      forgotPassword: async (email: string): Promise<string> => {
        const res = await fetch('/api/auth/forgot-password', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ email }),
        })
        if (!res.ok) {
          const errMsg = await parseErrorResponse(res, 'Could not send password reset link.')
          throw new Error(errMsg)
        }
        const data = await res.json()
        return data.message || "If an account with that email exists, a password reset link has been sent."
      },

      resetPassword: async (token: string, newPassword: string): Promise<string> => {
        const res = await fetch('/api/auth/reset-password', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ token, new_password: newPassword }),
        })
        if (!res.ok) {
          const errMsg = await parseErrorResponse(res, 'That password reset link is invalid or has expired. Please request a new one.')
          throw new Error(errMsg)
        }
        const data = await res.json()
        return data.message || "Password has been successfully updated. You can now log in."
      },

      changePassword: async (currentPassword: string, newPassword: string) => {
        const csrf = getCsrfToken()
        const res = await fetch('/api/auth/change-password', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrf,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        })
        if (!res.ok) {
          const errMsg = await parseErrorResponse(res, 'Password change failed.')
          throw new Error(errMsg)
        }
      },

      checkAuth: async () => {
        const epoch = ++_authEpoch
        try {
          const res = await fetch('/api/auth/me', {
            credentials: 'include',
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
            },
          })
          if (epoch !== _authEpoch) return
          if (res.ok) {
            const data = await res.json()
            const currentUser = get().user
            const userChanged = !currentUser || currentUser.id !== data.user.id
            if (userChanged) {
              get().resetUserScopedState()
              set({ user: data.user, authStatus: 'authenticated', page: 'app' })
              await get().fetchSessions()
            } else {
              set({ user: data.user, authStatus: 'authenticated', page: 'app' })
              await get().fetchSessions()
            }
          } else {
            get().resetUserScopedState()
          }
        } catch {
          if (epoch === _authEpoch) {
            get().resetUserScopedState()
          }
        }
      },

      fetchSessions: async () => {
        const epoch = ++_fetchSessionsEpoch
        try {
          const res = await fetch('/api/sessions', {
            credentials: 'include',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
          })
          if (epoch !== _fetchSessionsEpoch) return
          if (res.ok) {
            const data = await res.json()
            const backendSessions: ChatSession[] = Array.isArray(data.sessions)
              ? data.sessions.map((s: Record<string, unknown>) => ({
                  id: String(s.id),
                  title: String(s.title || 'Chat'),
                  createdAt: s.created_at ? new Date(String(s.created_at)).getTime() : Date.now(),
                  updatedAt: s.updated_at ? new Date(String(s.updated_at)).getTime() : Date.now(),
                  messages: [],
                  planSteps: [],
                  extractedFiles: [],
                  cost: null,
                }))
              : []

            set({ sessions: backendSessions })

            const state = get()
            const currentExists = backendSessions.some((s) => s.id === state.currentChatId)
            if (!currentExists && backendSessions.length > 0) {
              await get().restoreChat(backendSessions[0].id)
            } else if (backendSessions.length === 0) {
              get().createNewChat()
            }
          }
        } catch {
          // offline or background sync failure
        }
      },

      robotState: 'idle',
      setRobotState: (robotState) => set({ robotState }),
      activeToolCard: null,
      setActiveToolCard: (activeToolCard) => set({ activeToolCard }),
      hoverTarget: null,
      setHoverTarget: (hoverTarget) => set({ hoverTarget }),
      pendingToolCommand: null,
      setPendingToolCommand: (pendingToolCommand) => set({ pendingToolCommand }),

      currentChatId: createEmptyChat().currentChatId,
      currentChatTitle: 'New Chat',
      currentChatCreatedAt: createEmptyChat().currentChatCreatedAt,
      sessions: [],
      createNewChat: () => {
        const state = get()
        if (state.messages.length || state.planSteps.length || state.extractedFiles.length) {
          state.saveCurrentSessionToHistory()
        }
        const newChat = createEmptyChat()
        set({
          currentChatId: newChat.currentChatId,
          currentChatTitle: newChat.currentChatTitle,
          currentChatCreatedAt: newChat.currentChatCreatedAt,
          messages: [],
          planSteps: [],
          cost: null,
          extractedFiles: [],
        })
      },
      restoreChat: async (sessionId: string) => {
        const state = get()
        const session = state.sessions.find((s) => s.id === sessionId)

        if (state.messages.length || state.planSteps.length || state.extractedFiles.length) {
          state.saveCurrentSessionToHistory()
        }

        // Fetch detailed message history from backend for this session
        try {
          const res = await fetch(`/api/sessions/${sessionId}`, {
            credentials: 'include',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
          })
          if (res.ok) {
            const data = await res.json()
            const backendMessages: Message[] = (data.messages || []).map((m: Record<string, unknown>, idx: number) => ({
              id: `msg-${sessionId}-${idx}-${Date.now()}`,
              role: (m.role || 'assistant') as 'user' | 'assistant',
              text: String(m.content || ''),
            }))

            const activeTitle = data.session?.title || session?.title || 'Chat'
            const activeCreatedAt = data.session?.created_at
              ? new Date(data.session.created_at).getTime()
              : session?.createdAt || Date.now()

            set({
              currentChatId: sessionId,
              currentChatTitle: activeTitle,
              currentChatCreatedAt: activeCreatedAt,
              messages: backendMessages,
              planSteps: [],
              cost: null,
              extractedFiles: [],
            })
            return
          }
        } catch {
          // fallback to client session
        }

        if (!session) return
        set({
          currentChatId: session.id,
          currentChatTitle: session.title,
          currentChatCreatedAt: session.createdAt,
          messages: session.messages || [],
          planSteps: session.planSteps || [],
          cost: session.cost || null,
          extractedFiles: session.extractedFiles || [],
        })
      },
      renameChat: async (sessionId: string, newTitle: string) => {
        const trimmed = newTitle.trim()
        if (!trimmed) return
        set((state) => ({
          currentChatTitle: state.currentChatId === sessionId ? trimmed : state.currentChatTitle,
          sessions: state.sessions.map((s) => (s.id === sessionId ? { ...s, title: trimmed } : s)),
        }))
        try {
          const csrf = getCsrfToken()
          await fetch(`/api/sessions/${sessionId}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-Token': csrf,
              'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify({ title: trimmed }),
          })
        } catch {
          // ignore network failure
        }
      },
      deleteChat: async (sessionId: string) => {
        try {
          const csrf = getCsrfToken()
          await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE',
            credentials: 'include',
            headers: {
              'X-CSRF-Token': csrf,
              'X-Requested-With': 'XMLHttpRequest',
            },
          })
        } catch {
          // ignore network failure
        }
        const remaining = get().sessions.filter((s) => s.id !== sessionId)
        set({ sessions: remaining })
        if (get().currentChatId === sessionId) {
          if (remaining.length > 0) {
            await get().restoreChat(remaining[0].id)
          } else {
            get().createNewChat()
          }
        }
      },
      clearCurrentConversation: () => {
        const state = get()
        if (state.messages.length || state.planSteps.length || state.extractedFiles.length) {
          state.saveCurrentSessionToHistory()
        }
        const fresh = createEmptyChat()
        set({
          currentChatId: fresh.currentChatId,
          currentChatTitle: fresh.currentChatTitle,
          currentChatCreatedAt: fresh.currentChatCreatedAt,
          messages: [],
          planSteps: [],
          cost: null,
          extractedFiles: [],
        })
      },
      setCurrentChatTitle: (title) => set({ currentChatTitle: title }),
      saveCurrentSessionToHistory: () => {
        const state = get()
        if (
          !state.messages.length &&
          !state.planSteps.length &&
          !state.extractedFiles.length
        ) {
          return
        }

        const firstUser = state.messages.find((m) => m.role === 'user')
        if (!firstUser && !state.extractedFiles.length) {
          return
        }
        const title = state.currentChatTitle !== 'New Chat'
          ? state.currentChatTitle
          : firstUser
            ? deriveTitle(firstUser.text)
            : 'New Chat'

        const session: ChatSession = {
          id: state.currentChatId,
          title,
          createdAt: state.currentChatCreatedAt,
          updatedAt: Date.now(),
          messages: state.messages,
          planSteps: state.planSteps,
          extractedFiles: state.extractedFiles,
          cost: state.cost,
        }

        const existing = state.sessions.filter((item) => item.id !== session.id)
        const sessions = [session, ...existing].slice(0, 15)
        set({ sessions })
      },

      messages: [],
      addMessage: (m) =>
        set((state) => {
          const updatedTitle =
            m.role === 'user' && state.currentChatTitle === 'New Chat'
              ? deriveTitle(m.text)
              : state.currentChatTitle

          return {
            messages: [...state.messages, m],
            currentChatTitle: updatedTitle,
          }
        }),
      appendToken: (id, token) =>
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === id ? { ...m, text: m.text + token } : m,
          ),
        })),
      setAudioUrl: (id, url) =>
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === id ? { ...m, audioUrl: url } : m,
          ),
        })),

      planSteps: [],
      setPlanSteps: (planSteps) =>
        set({ planSteps: planSteps.map((s) => ({ ...s, status: 'pending' })) }),
      updateStepStatus: (step, status, duration, preview) =>
        set((state) => ({
          planSteps: state.planSteps.map((st) =>
            st.step === step
              ? {
                  ...st,
                  status,
                  execution_duration_sec: duration,
                  output_preview: preview,
                  started_at: st.started_at || new Date().toISOString(),
                }
              : st,
          ),
        })),

      cost: null,
      setCost: (cost) => set({ cost }),
      extractedFiles: [],
      setExtractedFiles: (extractedFiles) => set({ extractedFiles }),

      apiStatus: 'loading',
      setApiStatus: (apiStatus) => set({ apiStatus }),

      selectedModel: 'models/gemini-2.5-flash',
      setSelectedModel: (selectedModel) => set({ selectedModel }),
    }),
    {
      name: 'agent-chat-storage',
      partialize: (state) => ({
        // Strictly persist client UI preferences only — NEVER persist user-scoped chat/session/token data!
        selectedModel: state.selectedModel,
      }),
    }
  )
)
