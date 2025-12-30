import React, { useEffect, useRef, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { TranslationGroup } from '@/stores/paperStore'
import { useTermStore } from '@/stores/termStore'

import CodeBlock from './shared/CodeBlock'
import AuthImage from './shared/AuthImage'

interface ComparisonViewProps {
  groups: TranslationGroup[]
}

interface ParagraphPair {
  type: 'heading' | 'image' | 'table' | 'text'
  source: string
  translated: string
}

const splitIntoParagraphs = (source: string, translated: string): ParagraphPair[] => {
  // Split by double newline first, then handle multi-line blocks
  const splitBlock = (text: string): string[] => {
    const blocks = text.split(/\n\n+/).filter(p => p.trim())
    const result: string[] = []
    for (const block of blocks) {
      const lines = block.split('\n').filter(l => l.trim())
      // If block has multiple lines and looks like a list/toc, split by line
      const isListLike = lines.length > 1 && lines.every(l =>
        /^[\d.]+\s/.test(l.trim()) || /^[-*]\s/.test(l.trim()) || /^#{1,6}\s/.test(l.trim())
      )
      if (isListLike) {
        result.push(...lines)
      } else {
        result.push(block)
      }
    }
    return result
  }

  const sourceParts = splitBlock(source)
  const translatedParts = splitBlock(translated)

  const pairs: ParagraphPair[] = []
  const maxLen = Math.max(sourceParts.length, translatedParts.length)

  for (let i = 0; i < maxLen; i++) {
    const src = sourceParts[i] || ''
    const trans = translatedParts[i] || ''
    const trimmedSrc = src.trim()

    // Detect type
    let type: ParagraphPair['type'] = 'text'
    if (/^#{1,6}\s/.test(trimmedSrc)) {
      type = 'heading'
    } else if (/!\[.*?\]\([^)]+\)|<img\s+[^>]*>/i.test(trimmedSrc)) {
      type = 'image'
    } else if (/\|.+\|/.test(trimmedSrc) && /\|[\s:-]+\|/.test(trimmedSrc)) {
      type = 'table'
    }

    pairs.push({ type, source: src, translated: trans })
  }

  return pairs
}

