import React, { useState } from 'react'
import { cn } from '@/lib/utils'

interface TermTooltipProps {
  term: string
  translation: string | null
  definition: string | null
  sourcePaper?: string
  children: React.ReactNode
}

const TermTooltip: React.FC<TermTooltipProps> = ({
  term,
  translation,
  definition,
  sourcePaper,
  children
}) => {
  const [isVisible, setIsVisible] = useState(false)
  const [position, setPosition] = useState({ x: 0, y: 0 })

  const handleMouseEnter = (e: React.MouseEvent) => {
    const rect = (e.target as HTMLElement).getBoundingClientRect()
    setPosition({
      x: rect.left,
      y: rect.bottom + 8
    })
    setIsVisible(true)
  }

  const handleMouseLeave = () => {
    setIsVisible(false)
  }

  return (
    <>
      <span
        className="term-highlight"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </span>

      {isVisible && (
        <div
          className={cn(
            "fixed z-50 w-72 bg-white rounded-lg shadow-xl border border-gray-200 p-4",
            "animate-in fade-in-0 zoom-in-95"
          )}
          style={{ left: position.x, top: position.y }}
        >
          <div className="space-y-2">
            <div>
              <h4 className="font-bold text-gray-900">{term}</h4>
              {translation && (
                <p className="text-primary-600 text-sm">{translation}</p>
              )}
            </div>

            {definition && (
              <p className="text-sm text-gray-600 leading-relaxed">
                {definition.length > 150 ? `${definition.slice(0, 150)}...` : definition}
              </p>
            )}

            {sourcePaper && (
              <p className="text-xs text-gray-500">
                首次标注于: {sourcePaper}
              </p>
            )}

            <div className="flex gap-2 pt-2 border-t border-gray-100">
              <button className="text-xs text-primary-600 hover:underline">
                查看详情
              </button>
              <button className="text-xs text-gray-500 hover:underline">
                编辑
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default TermTooltip
