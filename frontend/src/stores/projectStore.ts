import { create } from 'zustand'
import api from '../lib/api'

export interface Project {
  id: string
  name: string
  domain: string | null
  description: string | null
  created_at: string
  org_id: string
}

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  isLoading: boolean
  fetchProjects: () => Promise<void>
  createProject: (data: { name: string; org_id: string; domain?: string }) => Promise<Project>
  setCurrentProject: (project: Project | null) => void
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProject: null,
  isLoading: false,

  fetchProjects: async () => {
    set({ isLoading: true })
    try {
      const res = await api.get('/projects')
      set({ projects: res.data })
    } finally {
      set({ isLoading: false })
    }
  },

  createProject: async (data) => {
    const res = await api.post('/projects', data)
    const newProject = res.data
    set((state) => ({ projects: [...state.projects, newProject] }))
    return newProject
  },

  setCurrentProject: (project) => set({ currentProject: project })
}))