export const ComparisonView: React.FC<ComparisonViewProps> = ({ groups }) => {
  const { terms } = useTermStore()
  const contentRootRef = useRef<HTMLDivElement>(null)

  const buildFuzzyRegex = useCallback((phrase: string): RegExp | null => {
    const normalized = phrase.trim().replace(/\s+/g, ' ')
    if (!normalized) return null
    const dashVariants = '[-‐‑‒–—−]'
    const parts = normalized.split(' ').map((token) => {
      const tokenNorm = token.replace(/[-‐‑‒–—−]/g, '-')
      const escaped = tokenNorm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      return escaped.replace(/-/g, dashVariants)
    })
    const pattern = parts.join('\\s+')
    try {
      return new RegExp(pattern, 'gi')
    } catch {
      return null
    }
  }, [])

  const termPatterns = useMemo(() => {
    const sorted = [...terms].sort((a, b) => b.phrase.length - a.phrase.length)
    return sorted
      .map((t) => ({ term: t, regex: buildFuzzyRegex(t.phrase) }))
      .filter((p): p is { term: typeof sorted[number]; regex: RegExp } => !!p.regex)
  }, [terms, buildFuzzyRegex])

  useEffect(() => {
    const root = contentRootRef.current
    if (!root) return

    // unwrap existing highlights
    root.querySelectorAll('span.term-highlight').forEach((span) => {
      const textNode = document.createTextNode(span.textContent || '')
      span.replaceWith(textNode)
    })

    if (termPatterns.length === 0) return

    const shouldSkipNode = (node: Text) => {
      const parent = node.parentElement
      if (!parent) return true
      if (parent.closest('code, pre, .katex, .term-tooltip')) return true
      if (parent.classList.contains('term-highlight')) return true
      return !node.textContent || !node.textContent.trim()
    }

    for (const { term, regex } of termPatterns) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          return shouldSkipNode(node as Text)
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_ACCEPT
        }
      })

      const textNodes: Text[] = []
      while (walker.nextNode()) {
        textNodes.push(walker.currentNode as Text)
      }

      textNodes.forEach((textNode) => {
        let current: Text | null = textNode
        while (current && current.textContent) {
          regex.lastIndex = 0
          const m = regex.exec(current.textContent)
          if (!m || m.index === undefined) break
          const start = m.index
          const matchText = m[0]
          const before = current.splitText(start)
          const after = before.splitText(matchText.length)
          const span = document.createElement('span')
          span.className = 'term-highlight'
          span.dataset.termId = term.id
          span.textContent = matchText
          before.replaceWith(span)
          current = after
        }
      })
    }
  }, [termPatterns, groups])

  const renderMarkdown = (content: string) => (
    <ReactMarkdown
      remarkPlugins={[remarkMath, remarkGfm]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, {
        ...defaultSchema,
        tagNames: [...(defaultSchema.tagNames || []), 'span', 'div', 'section', 'figure', 'figcaption'],
        attributes: {
          ...defaultSchema.attributes,
          '*': [...(defaultSchema.attributes?.['*'] || []), 'className', 'class', 'style'],
          span: ['data-term-id', 'data-*'],
          img: ['src', 'alt', 'title', 'width', 'height', 'loading'],
        }
      }], rehypeKatex]}
      components={{
        code: (props) => <CodeBlock {...props} />,
        img: (props) => <AuthImage {...props} />
      }}
    >
      {content}
    </ReactMarkdown>
  )

  const extractHeadingText = (md: string) => {
    const match = md.match(/^#{1,6}\s+(.+)$/)
    return match ? match[1].trim() : md.trim()
  }

  const allPairs = useMemo(() => {
    return groups.flatMap((group) => {
      const pairs = splitIntoParagraphs(group.source_md, group.translated_md || '')
      return pairs.map((pair, pairIdx) => ({
        ...pair,
        key: `${group.id}-${pairIdx}`
      }))
    })
  }, [groups])

  return (
    <div ref={contentRootRef} className="flex flex-col pb-20">
      {allPairs.map((pair) => {
        // Heading: merge English + (Chinese)
        if (pair.type === 'heading') {
          const srcText = extractHeadingText(pair.source)
          const transText = pair.translated ? extractHeadingText(pair.translated) : ''
          const level = (pair.source.match(/^(#{1,6})\s/) || ['', '##'])[1]
          const fontSize = level.length <= 2 ? 'text-lg font-bold' : level.length === 3 ? 'text-base font-semibold' : 'text-sm font-medium'
          return (
            <div key={pair.key} className={`px-3 py-2 ${fontSize} text-gray-900 border-b border-gray-200 bg-gray-50`}>
              {srcText}
              {transText && <span className="text-gray-500 font-normal ml-2">（{transText}）</span>}
            </div>
          )
        }

        // Image/Table: show only once
        if (pair.type === 'image' || pair.type === 'table') {
          return (
            <div key={pair.key} className="px-3 py-2 prose prose-sm prose-gray max-w-none">
              {renderMarkdown(pair.source)}
            </div>
          )
        }

        // Text: source + translation
        return (
          <div key={pair.key} className="px-3 py-1 hover:bg-gray-50/50 border-b border-gray-50">
            <div className="prose prose-sm prose-gray max-w-none text-gray-800 leading-relaxed">
              {renderMarkdown(pair.source)}
            </div>
            {pair.translated && (
              <div className="prose prose-sm prose-gray max-w-none text-blue-700/80 leading-relaxed mt-0.5 pl-3 border-l-2 border-blue-200">
                {renderMarkdown(pair.translated)}
              </div>
            )}
          </div>
        )
      })}

      {groups.length === 0 && (
        <div className="flex flex-col items-center justify-center text-gray-500 py-20 gap-2">
          <p>暂无对照内容</p>
          <p className="text-sm">请先完成翻译后查看对照视图</p>
        </div>
      )}
    </div>
  )
}
