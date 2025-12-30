import { create } from 'zustand'
import api from '../lib/api'

export interface Paper {
  id: string
  title: string
  abstract: string | null
  authors: string | null
  status: string
  created_at: string
  project_id: string
}

export interface Section {
  id: string
  title: string | null
  section_type: string | null
  content_md: string | null
  content_text: string | null
}

export interface TranslationGroup {
  id: string
  translation_id: string
  section_id: string
  section_title: string
  group_order: number
  source_md: string
  translated_md: string
  status: string
}

export interface ToolCall {
  tool: string
  query: string
  status: 'calling' | 'done'
  resultCount?: number
}

export interface FailedGroup {
  id: string
  sectionTitle: string
  sourceMd: string
  error: string
  attempts: number
  retrying: boolean
}

export interface TranslationProgress {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed'
  current: number
  total: number
  sectionTitle: string
  translationId: string | null
  toolCall: ToolCall | null
  chunkCurrent: number
  chunkTotal: number
  chunkMessage: string
  domain: string
  domainDetected: boolean
  failedGroups: FailedGroup[]
}

export interface AnalysisProgress {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed'
  current: number
  total: number
  dimension: string
  dimensionTitle: string
  jobId: string | null
  toolCall: ToolCall | null
  error: string
}

interface PaperState {
  currentPaper: Paper | null
  papers: Paper[]
  sections: Section[]
  originalContent: string
  translatedContent: string | null
  translationGroups: TranslationGroup[]
  analysisReport: string | null
  isLoading: boolean
  translationProgress: TranslationProgress
  analysisProgress: AnalysisProgress

  setCurrentPaper: (paper: Paper | null) => void
  setPapers: (papers: Paper[]) => void
  setSections: (sections: Section[]) => void
  setOriginalContent: (content: string) => void
  setTranslatedContent: (content: string | null) => void
  setTranslationGroups: (groups: TranslationGroup[]) => void
  setAnalysisReport: (content: string | null) => void
  setLoading: (loading: boolean) => void
  setTranslationProgress: (progress: Partial<TranslationProgress>) => void
  resetTranslationProgress: () => void
  setAnalysisProgress: (progress: Partial<AnalysisProgress>) => void
  resetAnalysisProgress: () => void

  fetchPapers: (projectId: string) => Promise<void>
  fetchPaperDetails: (paperId: string) => Promise<void>
  uploadPaper: (file: File, projectId: string) => Promise<Paper>
  deletePaper: (paperId: string) => Promise<void>
  reparsePaper: (paperId: string) => Promise<void>
  startTranslation: (mode: 'quick' | 'deep') => Promise<void>
  startDeepAnalysis: () => Promise<void>
  retryGroup: (groupId: string) => Promise<void>
}

const initialTranslationProgress: TranslationProgress = {
  status: 'idle',
  current: 0,
  total: 0,
  sectionTitle: '',
  translationId: null,
  toolCall: null,
  chunkCurrent: 0,
  chunkTotal: 0,
  chunkMessage: '',
  domain: '',
  domainDetected: false,
  failedGroups: [],
}

const initialAnalysisProgress: AnalysisProgress = {
  status: 'idle',
  current: 0,
  total: 0,
  dimension: '',
  dimensionTitle: '',
  jobId: null,
  toolCall: null,
  error: '',
}

const DEEP_DIMENSIONS = [
  { key: 'background_motivation', title: '研究背景与动机' },
  { key: 'core_innovations', title: '核心创新点（3-5个）' },
  { key: 'methodology_details', title: '方法论详解（流程/架构）' },
  { key: 'formula_analysis', title: '关键公式解析' },
  { key: 'experiments_results', title: '实验设计与结果' },
  { key: 'advantages_limitations', title: '优势与局限性' },
  { key: 'future_directions', title: '未来研究方向' },
] as const

