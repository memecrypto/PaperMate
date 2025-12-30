import { create } from 'zustand'
import api from '../lib/api'

export interface Term {
  id: string
  phrase: string
  translation: string | null
  definition: string | null
  occurrenceCount: number
  createdAt: string
  projectId?: string
}

interface TermState {
  terms: Term[]
  searchQuery: string
  isLoading: boolean
  activeProjectId: string | null

  setTerms: (terms: Term[]) => void
  addTerm: (term: Term) => void
  upsertTerm: (term: Term) => void
  updateTerm: (id: string, updates: Partial<Term>) => void
  removeTerm: (id: string) => void
  setSearchQuery: (query: string) => void
  setLoading: (loading: boolean) => void

  fetchTerms: (projectId: string) => Promise<void>
  createTermWithKnowledge: (params: {
    projectId: string
    paperId?: string
    phrase: string
    translation: string
    definition: string
  }) => Promise<Term>
  updateTermKnowledge: (termId: string, updates: { translation: string; definition: string }) => Promise<void>
  deleteTerm: (termId: string) => Promise<void>
}

let termsFetchSeq = 0

export const useTermStore = create<TermState>()((set, get) => ({
  terms: [],
  searchQuery: '',
  isLoading: false,
  activeProjectId: null,

  setTerms: (terms) => set({ terms }),
  addTerm: (term) => set((state) => ({
    terms: [term, ...state.terms]
  })),
  upsertTerm: (term) => set((state) => {
    const existingIndex = state.terms.findIndex((t: Term) => t.id === term.id)
    if (existingIndex >= 0) {
      const next = [...state.terms]
      next[existingIndex] = { ...next[existingIndex], ...term }
      return { terms: next }
    }
    return { terms: [term, ...state.terms] }
  }),
  updateTerm: (id, updates) => set((state) => ({
    terms: state.terms.map((t: Term) => t.id === id ? { ...t, ...updates } : t)
  })),
  removeTerm: (id) => set((state) => ({
    terms: state.terms.filter((t: Term) => t.id !== id)
  })),
  setSearchQuery: (query) => set({ searchQuery: query }),
  setLoading: (loading) => set({ isLoading: loading }),

  fetchTerms: async (projectId) => {
    const fetchId = ++termsFetchSeq
    set({ isLoading: true, activeProjectId: projectId })
    try {
      const res = await api.get('/terms', { params: { project_id: projectId } })
      if (fetchId !== termsFetchSeq) return
      const terms: Term[] = (res.data || []).map((t: any) => ({
        id: t.id,
        phrase: t.phrase,
        translation: t.knowledge?.translation ?? null,
        definition: t.knowledge?.definition ?? null,
        occurrenceCount: t.occurrence_count ?? 0,
        createdAt: t.created_at,
        projectId: t.project_id
      }))
      set({ terms })
    } finally {
      if (fetchId === termsFetchSeq) {
        set({ isLoading: false })
      }
    }
  },

  createTermWithKnowledge: async ({ projectId, paperId, phrase, translation, definition }): Promise<Term> => {
    console.log('createTermWithKnowledge called:', { projectId, paperId, phrase })
    // Step 1: create term
    let termId: string | null = null
    try {
      const createRes = await api.post('/terms', {
        project_id: projectId,
        phrase,
        language: 'en'
      })
      termId = createRes.data.id
      console.log('Term created:', termId)
    } catch (err: any) {
      console.log('Term create failed, fetching existing:', err.response?.status)
      // If term exists, refetch and reuse
      await get().fetchTerms(projectId)
      const existing = get().terms.find((t: Term) => t.phrase.toLowerCase() === phrase.toLowerCase())
      termId = existing?.id || null
      if (!termId) throw err
    }

    if (!termId) {
      throw new Error('Failed to resolve term id')
    }

    // Step 2: confirm/update knowledge
    await api.post(`/terms/${termId}/confirm`, {
      term_id: termId,
      canonical_en: phrase,
      translation,
      definition
    })
    console.log('Term confirmed:', termId)

    if (paperId) {
      try {
        await api.post(`/terms/${termId}/scan`, { paper_id: paperId })
        console.log('Term scanned')
      } catch (err) {
        console.error('Term scan failed:', err)
      }
    }

    // Fetch updated terms to get correct occurrence count
    console.log('Fetching terms for project:', projectId)
    await get().fetchTerms(projectId)
    const updatedTerm = get().terms.find((t: Term) => t.id === termId)
    console.log('Updated terms count:', get().terms.length, 'Found term:', updatedTerm)

    const resolvedTerm = updatedTerm || {
      id: termId,
      phrase,
      translation,
      definition,
      occurrenceCount: 0,
      createdAt: new Date().toISOString(),
      projectId
    }
    const { activeProjectId } = get()
    if (!activeProjectId || activeProjectId === projectId) {
      get().upsertTerm(resolvedTerm)
    }
    return resolvedTerm
  },

  updateTermKnowledge: async (termId, { translation, definition }) => {
    await api.post(`/terms/${termId}/confirm`, {
      term_id: termId,
      translation,
      definition
    })
    set((state) => ({
      terms: state.terms.map((t: Term) => t.id === termId ? { ...t, translation, definition } : t)
    }))
  },

  deleteTerm: async (termId) => {
    await api.delete(`/terms/${termId}`)
    set((state) => ({
      terms: state.terms.filter((t: Term) => t.id !== termId)
    }))
  }
}))
