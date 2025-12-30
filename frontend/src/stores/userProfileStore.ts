import { create } from 'zustand'
import api from '../lib/api'

export interface UserProfile {
  id: string
  user_id: string
  expertise_levels: Record<string, string>
  preferences: Record<string, any>
  difficult_topics: string[]
  mastered_topics: string[]
  updated_at: string | null
}

interface UserProfileState {
  profile: UserProfile | null
  isLoading: boolean
  error: string | null

  fetchProfile: () => Promise<void>
  updateProfile: (updates: Partial<Pick<UserProfile, 'expertise_levels' | 'preferences' | 'difficult_topics' | 'mastered_topics'>>) => Promise<void>
  resetProfile: () => Promise<void>
  removeExpertise: (topic: string) => Promise<void>
  removeDifficultTopic: (topic: string) => Promise<void>
  removeMasteredTopic: (topic: string) => Promise<void>
}

export const useUserProfileStore = create<UserProfileState>((set, get) => ({
  profile: null,
  isLoading: false,
  error: null,

  fetchProfile: async () => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.get('/auth/me/profile')
      set({ profile: res.data })
    } catch (err: any) {
      set({ error: err.response?.data?.detail || 'Failed to fetch profile' })
    } finally {
      set({ isLoading: false })
    }
  },

  updateProfile: async (updates) => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.patch('/auth/me/profile', updates)
      set({ profile: res.data })
    } catch (err: any) {
      set({ error: err.response?.data?.detail || 'Failed to update profile' })
    } finally {
      set({ isLoading: false })
    }
  },

  resetProfile: async () => {
    set({ isLoading: true, error: null })
    try {
      await api.delete('/auth/me/profile/reset')
      set({
        profile: get().profile ? {
          ...get().profile!,
          expertise_levels: {},
          preferences: {},
          difficult_topics: [],
          mastered_topics: []
        } : null
      })
    } catch (err: any) {
      set({ error: err.response?.data?.detail || 'Failed to reset profile' })
    } finally {
      set({ isLoading: false })
    }
  },

  removeExpertise: async (topic: string) => {
    const { profile, updateProfile } = get()
    if (!profile) return
    const newExpertise = { ...profile.expertise_levels }
    delete newExpertise[topic]
    await updateProfile({ expertise_levels: newExpertise })
  },

  removeDifficultTopic: async (topic: string) => {
    const { profile, updateProfile } = get()
    if (!profile) return
    await updateProfile({
      difficult_topics: profile.difficult_topics.filter(t => t !== topic)
    })
  },

  removeMasteredTopic: async (topic: string) => {
    const { profile, updateProfile } = get()
    if (!profile) return
    await updateProfile({
      mastered_topics: profile.mastered_topics.filter(t => t !== topic)
    })
  }
}))
