import { useEffect, useRef } from 'react'
import { useAgentStore } from '@/store/agentStore'

const estimateCost = (query: string, files: File[]) => {
  const inputTokens = Math.max(10, Math.ceil((query.length + files.reduce((sum, file) => sum + file.name.length, 0)) / 4))
  const outputTokens = Math.max(50, Math.min(600, Math.ceil(inputTokens * 0.35)))
  const estimated_cost_usd = Number(((inputTokens + outputTokens) * 0.0000004).toFixed(6))
  return {
    provider: 'Pending provider',
    input_tokens_est: inputTokens,
    output_tokens_est: outputTokens,
    estimated_cost_usd,
  }
}

export function useAgentSSE() {
  const { addMessage, appendToken, setAudioUrl, setPlanSteps, updateStepStatus, setCost, setExtractedFiles,
    setRobotState, setActiveToolCard, selectedModel, currentChatId } = useAgentStore()
  const abortRef = useRef<AbortController | null>(null)

  async function sendQuery(query: string, files: File[]) {
    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()

    const userMsgId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    addMessage({ id: userMsgId, role: 'user', text: query, files: files.map((f) => f.name) })

    const assistantMsgId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    addMessage({ id: assistantMsgId, role: 'assistant', text: '', streaming: true })

    setRobotState('thinking')

    const state = useAgentStore.getState()
    const finalQuery = query

    // Clear stale extracted-file context between requests so YouTube summaries
    // and fresh chats are based only on the current input.
    state.setExtractedFiles([])
    state.setPlanSteps([])
    state.setCost(null)

    const formData = new FormData()
    formData.append('query', finalQuery)
    formData.append('stream', 'true')
    formData.append('model', selectedModel)
    formData.append('session_id', currentChatId)
    files.forEach((f) => formData.append('files', f))

    setCost(estimateCost(finalQuery, files))

    const csrf = typeof document !== 'undefined' ? (document.cookie.match(/(^|;)\s*csrf_token=([^;]+)/)?.[2] || '') : ''
    const headers: Record<string, string> = {
      'X-Requested-With': 'XMLHttpRequest',
    }
    if (csrf) {
      headers['X-CSRF-Token'] = decodeURIComponent(csrf)
    }

    try {
      const res = await fetch(`/api/agent`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: formData,
        signal: abortRef.current.signal,
      })

      if (!res.ok) {
        if (res.status === 413) {
          throw new Error('Uploaded file is too large. Maximum allowed upload size is 25 MB.')
        }
        if (res.status === 401) {
          throw new Error('Authentication required or session expired. Please sign in.')
        }
        throw new Error(`Server returned HTTP ${res.status}`)
      }
      if (!res.body) throw new Error('No body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          const raw = part.slice(6).trim()
          try {
            const data = JSON.parse(raw)
            if (data.type === 'init') {
              setCost(data.cost)
              setExtractedFiles(data.extracted_texts ?? [])
              if (data.plan?.length) {
                setPlanSteps(data.plan)
                // activate first step
                updateStepStatus(data.plan[0].step, 'running')
                setActiveToolCard(data.plan[0].tool)
              }
            } else if (data.type === 'trace') {
              // mark all done
              ;(data.trace ?? []).forEach((t: { step: number; execution_duration_sec: number; output_preview: string }) => {
                updateStepStatus(t.step, 'done', t.execution_duration_sec, t.output_preview)
              })
              setActiveToolCard(null)
            } else if (data.type === 'token') {
              appendToken(assistantMsgId, data.token)
            } else if (data.type === 'files') {
              setExtractedFiles(data.extracted_texts ?? [])
            } else if (data.type === 'audio') {
              setAudioUrl(assistantMsgId, data.url)
            } else if (data.type === 'cost_update') {
              setCost(data.cost)
            } else if (data.type === 'done') {
              setRobotState('done')
              setTimeout(() => setRobotState('idle'), 3000)
            } else if (data.type === 'error') {
              appendToken(assistantMsgId, `\n\n❌ Error: ${data.message}`)
              setRobotState('idle')
            }
          } catch { /* malformed chunk */ }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') {
        appendToken(assistantMsgId, `\n\n❌ Connection error: ${(err as Error).message}`)
        setRobotState('idle')
      }
    }
  }

  useEffect(() => () => { abortRef.current?.abort() }, [])
  return { sendQuery }
}
