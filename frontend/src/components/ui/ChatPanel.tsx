import { useRef, useEffect, useState, type KeyboardEvent } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Paperclip, Send, X, Bot, User, RefreshCw, FileText, Music2, Image } from 'lucide-react'
import { useAgentStore, type Message } from '@/store/agentStore'
import { useAgentSSE } from '@/hooks/useAgentSSE'
import { Mic } from 'lucide-react'

// ── File pill ──────────────────────────────────────────────
function FilePill({ file, onRemove }: { file: File; onRemove: () => void }) {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  const Icon = ['mp3', 'wav', 'm4a', 'webm', 'mp4'].includes(ext) ? Music2
    : ['jpg', 'jpeg', 'png'].includes(ext) ? Image
    : FileText

  const isAudio = file.type.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'webm'].includes(ext)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)

  useEffect(() => {
    if (isAudio) {
      const url = URL.createObjectURL(file)
      setAudioUrl(url)
      return () => URL.revokeObjectURL(url)
    }
  }, [file, isAudio])

  return (
    <motion.span
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0.8, opacity: 0 }}
      className="flex flex-col gap-1 bg-panel border border-border rounded-lg px-2 py-1 text-xs text-gray-300"
    >
      <div className="flex items-center gap-1.5">
        <Icon size={11} className="text-blue" />
        {file.name}
        <button onClick={onRemove} className="text-gray-600 hover:text-red transition-colors ml-0.5">
          <X size={11} />
        </button>
      </div>
      {audioUrl && (
        <audio controls src={audioUrl} className="h-6 w-32 mt-1 opacity-80" />
      )}
    </motion.span>
  )
}

