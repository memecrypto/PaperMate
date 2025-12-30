import React from 'react'
import { Plus, FileText, MoreVertical } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { usePaperStore } from '@/stores/paperStore'
import { cn } from '@/lib/utils'

const PaperList: React.FC = () => {
  const { papers, currentPaper, setCurrentPaper } = usePaperStore()

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">论文列表</h3>
          <p className="text-xs text-gray-500">{papers.length} 篇论文</p>
        </div>
        <Button variant="ghost" size="icon" title="添加论文">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {papers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 text-sm p-4">
            <FileText className="h-12 w-12 mb-2" />
            <p>还没有论文</p>
            <p className="text-xs mt-1">点击上方按钮添加</p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {papers.map((paper) => (
              <li
                key={paper.id}
                onClick={() => setCurrentPaper(paper)}
                className={cn(
                  "px-4 py-3 cursor-pointer transition-colors group",
                  currentPaper?.id === paper.id
                    ? "bg-primary-50 border-l-2 border-primary-500"
                    : "hover:bg-gray-50"
                )}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium text-gray-900 text-sm truncate">
                      {paper.title}
                    </h4>
                    {paper.authors && (
                      <p className="text-xs text-gray-500 truncate mt-0.5">
                        {paper.authors}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-1">
                      <span className={cn(
                        "px-1.5 py-0.5 text-xs rounded",
                        paper.status === 'ready' ? "bg-green-100 text-green-700" :
                        paper.status === 'parsing' ? "bg-yellow-100 text-yellow-700" :
                        "bg-red-100 text-red-700"
                      )}>
                        {paper.status === 'ready' ? '已就绪' :
                         paper.status === 'parsing' ? '解析中' : '失败'}
                      </span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="opacity-0 group-hover:opacity-100 h-8 w-8"
                  >
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export default PaperList