export const usePaperStore = create<PaperState>((set, get) => ({
  currentPaper: null,
  papers: [],
  sections: [],
  originalContent: '',
  translatedContent: null,
  translationGroups: [],
  analysisReport: null,
  isLoading: false,
  translationProgress: { ...initialTranslationProgress },
  analysisProgress: { ...initialAnalysisProgress },

  setCurrentPaper: (paper) => set({ currentPaper: paper }),
  setPapers: (papers) => set({ papers }),
  setSections: (sections) => set({ sections }),
  setOriginalContent: (content) => set({ originalContent: content }),
  setTranslatedContent: (content) => set({ translatedContent: content }),
  setTranslationGroups: (groups) => set({ translationGroups: groups }),
  setAnalysisReport: (content) => set({ analysisReport: content }),
  setLoading: (loading) => set({ isLoading: loading }),
  setTranslationProgress: (progress) =>
    set((state) => ({
      translationProgress: { ...state.translationProgress, ...progress },
    })),
  resetTranslationProgress: () =>
    set({ translationProgress: { ...initialTranslationProgress } }),
  setAnalysisProgress: (progress) =>
    set((state) => ({
      analysisProgress: { ...state.analysisProgress, ...progress },
    })),
  resetAnalysisProgress: () =>
    set({ analysisProgress: { ...initialAnalysisProgress } }),

  fetchPapers: async (projectId) => {
    set({ isLoading: true })
    try {
      const res = await api.get('/papers', { params: { project_id: projectId } })
      set({ papers: res.data })
    } finally {
      set({ isLoading: false })
    }
  },

  fetchPaperDetails: async (paperId) => {
    set({ isLoading: true })
    try {
      const res = await api.get(`/papers/${paperId}`)
      const paper = res.data
      const sections: Section[] = paper.sections || []

      const fullContent = sections
        .map((s: Section) => `## ${s.title || 'Section'}\n\n${s.content_md || s.content_text || ''}`)
        .join('\n\n') || paper.abstract || ''

      let translatedContent: string | null = null
      let translationId: string | null = null
      let translationGroups: TranslationGroup[] = []
      let failedGroups: FailedGroup[] = []
      try {
        const transRes = await api.get('/translations', { params: { paper_id: paperId } })
        if (transRes.data && transRes.data.length > 0) {
          const sorted = [...transRes.data].sort((a: any, b: any) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
          const latest = sorted[0]
          if (latest.content_md) {
            translatedContent = latest.content_md
            translationId = latest.id
          }
          if (translationId) {
            try {
              const groupsRes = await api.get(`/translations/${translationId}/groups`)
              const groups = groupsRes.data || []
              translationGroups = groups
              failedGroups = groups
                .filter((g: any) => g.status === 'failed' || g.status === 'queued')
                .map((g: any) => ({
                  id: g.id,
                  sectionTitle: g.section_title || '',
                  sourceMd: g.source_md || '',
                  error: g.last_error || '翻译失败',
                  attempts: g.attempts || 0,
                  retrying: false,
                }))
            } catch {
              // ignore groups fetch error
            }
          }
        }
      } catch (e) {
        console.warn('Failed to fetch translations', e)
      }

      let analysisReport: string | null = null
      try {
        const analysisRes = await api.get(`/analysis/${paperId}/results`)
        const results = analysisRes.data || []

        for (const r of results) {
          if (r.dimension === 'report' && r.summary) {
            analysisReport = r.summary
            break
          }
        }

        if (!analysisReport) {
          const sectionsMap: Record<string, string> = {}
          for (const r of results) {
            if (r.dimension && r.dimension !== 'report' && r.summary) {
              sectionsMap[r.dimension] = r.summary
            }
          }
          if (Object.keys(sectionsMap).length > 0) {
            const header = `# 深度解析报告\n\n**论文**：${paper.title || ''}\n\n`
            const body = DEEP_DIMENSIONS.map((d, idx) => {
              const content = (sectionsMap[d.key] || '').trim()
              if (!content) return ''
              return `<details open><summary>${idx + 1}. ${d.title}</summary>\n\n${content}\n\n</details>`
            }).filter(Boolean).join('\n\n')
            analysisReport = (header + body).trim()
          }
        }
      } catch (e) {
        console.warn('Failed to fetch analysis results', e)
      }

      set({
        currentPaper: paper,
        sections,
        originalContent: fullContent,
        translatedContent,
        translationGroups,
        analysisReport,
        translationProgress: {
          ...initialTranslationProgress,
          translationId,
          failedGroups,
          status: translatedContent ? 'succeeded' : 'idle',
        },
      })
    } finally {
      set({ isLoading: false })
    }
  },

  uploadPaper: async (file, projectId) => {
    const formData = new FormData()
    formData.append('file', file)

    const res = await api.post('/papers/upload', formData, {
      params: { project_id: projectId },
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return res.data
  },

  deletePaper: async (paperId) => {
    await api.delete(`/papers/${paperId}`)
    set((state) => {
      const isCurrent = state.currentPaper?.id === paperId
      return {
        papers: state.papers.filter((p) => p.id !== paperId),
        currentPaper: isCurrent ? null : state.currentPaper,
        sections: isCurrent ? [] : state.sections,
        originalContent: isCurrent ? '' : state.originalContent,
        translatedContent: isCurrent ? null : state.translatedContent
      }
    })
  },

  reparsePaper: async (paperId) => {
    const { fetchPaperDetails } = get()
    set({ isLoading: true })
    try {
      await api.post(`/papers/${paperId}/reparse`)
      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise(r => setTimeout(r, 3000))
          const res = await api.get(`/papers/${paperId}`)
          if (res.data.status === 'ready') {
            await fetchPaperDetails(paperId)
            return
          } else if (res.data.status === 'failed') {
            throw new Error('解析失败')
          }
        }
        throw new Error('解析超时')
      }
      await poll()
    } finally {
      set({ isLoading: false })
    }
  },

  startTranslation: async (mode) => {
    const { currentPaper, setTranslationProgress, setTranslatedContent, resetTranslationProgress } = get()
    if (!currentPaper) return

    resetTranslationProgress()
    setTranslationProgress({ status: 'queued', translationId: null })

    try {
      const res = await api.post('/translations', {
        paper_id: currentPaper.id,
        mode,
        target_language: 'zh',
      })

      const translationId = res.data.id
      setTranslationProgress({ translationId, status: 'running' })

      const response = await fetch(`/api/v1/translations/${translationId}/stream`, {
        credentials: 'include'
      })

      if (!response.ok) {
        setTranslationProgress({ status: 'failed' })
        return
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        setTranslationProgress({ status: 'failed' })
        return
      }

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

                if (data.type === 'snapshot' && data.content_md) {
                  setTranslatedContent(data.content_md)
                } else if (data.type === 'domain_detected') {
                  setTranslationProgress({
                    domain: data.domain || '',
                    domainDetected: true,
                  })
                } else if (data.type === 'tool_call') {
                  setTranslationProgress({
                    toolCall: {
                      tool: data.tool || '',
                      query: data.query || '',
                      status: data.status || 'calling',
                      resultCount: data.result_count,
                    },
                  })
                } else if (data.type === 'chunk_progress') {
                  setTranslationProgress({
                    chunkCurrent: data.chunk_current || 0,
                    chunkTotal: data.chunk_total || 0,
                    chunkMessage: data.message || '',
                  })
                } else if (data.type === 'group_status' || data.type === 'group_error') {
                  const { translationProgress } = get()
                  const failedGroups = [...translationProgress.failedGroups]
                  const groupId = data.group_id
                  const existingIdx = failedGroups.findIndex((g) => g.id === groupId)

                  if (data.status === 'failed' || data.type === 'group_error') {
                    const failedGroup: FailedGroup = {
                      id: groupId,
                      sectionTitle: data.section_title || '',
                      sourceMd: '',
                      error: data.error || '翻译失败',
                      attempts: data.attempts || 1,
                      retrying: false,
                    }
                    if (existingIdx >= 0) {
                      failedGroups[existingIdx] = { ...failedGroups[existingIdx], ...failedGroup }
                    } else {
                      failedGroups.push(failedGroup)
                    }
                    setTranslationProgress({ failedGroups })
                  } else if (data.status === 'succeeded' && existingIdx >= 0) {
                    failedGroups.splice(existingIdx, 1)
                    setTranslationProgress({ failedGroups })
                  } else if (data.status === 'running' && existingIdx >= 0) {
                    failedGroups[existingIdx] = { ...failedGroups[existingIdx], retrying: true }
                    setTranslationProgress({ failedGroups })
                  }
                } else if (data.type === 'progress') {
                  setTranslationProgress({
                    current: data.current || 0,
                    total: data.total || 0,
                    sectionTitle: data.section_title || '',
                    toolCall: null,
                  })
                } else if (data.type === 'status') {
                  setTranslationProgress({ status: data.status, toolCall: null })
                  if (data.status === 'succeeded' || data.status === 'failed') {
                    if (data.status === 'succeeded') {
                      api.get(`/translations/${translationId}`).then((r) => {
                        if (r.data.content_md) {
                          setTranslatedContent(r.data.content_md)
                        }
                      })
                    }
                  }
                } else if (data.type === 'error') {
                  console.error('Translation error:', data.message)
                  setTranslationProgress({ status: 'failed' })
                }
              } catch (e) {
                console.warn('Failed to parse SSE message', e)
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to start translation', error)
      setTranslationProgress({ status: 'failed' })
    }
  },

  startDeepAnalysis: async () => {
    const {
      currentPaper,
      resetAnalysisProgress,
      setAnalysisProgress,
      setAnalysisReport,
    } = get()
    if (!currentPaper) return

    resetAnalysisProgress()
    setAnalysisProgress({ status: 'queued', jobId: null, error: '' })
    setAnalysisReport(null)

    const sectionsMap: Record<string, string> = {}

    try {
      const res = await api.post(`/analysis/${currentPaper.id}/run`, {
        paper_id: currentPaper.id,
        dimensions: DEEP_DIMENSIONS.map(d => d.key),
      })

      const jobId = res.data.id
      setAnalysisProgress({ jobId, status: 'running', total: DEEP_DIMENSIONS.length })

      const response = await fetch(`/api/v1/analysis/jobs/${jobId}/stream`, {
        credentials: 'include'
      })

      if (!response.ok) {
        setAnalysisProgress({ status: 'failed', error: 'Failed to connect to stream' })
        return
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        setAnalysisProgress({ status: 'failed', error: 'No reader available' })
        return
      }

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

                if (data.type === 'snapshot' && Array.isArray(data.results)) {
                  for (const r of data.results) {
                    if (!r?.dimension || !r?.summary) continue
                    if (r.dimension === 'report') {
                      setAnalysisReport(r.summary)
                    } else {
                      sectionsMap[r.dimension] = r.summary
                    }
                  }
                  if (Object.keys(sectionsMap).length > 0) {
                    const header = `# 深度解析报告\n\n**论文**：${currentPaper.title}\n\n`
                    const body = DEEP_DIMENSIONS.map((d, idx) => {
                      const content = (sectionsMap[d.key] || '').trim()
                      if (!content) return ''
                      return `<details open><summary>${idx + 1}. ${d.title}</summary>\n\n${content}\n\n</details>`
                    }).filter(Boolean).join('\n\n')
                    setAnalysisReport((header + body).trim())
                  }
                } else if (data.type === 'tool_call') {
                  setAnalysisProgress({
                    toolCall: {
                      tool: data.tool || '',
                      query: data.query || '',
                      status: data.status || 'calling',
                      resultCount: data.result_count,
                    },
                  })
                } else if (data.type === 'progress') {
                  setAnalysisProgress({
                    current: data.current || 0,
                    total: data.total || DEEP_DIMENSIONS.length,
                    dimension: data.dimension || '',
                    dimensionTitle: data.dimension_title || '',
                    toolCall: null,
                  })
                } else if (data.type === 'dimension_result') {
                  const dim = data.dimension || ''
                  const summary = data.summary || ''
                  if (dim) sectionsMap[dim] = summary
                  const header = `# 深度解析报告\n\n**论文**：${currentPaper.title}\n\n`
                  const body = DEEP_DIMENSIONS.map((d, idx) => {
                    const content = (sectionsMap[d.key] || '').trim()
                    if (!content) return ''
                    return `<details open><summary>${idx + 1}. ${d.title}</summary>\n\n${content}\n\n</details>`
                  }).filter(Boolean).join('\n\n')
                  setAnalysisReport((header + body).trim())
                } else if (data.type === 'status') {
                  setAnalysisProgress({ status: data.status, toolCall: null })
                  if (data.status === 'succeeded' || data.status === 'failed') {
                    if (data.status === 'failed') {
                      setAnalysisProgress({ error: data.error || '分析失败' })
                    } else {
                      api.get(`/analysis/jobs/${jobId}/results`).then((r) => {
                        const results = r.data || []
                        let report: string | null = null
                        const map: Record<string, string> = {}
                        for (const item of results) {
                          if (item.dimension === 'report' && item.summary) report = item.summary
                          else if (item.dimension && item.summary) map[item.dimension] = item.summary
                        }
                        if (!report) {
                          const header = `# 深度解析报告\n\n**论文**：${currentPaper.title}\n\n`
                          const body = DEEP_DIMENSIONS.map((d, idx) => {
                            const content = (map[d.key] || '').trim()
                            if (!content) return ''
                            return `<details open><summary>${idx + 1}. ${d.title}</summary>\n\n${content}\n\n</details>`
                          }).filter(Boolean).join('\n\n')
                          report = (header + body).trim()
                        }
                        setAnalysisReport(report)
                      }).catch(() => {})
                    }
                  }
                } else if (data.type === 'error') {
                  setAnalysisProgress({ status: 'failed', error: data.message || '分析失败' })
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      }
    } catch (err: any) {
      setAnalysisProgress({ status: 'failed', error: err?.message || 'Failed to start analysis' })
    }
  },

  retryGroup: async (groupId: string) => {
    const { translationProgress, setTranslationProgress, setTranslatedContent } = get()
    const translationId = translationProgress.translationId
    if (!translationId) return

    const failedGroups = [...translationProgress.failedGroups]
    const idx = failedGroups.findIndex((g) => g.id === groupId)
    if (idx >= 0) {
      failedGroups[idx] = { ...failedGroups[idx], retrying: true }
      setTranslationProgress({ failedGroups })
    }

    try {
      await api.post(`/translations/${translationId}/groups/${groupId}/retry`)

      const pollGroup = async (): Promise<boolean> => {
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000))
          try {
            const groupsRes = await api.get(`/translations/${translationId}/groups`)
            const groups = groupsRes.data || []
            const group = groups.find((g: any) => g.id === groupId)
            if (!group || group.status === 'succeeded') {
              return true
            }
            if (group.status === 'failed') {
              return false
            }
          } catch {
            // ignore polling errors
          }
        }
        return false
      }

      await pollGroup()
      const res = await api.get(`/translations/${translationId}`)
      if (res.data.content_md) {
        setTranslatedContent(res.data.content_md)
      }

      const groupsRes = await api.get(`/translations/${translationId}/groups`)
      const serverGroups = groupsRes.data || []
      const newFailedGroups: FailedGroup[] = serverGroups
        .filter((g: any) => g.status === 'failed')
        .map((g: any) => ({
          id: g.id,
          sectionTitle: '',
          sourceMd: g.source_md || '',
          error: g.last_error || '翻译失败',
          attempts: g.attempts || 1,
          retrying: false,
        }))
      setTranslationProgress({ failedGroups: newFailedGroups })

    } catch (error) {
      console.error('Failed to retry group', error)
      if (idx >= 0) {
        failedGroups[idx] = { ...failedGroups[idx], retrying: false }
        setTranslationProgress({ failedGroups })
      }
    }
  },
}))