// ── Message bubble ────────────────────────────────────────
function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'

  const formatted = msg.text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/###\s?(.*?)(\n|$)/g, '<span class="text-purple-light font-bold block mt-1">$1</span>')
    .replace(/\n/g, '<br />')

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* Avatar */}
      <div className={`
        flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
        ${isUser ? 'bg-purple' : 'bg-panel border border-border'}
      `}>
        {isUser ? <User size={14} /> : <Bot size={14} className="text-blue" />}
      </div>

      {/* Bubble */}
      <div className={`
        max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed
        ${isUser
          ? 'bg-gradient-to-br from-purple to-[#5a1fc8] text-white rounded-tr-none'
          : 'glass border border-border rounded-tl-none'}
        ${msg.streaming ? 'typing-cursor' : ''}
      `}>
        <p dangerouslySetInnerHTML={{ __html: formatted || '&nbsp;' }} />

        {/* File attachments */}
        {msg.files && msg.files.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-white/10">
            {msg.files.map((f) => {
              const ext = f.split('.').pop()?.toLowerCase() ?? ''
              const Icon = ['mp3', 'wav', 'm4a'].includes(ext) ? Music2
                : ['jpg', 'jpeg', 'png'].includes(ext) ? Image
                : FileText
              return (
                <span key={f} className="flex items-center gap-1 text-[10px] text-gray-400 bg-black/20 rounded px-1.5 py-0.5">
                  <Icon size={9} />{f}
                </span>
              )
            })}
          </div>
        )}

        {/* TTS Audio Playback */}
        {msg.audioUrl && (
          <div className="mt-3">
            <audio controls src={msg.audioUrl} className="h-8 w-full rounded-md" />
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Main Chat Panel ───────────────────────────────────────
export function ChatPanel() {
  const { messages, clearCurrentConversation, robotState, pendingToolCommand, setPendingToolCommand } = useAgentStore()
  const { sendQuery } = useAgentSSE()
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  
  const endRef       = useRef<HTMLDivElement>(null)
  const scrollRef    = useRef<HTMLDivElement>(null)
  const shouldAutoScrollRef = useRef(true)
  const textareaRef  = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const sending = robotState === 'thinking'

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    shouldAutoScrollRef.current = distanceFromBottom < 150
  }

  // auto-scroll only when user is near the bottom
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !shouldAutoScrollRef.current) return

    const frame = requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })

    return () => cancelAnimationFrame(frame)
  }, [messages])

  // handle pending tool commands from ToolGrid
  useEffect(() => {
    if (pendingToolCommand) {
      setQuery((prev) => (prev ? `${prev} ${pendingToolCommand}` : pendingToolCommand))
      setPendingToolCommand(null)
      if (textareaRef.current) {
        textareaRef.current.focus()
      }
    }
  }, [pendingToolCommand, setPendingToolCommand])

  // auto-resize textarea
  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleSubmit = () => {
    const q = query.trim()
    if ((!q && files.length === 0) || sending) return
    sendQuery(q, files)
    setQuery('')
    setFiles([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return
    const arr = Array.from(incoming)
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}${f.size}`))
      return [...prev, ...arr.filter((f) => !existing.has(`${f.name}${f.size}`))]
    })
  }

  const toggleRecording = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop()
      setIsRecording(false)
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        const mediaRecorder = new MediaRecorder(stream)
        mediaRecorderRef.current = mediaRecorder
        audioChunksRef.current = []

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunksRef.current.push(e.data)
        }

        mediaRecorder.onstop = () => {
          const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
          const audioFile = new File([audioBlob], `voice-input-${Date.now()}.webm`, { type: 'audio/webm' })
          setFiles((prev) => [...prev, audioFile])
          stream.getTracks().forEach(t => t.stop())
        }

        mediaRecorder.start()
        setIsRecording(true)
      } catch (err) {
        console.error("Microphone access denied or error:", err)
      }
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green animate-pulse" />
          <h2 className="font-display font-semibold text-sm text-gray-200">Agent Conversation</h2>
        </div>
        <button
          onClick={() => {
            if (window.confirm('Clear current conversation?')) {
              clearCurrentConversation()
            }
          }}
          className="text-gray-600 hover:text-gray-300 transition-colors"
          title="Clear current conversation"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4"
      >
        <AnimatePresence initial={false}>
          {messages.map((m) => <MessageBubble key={m.id} msg={m} />)}
        </AnimatePresence>

        {/* Thinking indicator */}
        <AnimatePresence>
          {sending && messages[messages.length - 1]?.role !== 'assistant' && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex gap-3"
            >
              <div className="w-8 h-8 rounded-full glass border border-border flex items-center justify-center">
                <Bot size={14} className="text-blue" />
              </div>
              <div className="glass border border-border rounded-2xl rounded-tl-none px-4 py-3">
                <div className="flex gap-1 items-center">
                  {[0, 0.2, 0.4].map((d) => (
                    <motion.div
                      key={d}
                      className="w-1.5 h-1.5 rounded-full bg-blue"
                      animate={{ y: [0, -5, 0] }}
                      transition={{ duration: 0.7, repeat: Infinity, delay: d }}
                    />
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={endRef} />
      </div>

      {/* Input zone */}
      <div className="px-5 pb-5 flex-shrink-0">
        {/* File pills */}
        <AnimatePresence>
          {files.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="flex flex-wrap gap-1.5 mb-2 overflow-hidden"
            >
              {files.map((f, i) => (
                <FilePill
                  key={`${f.name}${f.size}`}
                  file={f}
                  onRemove={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                />
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        <div className="
          flex items-end gap-2 glass border border-border rounded-2xl p-3
          focus-within:border-purple transition-colors
        ">
          {/* Attach */}
          <label
            className="flex-shrink-0 text-gray-600 hover:text-purple-light cursor-pointer transition-colors p-1"
            title="Attach files"
          >
            <Paperclip size={17} />
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="video/webm,video/mp4,video/*,audio/*,image/*,application/pdf,.pdf,.png,.jpg,.jpeg,.mp3,.wav,.m4a,.mp4,.webm,.ogg"
              className="hidden"
              onChange={(e) => addFiles(e.target.files)}
            />
          </label>

          {/* Voice Input */}
          <button
            onClick={toggleRecording}
            className={`flex-shrink-0 p-1 rounded-full transition-colors ${
              isRecording ? 'text-red animate-pulse bg-red/10' : 'text-gray-600 hover:text-purple-light'
            }`}
            title="Voice Input"
          >
            <Mic size={17} />
          </button>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question, describe your goal…"
            rows={1}
            className="
              flex-1 bg-transparent outline-none resize-none
              text-sm text-gray-200 placeholder-gray-700
              font-sans leading-relaxed min-h-[24px]
            "
          />

          {/* Send */}
          <motion.button
            whileTap={{ scale: 0.9 }}
            onClick={handleSubmit}
            disabled={sending || (!query.trim() && files.length === 0)}
            className="
              flex-shrink-0 w-8 h-8 rounded-full
              flex items-center justify-center
              transition-all duration-200
              disabled:opacity-30 disabled:cursor-not-allowed
            "
            style={{
              background: sending || (!query.trim() && files.length === 0)
                ? 'rgba(138,63,252,0.3)'
                : 'linear-gradient(135deg,#8a3ffc,#5a1fc8)',
            }}
          >
            <Send size={14} />
          </motion.button>
        </div>

        <p className="text-center text-[10px] text-gray-700 mt-2">
          Shift+Enter for newline · Enter to send
        </p>
      </div>
    </div>
  )
}
