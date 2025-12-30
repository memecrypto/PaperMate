import React, { useEffect, useState } from 'react'
import { Search, ChevronRight, Trash2, Edit3 } from 'lucide-react'
import { Input } from '@/components/ui/Input'
import { useTermStore } from '@/stores/termStore'
import { usePaperStore } from '@/stores/paperStore'
import { Button } from '@/components/ui/Button'

const MemoryPanel: React.FC = () => {
  const { terms, searchQuery, setSearchQuery, fetchTerms, updateTermKnowledge, deleteTerm } = useTermStore()
  const { currentPaper } = usePaperStore()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<{
    id: string
    phrase: string
    translation: string
    definition: string
  } | null>(null)

  useEffect(() => {
    if (currentPaper?.project_id) {
      fetchTerms(currentPaper.project_id)
    }
  }, [currentPaper?.project_id, fetchTerms])

  const filteredTerms = terms.filter(term =>
    term.phrase.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (term.translation && term.translation.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200">
      <div className="px-4 py-3 border-b border-gray-200">
        <h3 className="font-semibold text-gray-900">{terms.length} 个术语</h3>
      </div>

      <div className="p-3 border-b border-gray-200">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            placeholder="搜索术语..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {filteredTerms.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 text-sm p-4">
            {searchQuery ? (
              <p>没有找到匹配的术语</p>
            ) : (
              <>
                <p>还没有保存任何术语</p>
                <p className="mt-1 text-xs">选中文本并标注来添加术语</p>
              </>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {filteredTerms.map((term) => (
              <li
                key={term.id}
                className="px-4 py-3 hover:bg-gray-50 cursor-pointer transition-colors group"
                onClick={() => setExpandedId(expandedId === term.id ? null : term.id)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900 truncate">
                        {term.phrase}
                      </span>
                      <span className="text-xs text-gray-500">
                        ×{term.occurrenceCount}
                      </span>
                    </div>
                    {term.translation && (
                      <p className="text-sm text-primary-600 truncate">
                        {term.translation}
                      </p>
                    )}
                    {term.definition && (
                      <p className={expandedId === term.id
                        ? "text-xs text-gray-500 mt-1 whitespace-pre-wrap"
                        : "text-xs text-gray-500 mt-1 line-clamp-2"
                      }>
                        {term.definition}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 transition-opacity">
                    <Button
                      variant="ghost"
                      size="icon"
                      title="编辑"
                      className="text-gray-400 hover:text-gray-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditing({
                          id: term.id,
                          phrase: term.phrase,
                          translation: term.translation || '',
                          definition: term.definition || ''
                        })
                      }}
                    >
                      <Edit3 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      title="删除"
                      className="text-gray-400 hover:text-red-500"
                      onClick={async (e) => {
                        e.stopPropagation()
                        if (!window.confirm(`确定删除术语 "${term.phrase}" 吗？`)) return
                        try {
                          await deleteTerm(term.id)
                        } catch (err) {
                          alert('删除失败：需要管理员权限或网络异常')
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      title={expandedId === term.id ? "收起" : "展开"}
                      className="text-gray-400 hover:text-gray-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        setExpandedId(expandedId === term.id ? null : term.id)
                      }}
                    >
                      <ChevronRight
                        className={`h-4 w-4 transition-transform ${expandedId === term.id ? "rotate-90" : ""}`}
                      />
                    </Button>
                  </div>
                </div>
                {expandedId === term.id && (
                  <div className="mt-2 text-xs text-gray-500">
                    点击右侧按钮可编辑或删除该术语
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="p-3 border-t border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>常用术语排序</span>
          <button
            className="text-primary-600 hover:underline"
            onClick={() => setSearchQuery('')}
          >
            查看全部
          </button>
        </div>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-lg p-6 space-y-4">
            <h4 className="font-semibold text-gray-900">编辑术语</h4>
            <div>
              <label className="text-sm text-gray-500">术语</label>
              <div className="mt-1 text-gray-900 font-medium">{editing.phrase}</div>
            </div>
            <div>
              <label className="text-sm text-gray-500">中文翻译</label>
              <input
                className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                value={editing.translation}
                onChange={(e) => setEditing({ ...editing, translation: e.target.value })}
              />
            </div>
            <div>
              <label className="text-sm text-gray-500">解释</label>
              <textarea
                className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                rows={4}
                value={editing.definition}
                onChange={(e) => setEditing({ ...editing, definition: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                取消
              </Button>
              <Button
                onClick={async () => {
                  try {
                    await updateTermKnowledge(editing.id, {
                      translation: editing.translation,
                      definition: editing.definition
                    })
                    setEditing(null)
                  } catch (err) {
                    alert('保存失败：请稍后重试')
                  }
                }}
              >
                保存修改
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MemoryPanel
