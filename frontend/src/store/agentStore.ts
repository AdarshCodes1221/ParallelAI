import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type RobotState = 'idle' | 'thinking' | 'done' | 'wave' | 'audio'

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

// Available Gemini models
export const GEMINI_MODELS = [
  { value: 'models/gemini-2.5-flash', label: 'Gemini 2.5 Flash ⚡ (Recommended)' },
  { value: 'models/gemini-2.5-pro', label: 'Gemini 2.5 Pro 🧠' },
  { value: 'models/gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  { value: 'models/gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash Lite (Free)' },
  { value: 'models/gemini-3.5-flash', label: 'Gemini 3.5 Flash ✨' },
  { value: 'models/gemini-flash-latest', label: 'Gemini Flash Latest' },
] as const

export type GeminiModelValue = typeof GEMINI_MODELS[number]['value']

interface AgentStore {
  // Navigation
  page: 'landing' | 'app'
  setPage: (p: 'landing' | 'app') => void

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
  restoreChat: (sessionId: string) => void
  deleteChat: (sessionId: string) => void
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
  const id = crypto.randomUUID()
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
      restoreChat: (sessionId) => {
        const state = get()
        const session = state.sessions.find((s) => s.id === sessionId)
        if (!session) return

        if (state.messages.length || state.planSteps.length || state.extractedFiles.length) {
          state.saveCurrentSessionToHistory()
        }

        const nextSessions = state.sessions.filter((s) => s.id !== sessionId)
        set({
          currentChatId: session.id,
          currentChatTitle: session.title,
          currentChatCreatedAt: session.createdAt,
          messages: session.messages,
          planSteps: session.planSteps,
          cost: session.cost,
          extractedFiles: session.extractedFiles,
          sessions: [session, ...nextSessions].slice(0, 5),
        })
      },
      deleteChat: (sessionId) =>
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== sessionId),
        })),
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
        const sessions = [session, ...existing].slice(0, 5)
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
        messages: state.messages,
        planSteps: state.planSteps,
        extractedFiles: state.extractedFiles,
        sessions: state.sessions,
        currentChatId: state.currentChatId,
        currentChatTitle: state.currentChatTitle,
        currentChatCreatedAt: state.currentChatCreatedAt,
        cost: state.cost,
      }),
    }
  )
)
