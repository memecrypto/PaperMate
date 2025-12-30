import { create } from 'zustand'
import api from '../lib/api'
import { useTermStore } from './termStore'
import { usePaperStore } from './paperStore'
import { useUserProfileStore } from './userProfileStore'

const makeScopeKey = (scopeType: string, scopeId: string) => `${scopeType}:${scopeId}`

// Deduplicate concurrent inits per scope (React StrictMode / remounts / repeated effects)
const scopeInitInFlight = new Map<string, Promise<void>>()

export interface ChatImageAttachment {
  type: 'image'
  data_url: string
  name?: string
  size?: number
}

export type ChatAttachment = ChatImageAttachment

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments?: ChatAttachment[]
  createdAt: string
  parentId: string | null
  siblingIndex: number
  siblingCount: number
}

export interface PendingTermSuggestion {
  id: string
  term: string
  translation: string
  explanation: string
  countdown: number
  status: 'pending' | 'saving' | 'saved' | 'cancelled' | 'editing'
}

export interface PendingProfileUpdate {
  id: string
  updateType: 'expertise' | 'difficulty' | 'mastery' | 'preference'
  topic: string
  value: string  // e.g., "beginner", "intermediate", "advanced" for expertise
  countdown: number
  status: 'pending' | 'saving' | 'saved' | 'cancelled'
}

export interface ToolCall {
  id: string
  tool: string
  query: string
  status: 'calling' | 'done'
  resultCount?: number
}

export interface ChatThread {
  id: string
  title: string | null
  scopeType: string
  scopeId: string
  createdAt: string
}

interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  currentThreadId: string | null
  pendingTerms: PendingTermSuggestion[]
  pendingProfileUpdates: PendingProfileUpdate[]
  toolCalls: ToolCall[]
  projectId: string | null
  scopeType: string | null
  scopeId: string | null
  threads: ChatThread[]
  isLoadingThreads: boolean
  initializedScopeKey: string | null
  currentLeafId: string | null
  error: string | null

  setMessages: (messages: ChatMessage[]) => void
  addMessage: (message: ChatMessage) => void
  appendToLastMessage: (content: string) => void
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void
  replaceMessageId: (oldId: string, newId: string) => void
  removeMessage: (id: string) => void
  setStreaming: (streaming: boolean) => void
  setCurrentThreadId: (id: string | null) => void
  setProjectId: (id: string | null) => void
  setError: (error: string | null) => void
  clearMessages: () => void

  addPendingTerms: (terms: Array<{ term: string; translation: string; explanation: string }>) => void
  updatePendingTerm: (id: string, updates: Partial<PendingTermSuggestion>) => void
  removePendingTerm: (id: string) => void
  savePendingTerm: (id: string) => Promise<void>
  cancelPendingTerm: (id: string) => void
  tickCountdown: () => void

  addPendingProfileUpdates: (updates: Array<Record<string, any>>) => void
  updatePendingProfileUpdate: (id: string, updates: Partial<PendingProfileUpdate>) => void
  removePendingProfileUpdate: (id: string) => void
  savePendingProfileUpdate: (id: string) => Promise<void>
  cancelPendingProfileUpdate: (id: string) => void
  tickProfileCountdown: () => void

  addToolCall: (tc: Omit<ToolCall, 'id'>) => void
  updateToolCall: (tool: string, updates: Partial<ToolCall>) => void
  clearToolCalls: () => void

  initializeForScope: (scopeType: string, scopeId: string) => Promise<void>
  createThread: (scopeType: string, scopeId: string) => Promise<string>
  fetchThreads: (scopeType: string, scopeId: string) => Promise<void>
  switchThread: (threadId: string) => Promise<void>
  deleteThread: (threadId: string) => Promise<void>
  sendMessage: (content: string, parentId?: string | null, attachments?: ChatAttachment[]) => Promise<void>
  editMessage: (messageId: string, content: string) => Promise<void>
  deleteMessage: (messageId: string) => Promise<void>
  switchBranch: (messageId: string, direction: 'prev' | 'next') => Promise<void>
  loadBranch: (leafId?: string) => Promise<void>
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  currentThreadId: null,
  pendingTerms: [],
  pendingProfileUpdates: [],
  toolCalls: [],
  projectId: null,
  scopeType: null,
  scopeId: null,
  threads: [],
  isLoadingThreads: false,
  initializedScopeKey: null,
  currentLeafId: null,
  error: null,

  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message]
  })),
  appendToLastMessage: (content) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const last = messages[messages.length - 1]
      messages[messages.length - 1] = { ...last, content: last.content + content }
    }
    return { messages }
  }),
  updateMessage: (id, updates) => set((state) => ({
    messages: state.messages.map((m) => (m.id === id ? { ...m, ...updates } : m))
  })),
  replaceMessageId: (oldId, newId) => set((state) => ({
    messages: state.messages.map((m) => {
      if (m.id === oldId) return { ...m, id: newId }
      if (m.parentId === oldId) return { ...m, parentId: newId }
      return m
    })
  })),
  removeMessage: (id) => set((state) => ({
    messages: state.messages.filter((m) => m.id !== id)
  })),
  setStreaming: (streaming) => set({ isStreaming: streaming }),
  setCurrentThreadId: (id) => set({ currentThreadId: id }),
  setProjectId: (id) => set({ projectId: id }),
  setError: (error) => set({ error }),
  clearMessages: () => set({ messages: [], currentThreadId: null, pendingTerms: [], pendingProfileUpdates: [], projectId: null, scopeType: null, scopeId: null, threads: [], currentLeafId: null, error: null }),

  addPendingTerms: (terms) => set((state) => ({
    pendingTerms: [
      ...state.pendingTerms,
      ...terms.map((t) => ({
        id: `term-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        term: t.term,
        translation: t.translation,
        explanation: t.explanation,
        countdown: 5,
        status: 'pending' as const
      }))
    ]
  })),

  updatePendingTerm: (id, updates) => set((state) => ({
    pendingTerms: state.pendingTerms.map((t) =>
      t.id === id ? { ...t, ...updates } : t
    )
  })),

  removePendingTerm: (id) => set((state) => ({
    pendingTerms: state.pendingTerms.filter((t) => t.id !== id)
  })),

  savePendingTerm: async (id) => {
    const { pendingTerms, projectId: stateProjectId, scopeType, scopeId, updatePendingTerm, removePendingTerm } = get()
    const term = pendingTerms.find((t) => t.id === id)
    if (!term) {
      console.error('savePendingTerm: missing term', { id })
      return
    }

    updatePendingTerm(id, { status: 'saving' })

    // Try to resolve projectId from paperStore if not in state
    let projectId = stateProjectId
    if (!projectId && scopeType === 'paper' && scopeId) {
      const paper = usePaperStore.getState().currentPaper
      // Compare as strings to handle UUID/string type mismatch
      if (paper && String(paper.id) === String(scopeId) && paper.project_id) {
        projectId = paper.project_id
        set({ projectId })
      }
    }
    // Additional fallback: try to get projectId from currentPaper regardless of scopeId match
    if (!projectId) {
      const paper = usePaperStore.getState().currentPaper
      if (paper?.project_id) {
        projectId = paper.project_id
        set({ projectId })
        console.log('savePendingTerm: resolved projectId from currentPaper fallback', projectId)
      }
    }

    console.log('savePendingTerm called:', { id, term: term.term, projectId, scopeType, scopeId })
    if (!projectId) {
      console.error('savePendingTerm: missing projectId', { id, scopeType, scopeId })
      updatePendingTerm(id, { status: 'pending', countdown: 5 })
      return
    }

    try {
      const paperId = scopeType === 'paper' ? scopeId : undefined
      console.log('savePendingTerm: calling createTermWithKnowledge', { projectId, paperId, phrase: term.term })
      await useTermStore.getState().createTermWithKnowledge({
        projectId,
        paperId: paperId || undefined,
        phrase: term.term,
        translation: term.translation,
        definition: term.explanation
      })
      updatePendingTerm(id, { status: 'saved' })
      setTimeout(() => removePendingTerm(id), 1000)
    } catch (e) {
      console.error('Failed to save term', e)
      updatePendingTerm(id, { status: 'pending', countdown: 5 })
    }
  },

  cancelPendingTerm: (id) => {
    const { updatePendingTerm, removePendingTerm } = get()
    updatePendingTerm(id, { status: 'cancelled' })
    setTimeout(() => removePendingTerm(id), 500)
  },

  tickCountdown: () => {
    const { pendingTerms, savePendingTerm, updatePendingTerm } = get()
    console.log('tickCountdown called, pendingTerms:', pendingTerms.length, pendingTerms.map(t => ({ id: t.id, status: t.status, countdown: t.countdown })))
    for (const term of pendingTerms) {
      if (term.status === 'pending' && term.countdown > 0) {
        const newCountdown = term.countdown - 1
        console.log('tickCountdown: term', term.term, 'countdown', term.countdown, '->', newCountdown)
        if (newCountdown <= 0) {
          console.log('tickCountdown: calling savePendingTerm for', term.id)
          savePendingTerm(term.id)
        } else {
          updatePendingTerm(term.id, { countdown: newCountdown })
        }
      }
    }
  },

  addPendingProfileUpdates: (updates) => {
    const items: PendingProfileUpdate[] = []
    const toTopicList = (value: unknown): string[] => {
      if (typeof value === 'string') return [value]
      if (Array.isArray(value)) return value.filter((v) => typeof v === 'string')
      return []
    }

    for (const update of updates) {
      // Parse different update formats from backend
      if (update.expertise) {
        for (const [topic, level] of Object.entries(update.expertise)) {
          items.push({
            id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            updateType: 'expertise',
            topic,
            value: String(level),
            countdown: 3,
            status: 'pending'
          })
        }
      }
      if (update.expertise_levels) {
        for (const [topic, level] of Object.entries(update.expertise_levels)) {
          items.push({
            id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            updateType: 'expertise',
            topic,
            value: String(level),
            countdown: 3,
            status: 'pending'
          })
        }
      }
      if (update.difficult_topic) {
        items.push({
          id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          updateType: 'difficulty',
          topic: update.difficult_topic,
          value: 'difficult',
          countdown: 3,
          status: 'pending'
        })
      }
      for (const topic of toTopicList(update.added_difficult_topics)) {
        items.push({
          id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          updateType: 'difficulty',
          topic,
          value: 'difficult',
          countdown: 3,
          status: 'pending'
        })
      }
      if (update.mastered_topic) {
        items.push({
          id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          updateType: 'mastery',
          topic: update.mastered_topic,
          value: 'mastered',
          countdown: 3,
          status: 'pending'
        })
      }
      for (const topic of toTopicList(update.added_mastered_topics)) {
        items.push({
          id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          updateType: 'mastery',
          topic,
          value: 'mastered',
          countdown: 3,
          status: 'pending'
        })
      }
      if (update.preferences) {
        for (const [key, val] of Object.entries(update.preferences)) {
          items.push({
            id: `profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            updateType: 'preference',
            topic: key,
            value: String(val),
            countdown: 3,
            status: 'pending'
          })
        }
      }
    }
    if (items.length > 0) {
      set((state) => ({
        pendingProfileUpdates: [...state.pendingProfileUpdates, ...items]
      }))
    }
  },

  updatePendingProfileUpdate: (id, updates) => set((state) => ({
    pendingProfileUpdates: state.pendingProfileUpdates.map((p) =>
      p.id === id ? { ...p, ...updates } : p
    )
  })),

  removePendingProfileUpdate: (id) => set((state) => ({
    pendingProfileUpdates: state.pendingProfileUpdates.filter((p) => p.id !== id)
  })),

  savePendingProfileUpdate: async (id) => {
    const { pendingProfileUpdates, updatePendingProfileUpdate, removePendingProfileUpdate } = get()
    const item = pendingProfileUpdates.find((p) => p.id === id)
    if (!item) return

    updatePendingProfileUpdate(id, { status: 'saving' })

    try {
      const payload: Record<string, any> = {}
      if (item.updateType === 'expertise') {
        payload.expertise_levels = { [item.topic]: item.value }
      } else if (item.updateType === 'difficulty') {
        payload.added_difficult_topics = [item.topic]
      } else if (item.updateType === 'mastery') {
        payload.added_mastered_topics = [item.topic]
      } else if (item.updateType === 'preference') {
        const rawValue = item.value
        let parsedValue: string | boolean = rawValue
        if (rawValue === 'true') {
          parsedValue = true
        } else if (rawValue === 'false') {
          parsedValue = false
        }
        payload.preferences = { [item.topic]: parsedValue }
      }

      const res = await api.patch('/auth/me/profile', payload)
      useUserProfileStore.setState({ profile: res.data })
      updatePendingProfileUpdate(id, { status: 'saved' })
      setTimeout(() => removePendingProfileUpdate(id), 1000)
    } catch (e) {
      console.error('Failed to save profile update', e)
      updatePendingProfileUpdate(id, { status: 'pending', countdown: 3 })
    }
  },

  cancelPendingProfileUpdate: (id) => {
    const { updatePendingProfileUpdate, removePendingProfileUpdate } = get()
    updatePendingProfileUpdate(id, { status: 'cancelled' })
    setTimeout(() => removePendingProfileUpdate(id), 500)
  },

  tickProfileCountdown: () => {
    const { pendingProfileUpdates, savePendingProfileUpdate, updatePendingProfileUpdate } = get()
    for (const item of pendingProfileUpdates) {
      if (item.status === 'pending' && item.countdown > 0) {
        const newCountdown = item.countdown - 1
        if (newCountdown <= 0) {
          savePendingProfileUpdate(item.id)
        } else {
          updatePendingProfileUpdate(item.id, { countdown: newCountdown })
        }
      }
    }
  },

  addToolCall: (tc) => set((state) => ({
    toolCalls: [...state.toolCalls, { ...tc, id: `tc-${Date.now()}-${Math.random().toString(36).slice(2, 6)}` }]
  })),

  updateToolCall: (tool, updates) => set((state) => ({
    toolCalls: state.toolCalls.map((tc) =>
      tc.tool === tool && tc.status === 'calling' ? { ...tc, ...updates } : tc
    )
  })),

  clearToolCalls: () => set({ toolCalls: [] }),

  initializeForScope: async (scopeType, scopeId) => {
    const normalizedScopeId = String(scopeId)
    const scopeKey = makeScopeKey(scopeType, normalizedScopeId)

    const { initializedScopeKey, threads: existingThreads, currentThreadId } = get()
    if (initializedScopeKey === scopeKey && existingThreads.length > 0 && currentThreadId) return

    const existing = scopeInitInFlight.get(scopeKey)
    if (existing) {
      await existing
      return
    }

    const initPromise = (async () => {
      set({ isLoadingThreads: true, scopeType, scopeId: normalizedScopeId })

      try {
        const res = await api.get('/threads', {
          params: { scope_type: scopeType, scope_id: normalizedScopeId }
        })

        const raw = Array.isArray(res.data) ? res.data : []
        const threads: ChatThread[] = raw.map((t: any) => ({
          id: String(t.id),
          title: t.title ?? null,
          scopeType: String(t.scope_type),
          scopeId: String(t.scope_id),
          createdAt: t.created_at
        }))

        if (threads.length === 0) {
          // Use ensure=true for idempotent creation (won't create duplicates)
          const createRes = await api.post('/threads?ensure=true', { scope_type: scopeType, scope_id: normalizedScopeId })
          const thread = createRes.data
          const newThread: ChatThread = {
            id: String(thread.id),
            title: thread.title ?? null,
            scopeType: String(thread.scope_type),
            scopeId: String(thread.scope_id),
            createdAt: thread.created_at
          }
          set({
            threads: [newThread],
            currentThreadId: newThread.id,
            messages: []
          })
        } else {
          // Switch to most recent thread (backend ordering may not be guaranteed)
          const sorted = [...threads].sort((a, b) =>
            new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
          )
          set({ threads: sorted })
          await get().switchThread(sorted[0].id)
        }

        // Mark successful init for this scope
        set({ initializedScopeKey: scopeKey })
      } finally {
        set({ isLoadingThreads: false })
      }
    })()

    scopeInitInFlight.set(scopeKey, initPromise)
    try {
      await initPromise
    } finally {
      if (scopeInitInFlight.get(scopeKey) === initPromise) {
        scopeInitInFlight.delete(scopeKey)
      }
    }
  },

  createThread: async (scopeType, scopeId) => {
    const res = await api.post('/threads', { scope_type: scopeType, scope_id: scopeId })
    const thread = res.data
    const newThread: ChatThread = {
      id: thread.id,
      title: thread.title,
      scopeType: thread.scope_type,
      scopeId: thread.scope_id,
      createdAt: thread.created_at
    }
    set((state) => ({
      currentThreadId: thread.id,
      messages: [],
      threads: [newThread, ...state.threads]
    }))
    return thread.id
  },

  fetchThreads: async (scopeType, scopeId) => {
    set({ isLoadingThreads: true })
    try {
      const res = await api.get('/threads', {
        params: { scope_type: scopeType, scope_id: scopeId }
      })
      const threads: ChatThread[] = (res.data || []).map((t: any) => ({
        id: t.id,
        title: t.title,
        scopeType: t.scope_type,
        scopeId: t.scope_id,
        createdAt: t.created_at
      }))
      set({ threads })
    } finally {
      set({ isLoadingThreads: false })
    }
  },

  switchThread: async (threadId) => {
    set({ currentThreadId: threadId, messages: [], currentLeafId: null })
    await get().loadBranch()
  },

  deleteThread: async (threadId) => {
    await api.delete(`/threads/${threadId}`)
    const { currentThreadId, threads } = get()
    const newThreads = threads.filter((t) => t.id !== threadId)
    set({ threads: newThreads })
    if (currentThreadId === threadId) {
      set({ currentThreadId: null, messages: [] })
    }
  },

  sendMessage: async (content, parentId, attachments) => {
    const {
      currentThreadId,
      messages,
      addMessage,
      setStreaming,
      appendToLastMessage,
      addPendingTerms,
      replaceMessageId,
      loadBranch,
      setError,
      removeMessage,
      addToolCall,
      updateToolCall,
      clearToolCalls
    } = get()

    if (!currentThreadId) {
      throw new Error('No active thread')
    }

    setError(null)
    clearToolCalls()

    // undefined = auto (use last message), null = explicit root, string = specific parent
    const effectiveParentId = parentId === undefined
      ? (messages.length > 0 ? messages[messages.length - 1].id : null)
      : parentId

    // If we're branching from an earlier point, optimistically truncate the visible branch
    // so the UI doesn't temporarily show messages from the old branch after the fork point.
    if (effectiveParentId === null) {
      set({ messages: [] })
    } else if (effectiveParentId) {
      const parentIdx = messages.findIndex((m) => m.id === effectiveParentId)
      if (parentIdx >= 0 && parentIdx < messages.length - 1) {
        set({ messages: messages.slice(0, parentIdx + 1) })
      }
    }

    const randomSuffix = () => Math.random().toString(36).slice(2, 10)
    const tempUserId = `temp-user-${Date.now()}-${randomSuffix()}`
    const tempAssistantId = `temp-assistant-${Date.now()}-${randomSuffix()}`

    addMessage({
      id: tempUserId,
      role: 'user',
      content,
      attachments: attachments ?? [],
      createdAt: new Date().toISOString(),
      parentId: effectiveParentId,
      siblingIndex: 0,
      siblingCount: 1
    })

    addMessage({
      id: tempAssistantId,
      role: 'assistant',
      content: '',
      createdAt: new Date().toISOString(),
      parentId: tempUserId,
      siblingIndex: 0,
      siblingCount: 1
    })

    setStreaming(true)
    let hasError = false
    let persistedUser = false
    let realUserId: string | null = null

    try {
      try {
        const postRes = await api.post(`/threads/${currentThreadId}/messages`, {
          content,
          parent_id: effectiveParentId,
          attachments: attachments ?? []
        })
        realUserId = postRes.data?.message_id ?? null
        if (realUserId) {
          replaceMessageId(tempUserId, realUserId)
          persistedUser = true
        }
      } catch (e) {
        // POST failed => remove both optimistic messages.
        removeMessage(tempAssistantId)
        removeMessage(tempUserId)
        throw e
      }

      const response = await fetch(`/api/v1/threads/${currentThreadId}/stream`, {
        credentials: 'include'
      })

      if (!response.ok) {
        throw new Error('Stream failed')
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (reader) {
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''

          for (const part of parts) {
            const lines = part.split('\n')
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const dataText = line.slice(6).trim()
                if (dataText === '[DONE]') continue
                try {
                  const data = JSON.parse(dataText)
                  if (data.type === 'token' && data.content) {
                    appendToLastMessage(data.content)
                  } else if (data.type === 'tool_call') {
                    if (data.status === 'calling') {
                      addToolCall({ tool: data.tool, query: data.query, status: 'calling' })
                    } else if (data.status === 'done') {
                      updateToolCall(data.tool, { status: 'done', resultCount: data.result_count })
                    }
                  } else if (data.type === 'term_suggestions' && Array.isArray(data.terms)) {
                    addPendingTerms(data.terms)
                  } else if (data.type === 'profile_update_suggestions' && Array.isArray(data.updates)) {
                    get().addPendingProfileUpdates(data.updates)
                  } else if (data.type === 'error' && data.message) {
                    hasError = true
                    setError(data.message)
                    removeMessage(tempAssistantId)
                  }
                } catch {}
              }
            }
          }
        }
      }

      if (persistedUser) {
        // Follow the branch from the user message we just created (backend will extend to the deepest leaf).
        await loadBranch(realUserId ?? undefined)
      } else if (!hasError) {
        await loadBranch()
      }
    } catch (error) {
      console.error('Failed to send message', error)
      setError(error instanceof Error ? error.message : 'Failed to send message')
      // If user message was persisted but streaming failed, keep the user message and drop the placeholder assistant.
      removeMessage(tempAssistantId)
      if (!persistedUser) removeMessage(tempUserId)
    } finally {
      setStreaming(false)
    }
  },

  editMessage: async (messageId, content) => {
    const { currentThreadId, updateMessage } = get()
    if (!currentThreadId) throw new Error('No active thread')

    updateMessage(messageId, { content })
    await api.patch(`/threads/${currentThreadId}/messages/${messageId}`, { content })
  },

  deleteMessage: async (messageId) => {
    const { currentThreadId, removeMessage, loadBranch } = get()
    if (!currentThreadId) throw new Error('No active thread')

    await api.delete(`/threads/${currentThreadId}/messages/${messageId}`)
    removeMessage(messageId)
    await loadBranch()
  },

  switchBranch: async (messageId, direction) => {
    const { currentThreadId, messages, loadBranch } = get()
    if (!currentThreadId) return

    const msg = messages.find((m) => m.id === messageId)
    if (!msg || msg.siblingCount <= 1) return

    try {
      const res = await api.get(`/threads/${currentThreadId}/messages/${messageId}/siblings`)
      const { siblings, current_index } = res.data
      const newIndex = direction === 'prev' ? current_index - 1 : current_index + 1
      if (newIndex < 0 || newIndex >= siblings.length) return

      const newSiblingId = siblings[newIndex]
      // Load branch ending at the new sibling - the backend will find the deepest leaf from there
      await loadBranch(newSiblingId)
    } catch (e) {
      console.error('Failed to switch branch', e)
    }
  },

  loadBranch: async (leafId) => {
    const { currentThreadId } = get()
    if (!currentThreadId) return

    try {
      const params: Record<string, string> = {}
      if (leafId) params.leaf_id = leafId

      const res = await api.get(`/threads/${currentThreadId}/branch`, { params })
      const messages: ChatMessage[] = (res.data || []).map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content_json?.text || '',
        attachments: m.content_json?.attachments || [],
        createdAt: m.created_at,
        parentId: m.parent_id,
        siblingIndex: m.sibling_index ?? 0,
        siblingCount: m.sibling_count ?? 1
      }))

      const newLeafId = messages.length > 0 ? messages[messages.length - 1].id : null
      set({ messages, currentLeafId: newLeafId })
    } catch (e) {
      console.error('Failed to load branch', e)
    }
  }
}))
