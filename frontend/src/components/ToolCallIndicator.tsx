import React from 'react'
import { Search, Database, Loader2, CheckCircle2, FileText } from 'lucide-react'
import { cn } from '../lib/utils'
import type { ToolCall } from '../stores/chatStore'

const TOOL_CONFIG: Record<string, { icon: React.ElementType; label: string }> = {
  web_search: { icon: Search, label: '搜索网络' },
  search_web: { icon: Search, label: '搜索网络' },
  memory_lookup: { icon: Database, label: '查询记忆' },
  lookup_memory: { icon: Database, label: '查询记忆' },
  term_lookup: { icon: Database, label: '查询术语' },
  search_paper_sections: { icon: FileText, label: '搜索论文' },
}

interface ToolCallIndicatorProps {
  toolCalls: ToolCall[]
}

export default function ToolCallIndicator({ toolCalls }: ToolCallIndicatorProps) {
  if (toolCalls.length === 0) return null

  return (
    <div className="flex flex-col gap-1.5 mb-2">
      {toolCalls.map((tc) => {
        const config = TOOL_CONFIG[tc.tool] || { icon: Search, label: tc.tool }
        const Icon = config.icon
        const isCalling = tc.status === 'calling'

        return (
          <div
            key={tc.id}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all duration-300",
              isCalling
                ? "bg-blue-50 text-blue-700 border border-blue-200"
                : "bg-green-50 text-green-700 border border-green-200"
            )}
          >
            <div className="flex items-center gap-1.5">
              {isCalling ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5" />
              )}
              <Icon className="w-3.5 h-3.5" />
              <span className="font-medium">{config.label}</span>
            </div>
            {tc.query && (
              <span className="text-gray-500 truncate max-w-[200px]">
                {tc.query}
              </span>
            )}
            {!isCalling && tc.resultCount !== undefined && tc.resultCount > 0 && (
              <span className="ml-auto text-green-600 whitespace-nowrap">
                {tc.resultCount} 条结果
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
