import { create } from 'zustand'

export interface ToolCallInfo {
  tool: string
  query: string
  status: 'calling' | 'done'
  resultCount?: number
}

export interface TermSuggestion {
  term: string
  translation: string
  explanation: string
  id: string
  status?: 'analyzing' | 'ready'
  sources?: string[]
  toolCall?: ToolCallInfo
  statusMessage?: string
}

interface UIState {
  isMemoryPanelOpen: boolean
  isChatPanelOpen: boolean
  isProfilePanelOpen: boolean
  isSettingsOpen: boolean
  activeTab: 'original' | 'translation' | 'analysis' | 'pdf' | 'comparison'
  pendingTerms: TermSuggestion[]
  selectedText: string | null

  toggleMemoryPanel: () => void
  toggleChatPanel: () => void
  toggleProfilePanel: () => void
  toggleSettings: () => void
  setActiveTab: (tab: 'original' | 'translation' | 'analysis' | 'pdf' | 'comparison') => void
  addPendingTerm: (term: TermSuggestion) => void
  updatePendingTerm: (id: string, updates: Partial<TermSuggestion>) => void
  removePendingTerm: (id: string) => void
  clearPendingTerms: () => void
  setSelectedText: (text: string | null) => void
}

export const useUIStore = create<UIState>((set) => ({
  isMemoryPanelOpen: true,
  isChatPanelOpen: true,
  isProfilePanelOpen: false,
  isSettingsOpen: false,
  activeTab: 'original',
  pendingTerms: [],
  selectedText: null,

  toggleMemoryPanel: () => set((state) => ({ isMemoryPanelOpen: !state.isMemoryPanelOpen })),
  toggleChatPanel: () => set((state) => ({ isChatPanelOpen: !state.isChatPanelOpen })),
  toggleProfilePanel: () => set((state) => ({ isProfilePanelOpen: !state.isProfilePanelOpen })),
  toggleSettings: () => set((state) => ({ isSettingsOpen: !state.isSettingsOpen })),
  setActiveTab: (tab) => set({ activeTab: tab }),

  addPendingTerm: (term) => set((state) => ({
    pendingTerms: [...state.pendingTerms, term]
  })),
  updatePendingTerm: (id, updates) => set((state) => ({
    pendingTerms: state.pendingTerms.map(t => t.id === id ? { ...t, ...updates } : t)
  })),
  removePendingTerm: (id) => set((state) => ({
    pendingTerms: state.pendingTerms.filter(t => t.id !== id)
  })),
  clearPendingTerms: () => set({ pendingTerms: [] }),
  setSelectedText: (text) => set({ selectedText: text }),
}))
