import React, { useEffect, useState, useCallback } from 'react'
import { X, Edit, Check } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useUIStore, type TermSuggestion } from '@/stores/uiStore'
import { useTermStore } from '@/stores/termStore'
import { usePaperStore } from '@/stores/paperStore'
import { cn } from '@/lib/utils'

interface CountdownItemProps {
  term: TermSuggestion
  onSave: (term: TermSuggestion) => void
  onCancel: (id: string) => void
  onEdit: (term: TermSuggestion) => void
  isEditing: boolean
}

const CountdownItem: React.FC<CountdownItemProps> = ({ term, onSave, onCancel, onEdit, isEditing }) => {
  const [progress, setProgress] = useState(100)
  const isAnalyzing = term.status === 'analyzing'

  useEffect(() => {
    if (isEditing || isAnalyzing) return
    if (!term.translation || term.translation.trim() === '') return
    if (term.translation === '解析失败' || term.explanation.includes('解析失败')) return

    const duration = 5000
    const interval = 50
    const decrement = (100 / duration) * interval

    const timer = setInterval(() => {
      setProgress((prev) => {
        const next = prev - decrement
        if (next <= 0) {
          clearInterval(timer)
          onSave(term)
          return 0
        }
        return next
      })
    }, interval)

    return () => clearInterval(timer)
  }, [isEditing, isAnalyzing, term, onSave])

  const getProgressColor = () => {
    if (isAnalyzing) return 'bg-gradient-to-r from-blue-400 to-purple-500 animate-pulse'
    if (progress > 40) return 'bg-gradient-to-r from-primary-500 to-blue-500'
    if (progress > 20) return 'bg-gradient-to-r from-amber-500 to-orange-500'
    return 'bg-gradient-to-r from-red-500 to-pink-500'
  }

  const handleEdit = () => {
    onEdit(term)
  }

  return (
    <div className="bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden">
      <div className={cn("h-1 transition-all", getProgressColor())} style={{ width: isAnalyzing ? '100%' : `${progress}%` }} />
      <div className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-900">{term.term}</span>
              {!isAnalyzing && term.translation && (
                <span className="text-primary-600">（{term.translation}）</span>
              )}
            </div>
            {isAnalyzing ? (
              <div className="mt-2 space-y-2">
                {term.statusMessage && (
                  <p className="text-sm text-gray-600">{term.statusMessage}</p>
                )}
                {term.toolCall && (
                  <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
                    <div className={cn(
                      "w-2 h-2 rounded-full",
                      term.toolCall.status === 'calling'
                        ? "bg-blue-500 animate-pulse"
                        : "bg-green-500"
                    )} />
                    <span className="text-xs font-medium text-blue-700">
                      {term.toolCall.tool === 'arxiv_search' && 'arXiv 搜索'}
                      {term.toolCall.tool === 'tavily_search' && 'Tavily 搜索'}
                      {!['arxiv_search', 'tavily_search'].includes(term.toolCall.tool) && term.toolCall.tool}
                    </span>
                    {term.toolCall.query && (
                      <span className="text-xs text-blue-600 truncate max-w-[200px]">
                        {term.toolCall.query}
                      </span>
                    )}
                    {term.toolCall.status === 'done' && term.toolCall.resultCount !== undefined && (
                      <span className="text-xs text-green-600 ml-auto">
                        {term.toolCall.resultCount} 条结果
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500 mt-1 line-clamp-2">{term.explanation}</p>
            )}
          </div>
          {!isAnalyzing && (
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" onClick={() => onCancel(term.id)} title="取消" className="text-gray-400 hover:text-gray-700">
                <X className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" onClick={handleEdit} title="编辑" className="text-gray-400 hover:text-gray-700">
                <Edit className="h-4 w-4" />
              </Button>
              <Button variant="default" size="sm" onClick={() => onSave(term)}>
                <Check className="h-4 w-4 mr-1" />
                保存
              </Button>
            </div>
          )}
          {isAnalyzing && (
            <Button variant="ghost" size="icon" onClick={() => onCancel(term.id)} title="取消" className="text-gray-400 hover:text-gray-700">
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

const CountdownConfirmation: React.FC = () => {
  const { pendingTerms, removePendingTerm, updatePendingTerm } = useUIStore()
  const { createTermWithKnowledge } = useTermStore()
  const { currentPaper } = usePaperStore()
  const [editingTerm, setEditingTerm] = useState<TermSuggestion | null>(null)
  const [draftTranslation, setDraftTranslation] = useState('')
  const [draftExplanation, setDraftExplanation] = useState('')

  const handleSave = useCallback((term: TermSuggestion) => {
    if (!currentPaper) return
    createTermWithKnowledge({
      projectId: currentPaper.project_id,
      paperId: currentPaper.id,
      phrase: term.term,
      translation: term.translation,
      definition: term.explanation
    }).then(() => {
      removePendingTerm(term.id)
    }).catch((err) => {
      console.error('Failed to save term:', err)
      alert('术语保存失败，请重试')
    })
  }, [createTermWithKnowledge, currentPaper, removePendingTerm])

  const handleCancel = useCallback((id: string) => {
    removePendingTerm(id)
  }, [removePendingTerm])

  const handleEdit = useCallback((term: TermSuggestion) => {
    setEditingTerm(term)
    setDraftTranslation(term.translation || '')
    setDraftExplanation(term.explanation || '')
  }, [])

  const handleEditSave = () => {
    if (!editingTerm) return
    updatePendingTerm(editingTerm.id, {
      translation: draftTranslation,
      explanation: draftExplanation,
      status: 'ready'
    })
    setEditingTerm(null)
  }

  if (pendingTerms.length === 0) return null

  return (
    <>
      <div className="fixed bottom-20 left-1/2 -translate-x-1/2 w-full max-w-2xl z-50 px-4 space-y-2">
        {pendingTerms.map((term) => (
          <CountdownItem
            key={term.id}
            term={term}
            onSave={handleSave}
            onCancel={handleCancel}
            onEdit={handleEdit}
            isEditing={editingTerm?.id === term.id}
          />
        ))}
      </div>

      {editingTerm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-lg p-6 space-y-4">
            <h4 className="font-semibold text-gray-900">编辑术语</h4>
            <div>
              <label className="text-sm text-gray-500">术语</label>
              <div className="mt-1 text-gray-900 font-medium">{editingTerm.term}</div>
            </div>
            <div>
              <label className="text-sm text-gray-500">中文翻译</label>
              <input
                className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                value={draftTranslation}
                onChange={(e) => setDraftTranslation(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm text-gray-500">解释</label>
              <textarea
                className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                rows={4}
                value={draftExplanation}
                onChange={(e) => setDraftExplanation(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setEditingTerm(null)}>
                取消
              </Button>
              <Button onClick={handleEditSave}>
                保存修改
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default CountdownConfirmation
