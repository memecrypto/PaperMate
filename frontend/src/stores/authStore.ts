import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import api from '../lib/api'

interface User {
  id: string
  email: string
  name: string | null
  org_id: string | null
}

interface AuthState {
  user: User | null
  isLoading: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  register: (email: string, password: string, name?: string) => Promise<void>
  logout: () => Promise<void>
  fetchMe: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isLoading: false,
      error: null,

      login: async (username, password) => {
        set({ isLoading: true, error: null })
        try {
          const params = new URLSearchParams()
          params.append('username', username)
          params.append('password', password)

          const response = await api.post('/auth/login', params, {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
          })
          set({ user: response.data })
        } catch (err: any) {
          const message = err.response?.data?.detail || 'Login failed'
          set({ error: message })
          throw err
        } finally {
          set({ isLoading: false })
        }
      },

      register: async (email, password, name) => {
        set({ isLoading: true, error: null })
        try {
          const response = await api.post('/auth/register', { email, password, name })
          set({ user: response.data })
        } catch (err: any) {
          const message = err.response?.data?.detail || 'Registration failed'
          set({ error: message })
          throw err
        } finally {
          set({ isLoading: false })
        }
      },

      logout: async () => {
        try {
          await api.post('/auth/logout')
        } finally {
          set({ user: null })
        }
      },

      fetchMe: async () => {
        try {
          const response = await api.get('/auth/me')
          set({ user: response.data })
        } catch {
          set({ user: null })
        }
      },

      clearError: () => set({ error: null })
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ user: state.user })
    }
  )
)
