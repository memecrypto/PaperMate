import React, { useEffect, useRef, useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { useUIStore } from '@/stores/uiStore'
import { usePaperStore } from '@/stores/paperStore'
import { useTermStore } from '@/stores/termStore'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

import { ComparisonView } from './ComparisonView'
import CodeBlock from './shared/CodeBlock'
import AuthImage from './shared/AuthImage'

const PaperReader: React.FC = () => {
  const { activeTab, setActiveTab, addPendingTerm, updatePendingTerm } = useUIStore()
  const {
    originalContent,
    translatedContent,
    translationGroups,
    analysisReport,
    currentPaper,
    translationProgress,
    analysisProgress,
    startTranslation,
    startDeepAnalysis,
    reparsePaper,
    isLoading,
    retryGroup
  } = usePaperStore()
  const { terms } = useTermStore()
  const contentRootRef = useRef<HTMLDivElement>(null)
  const hideTooltipTimerRef = useRef<number | null>(null)
  const pdfObjectUrlRef = useRef<string | null>(null)
  const [selectionPopover, setSelectionPopover] = useState<{
    text: string
    x: number
    y: number
    context?: string
  } | null>(null)
  const [hoverTooltip, setHoverTooltip] = useState<{
    termId: string
    x: number
    y: number
  } | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfStatus, setPdfStatus] = useState<'idle' | 'loading' | 'ready' | 'failed'>('idle')
  const [pdfError, setPdfError] = useState<string | null>(null)

  const cancelHideTooltip = () => {
    if (hideTooltipTimerRef.current) {
      window.clearTimeout(hideTooltipTimerRef.current)
      hideTooltipTimerRef.current = null
    }
  }

  const scheduleHideTooltip = () => {
    cancelHideTooltip()
    hideTooltipTimerRef.current = window.setTimeout(() => {
      setHoverTooltip(null)
    }, 150)
  }

  const handleTextSelection = () => {
    const selection = window.getSelection()
    const selectedText = selection?.toString().trim()

    if (!selectedText || selectedText.length <= 2 || selectedText.length >= 100) {
      setSelectionPopover(null)
      return
    }

    try {
      const range = selection?.getRangeAt(0)
      const rect = range?.getBoundingClientRect()
      if (!rect) return

      // Extract surrounding context (3-5 paragraphs around selection)
      let context = ''
      const anchorNode = selection?.anchorNode
      if (anchorNode) {
        // Find the paragraph containing the selection
        let paragraph = anchorNode.nodeType === Node.TEXT_NODE
          ? anchorNode.parentElement
          : anchorNode as HTMLElement
        while (paragraph && !['P', 'DIV', 'SECTION', 'LI'].includes(paragraph.tagName)) {
          paragraph = paragraph.parentElement
        }
        if (paragraph) {
          // Get sibling paragraphs for context
          const paragraphs: string[] = []
          let current: Element | null = paragraph
          // Get 2 previous paragraphs
          for (let i = 0; i < 2 && current?.previousElementSibling; i++) {
            current = current.previousElementSibling
            if (current.textContent?.trim()) {
              paragraphs.unshift(current.textContent.trim())
            }
          }
          // Add current paragraph
          paragraphs.push(paragraph.textContent?.trim() || '')
          // Get 2 next paragraphs
          current = paragraph
          for (let i = 0; i < 2 && current?.nextElementSibling; i++) {
            current = current.nextElementSibling
            if (current.textContent?.trim()) {
              paragraphs.push(current.textContent.trim())
            }
          }
          context = paragraphs.join('\n\n')
        }
      }

      setSelectionPopover({
        text: selectedText,
        x: rect.left + rect.width / 2 + window.scrollX,
        y: rect.top + window.scrollY,
        context
      })
    } catch {
      // ignore selection errors
    }
  }

  const handleAnalyzeSelection = async () => {
    if (!selectionPopover || !currentPaper) return
    const phrase = selectionPopover.text
    const termId = `term-${Date.now()}`

    addPendingTerm({
      id: termId,
      term: phrase,
      translation: '',
      explanation: '',
      status: 'analyzing',
      statusMessage: '正在初始化...'
    })

    const context = selectionPopover.context
    setSelectionPopover(null)
    window.getSelection()?.removeAllRanges()

    try {
      const response = await fetch('/api/v1/terms/analyze/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          phrase,
          project_id: currentPaper.project_id,
          paper_id: currentPaper.id,
          context
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        console.log('SSE buffer:', buffer)
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          console.log('SSE line:', line)
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') continue

          try {
            const event = JSON.parse(data)
            console.log('SSE event:', event)

            switch (event.type) {
              case 'status':
                updatePendingTerm(termId, {
                  statusMessage: event.message
                })
                break

              case 'tool_call':
                updatePendingTerm(termId, {
                  toolCall: {
                    tool: event.tool,
                    query: event.query,
                    status: event.status
                  },
                  statusMessage: `正在调用 ${event.tool === 'arxiv_search' ? 'arXiv' : 'Tavily'} 搜索...`
                })
                break

              case 'tool_result':
                updatePendingTerm(termId, {
                  toolCall: {
                    tool: event.tool,
                    query: '',
                    status: 'done',
                    resultCount: event.result_count
                  },
                  statusMessage: `${event.tool === 'arxiv_search' ? 'arXiv' : 'Tavily'} 找到 ${event.result_count} 条结果`
                })
                break

              case 'content':
                updatePendingTerm(termId, {
                  explanation: event.text,
                  statusMessage: '正在生成翻译...'
                })
                break

              case 'done':
                updatePendingTerm(termId, {
                  term: event.result.term || phrase,
                  translation: event.result.translation || '',
                  explanation: event.result.explanation || '',
                  sources: event.result.sources || [],
                  status: 'ready',
                  toolCall: undefined,
                  statusMessage: undefined
                })
                break

              case 'error':
                updatePendingTerm(termId, {
                  translation: '解析失败',
                  explanation: event.message || '解析失败，请稍后重试。',
                  status: 'ready',
                  toolCall: undefined,
                  statusMessage: undefined
                })
                break
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (error) {
      updatePendingTerm(termId, {
        translation: '解析失败',
        explanation: '解析失败，请稍后重试。',
        status: 'ready',
        toolCall: undefined,
        statusMessage: undefined
      })
      console.error('Term analyze failed', error)
    }
  }

  const handleContentMouseOver = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement
    if (!target?.classList?.contains('term-highlight')) return
    const termId = target.dataset.termId
    if (!termId) return
    const rect = target.getBoundingClientRect()
    cancelHideTooltip()
    setHoverTooltip({
      termId,
      x: rect.left + window.scrollX,
      y: rect.bottom + window.scrollY + 8
    })
  }

  const handleContentMouseOut = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement
    if (!target?.classList?.contains('term-highlight')) return
    const related = e.relatedTarget as HTMLElement | null
    if (related && related.closest('.term-tooltip')) return
    scheduleHideTooltip()
  }

  const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const buildFuzzyRegex = useMemo(() => (phrase: string) => {
    const normalized = phrase.trim().replace(/\s+/g, ' ')
    if (!normalized) return null
    const dashClass = '[-‐‑‒–—−]'
    const tokens = normalized.split(' ')
    const tokenPatterns = tokens.map(tok => {
      const tokNorm = tok.replace(/[\u2010\u2011\u2012\u2013\u2014\u2212]/g, '-')
      const escaped = escapeRegex(tokNorm)
      return escaped.replace(/-/g, dashClass)
    })
    return new RegExp(tokenPatterns.join('\\s+'), 'i')
  }, [])

  // Cache compiled regex patterns for terms
  const termPatterns = useMemo(() => {
    if (!terms || terms.length === 0) return []
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
  }, [termPatterns, activeTab, originalContent, translatedContent])

  useEffect(() => {
    if (pdfObjectUrlRef.current) {
      URL.revokeObjectURL(pdfObjectUrlRef.current)
      pdfObjectUrlRef.current = null
    }
    setPdfUrl(null)
    setPdfStatus('idle')
    setPdfError(null)
  }, [currentPaper?.id])

  useEffect(() => {
    return () => {
      if (pdfObjectUrlRef.current) {
        URL.revokeObjectURL(pdfObjectUrlRef.current)
        pdfObjectUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (activeTab !== 'pdf') return
    if (!currentPaper?.id) return
    if (pdfStatus === 'loading' || pdfStatus === 'ready') return

    setPdfStatus('loading')
    setPdfError(null)

    api.get(`/papers/${currentPaper.id}/pdf`, { responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        pdfObjectUrlRef.current = url
        setPdfUrl(url)
        setPdfStatus('ready')
      })
      .catch((err) => {
        console.error('Failed to load PDF', err)
        setPdfStatus('failed')
        setPdfError(err?.response?.data?.detail || err?.message || 'PDF加载失败')
      })
  }, [activeTab, currentPaper?.id, pdfStatus])

  const renderContent = (content: string) => {
    const renderSimpleText = (Tag: keyof JSX.IntrinsicElements, children: React.ReactNode) => {
      return <Tag>{children}</Tag>
    }
    return (
      <div ref={contentRootRef} className="prose prose-gray max-w-none text-gray-900 prose-headings:text-gray-900 prose-strong:text-gray-900 prose-a:text-primary-600 prose-blockquote:text-gray-600 prose-th:text-gray-900 prose-td:text-gray-700">
        <ReactMarkdown
          remarkPlugins={[remarkMath, remarkGfm]}
          rehypePlugins={[rehypeRaw, [rehypeSanitize, {
            ...defaultSchema,
            tagNames: [...(defaultSchema.tagNames || []), 'span', 'div', 'section', 'figure', 'figcaption'],
            attributes: {
              ...defaultSchema.attributes,
              '*': [...(defaultSchema.attributes?.['*'] || []), 'className', 'class', 'style'],
              span: ['data-term-id'],
              img: ['src', 'alt', 'title', 'width', 'height', 'loading'],
            }
          }], rehypeKatex]}
          components={{
            p: ({ children }) => {
              const childArray = React.Children.toArray(children)
              const nonEmptyChildren = childArray.filter((c) => {
                if (typeof c === 'string') return c.trim() !== ''
                return true
              })

              const isImageOnly =
                nonEmptyChildren.length > 0 &&
                nonEmptyChildren.every(
                  (c) => React.isValidElement(c) && c.type === 'img'
                )

              if (isImageOnly) {
                return <div className="image-row">{nonEmptyChildren}</div>
              }

              return <p className="mb-4 leading-relaxed whitespace-pre-wrap">{children}</p>
            }
            ,code: (props) => <CodeBlock {...props} />
            ,li: ({ children }) => renderSimpleText('li', children)
            ,h1: ({ children }) => renderSimpleText('h1', children)
            ,h2: ({ children }) => renderSimpleText('h2', children)
            ,h3: ({ children }) => renderSimpleText('h3', children)
            ,h4: ({ children }) => renderSimpleText('h4', children)
            ,h5: ({ children }) => renderSimpleText('h5', children)
            ,h6: ({ children }) => renderSimpleText('h6', children)
            ,td: ({ children }) => renderSimpleText('td', children)
            ,th: ({ children }) => renderSimpleText('th', children)
            ,img: (props) => <AuthImage {...props} />
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200">
      <div className="flex items-center border-b border-gray-200 px-4">
        <button
          className={cn(
            "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
            activeTab === 'original'
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
          onClick={() => setActiveTab('original')}
        >
          原文
        </button>
        <button
          className={cn(
            "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
            activeTab === 'translation'
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
          onClick={() => setActiveTab('translation')}
        >
          翻译
        </button>
        <button
          className={cn(
            "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
            activeTab === 'comparison'
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
          onClick={() => setActiveTab('comparison')}
        >
          对照
        </button>
        <button
          className={cn(
            "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
            activeTab === 'analysis'
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
          onClick={() => setActiveTab('analysis')}
        >
          深度解析
        </button>
        <button
          className={cn(
            "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
            activeTab === 'pdf'
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
          onClick={() => setActiveTab('pdf')}
          disabled={!currentPaper}
          title={!currentPaper ? '请先选择论文' : undefined}
        >
          原PDF
        </button>

        {currentPaper && (
          <div className="ml-auto text-sm text-gray-500">
            {currentPaper.title}
          </div>
        )}
      </div>

      <div
        className={cn(
          "flex-1 overflow-y-auto",
          activeTab === 'pdf' ? "p-0" : "p-6"
        )}
        onMouseUp={activeTab === 'pdf' ? undefined : handleTextSelection}
        onMouseOver={activeTab === 'pdf' ? undefined : handleContentMouseOver}
        onMouseOut={activeTab === 'pdf' ? undefined : handleContentMouseOut}
      >
        {activeTab !== 'pdf' && hoverTooltip && (() => {
          const term = terms.find(t => t.id === hoverTooltip.termId)
          if (!term) return null
          return (
            <div
              className={cn(
                "term-tooltip fixed z-50 w-72 bg-white rounded-lg shadow-xl border border-gray-200 p-3",
                "animate-in fade-in-0 zoom-in-95"
              )}
              style={{ left: hoverTooltip.x, top: hoverTooltip.y }}
              onMouseEnter={cancelHideTooltip}
              onMouseLeave={(e) => {
                const related = e.relatedTarget as HTMLElement | null
                if (related && related.closest('.term-highlight')) return
                scheduleHideTooltip()
              }}
            >
              <div className="space-y-1">
                <div className="font-semibold text-gray-900">{term.phrase}</div>
                {term.translation && (
                  <div className="text-sm text-primary-600">{term.translation}</div>
                )}
                {term.definition && (
                  <div className="text-xs text-gray-600 leading-relaxed">
                    {term.definition}
                  </div>
                )}
              </div>
            </div>
          )
        })()}
        {activeTab !== 'pdf' && selectionPopover && (
          <div
            className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-sm"
            style={{
              left: selectionPopover.x,
              top: selectionPopover.y,
              transform: 'translate(-50%, -110%)'
            }}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 max-w-xs">
              <span className="truncate max-w-[180px]" title={selectionPopover.text}>
                {selectionPopover.text}
              </span>
              <Button size="sm" onClick={handleAnalyzeSelection}>
                解析
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelectionPopover(null)}
              >
                取消
              </Button>
            </div>
          </div>
        )}
        {activeTab === 'original' ? (
          originalContent ? (
            <div>
              <div className="mb-4 flex items-center justify-between">
                <span className="text-xs text-gray-500">原文</span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isLoading || currentPaper?.status === 'parsing'}
                  onClick={() => currentPaper && reparsePaper(currentPaper.id)}
                >
                  {isLoading || currentPaper?.status === 'parsing' ? '解析中...' : '重新解析'}
                </Button>
              </div>
              <MemoizedContent content={originalContent} render={renderContent} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              请选择或上传论文
            </div>
          )
        ) : activeTab === 'translation' ? (
          translatedContent && ['idle', 'succeeded'].includes(translationProgress.status) ? (
            <div>
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                    AI翻译
                  </span>
                  <span className="text-xs text-gray-500">
                    双击段落可编辑
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => startTranslation('deep')}
                >
                  重新翻译
                </Button>
              </div>
              <MemoizedContent content={translatedContent} render={renderContent} />
              {translationProgress.failedGroups.length > 0 && (
                <div className="mt-6 border-t pt-4">
                  <h4 className="text-sm font-medium text-red-600 mb-3">
                    {translationProgress.failedGroups.length} 个段落翻译失败
                  </h4>
                  <div className="space-y-3">
                    {translationProgress.failedGroups.map((group) => (
                      <div
                        key={group.id}
                        className="bg-red-50 border border-red-200 rounded-lg p-3"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-red-700">
                              {group.sectionTitle || '未知章节'}
                            </p>
                            <p className="text-xs text-red-500 mt-1 truncate">
                              {group.error}
                            </p>
                            <p className="text-xs text-gray-500 mt-1">
                              尝试次数: {group.attempts}
                            </p>
                          </div>
                          <Button
                            size="sm"
                            variant="outline"
                            className="shrink-0 text-red-600 border-red-300 hover:bg-red-100"
                            disabled={group.retrying}
                            onClick={() => retryGroup(group.id)}
                          >
                            {group.retrying ? '重试中...' : '重试'}
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 gap-4">
              {translationProgress.status === 'idle' && (
                <>
                  <p>{currentPaper ? '暂无翻译' : '请先选择论文'}</p>
                  <button
                    className={cn(
                      "px-4 py-2 rounded-lg transition-colors",
                      currentPaper
                        ? "bg-primary-600 text-white hover:bg-primary-700"
                        : "bg-gray-300 text-gray-500 cursor-not-allowed"
                    )}
                    onClick={() => currentPaper && startTranslation('deep')}
                    disabled={!currentPaper}
                  >
                    开始翻译
                  </button>
                </>
              )}
              {(translationProgress.status === 'queued' || translationProgress.status === 'running') && (
                <div className="flex flex-col items-center gap-4 p-8">
                  <div className="relative w-16 h-16">
                    <div className="absolute inset-0 border-4 border-gray-200 rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-primary-500 rounded-full border-t-transparent animate-spin"></div>
                  </div>
                  <div className="text-center">
                    <p className="text-gray-700 font-medium">
                      {translationProgress.status === 'queued' ? '准备中...' : '翻译中...'}
                    </p>
                    {translationProgress.domainDetected && translationProgress.domain && (
                      <div className="mt-2 px-3 py-1 bg-green-50 border border-green-200 rounded-lg inline-block">
                        <span className="text-xs text-green-700">
                          领域: {translationProgress.domain}
                        </span>
                      </div>
                    )}
                    {translationProgress.total > 0 && (
                      <>
                        <p className="text-sm text-gray-500 mt-1">
                          {translationProgress.current} / {translationProgress.total} 章节
                        </p>
                        <p className="text-xs text-gray-500 mt-1 max-w-xs truncate">
                          {translationProgress.sectionTitle}
                        </p>
                        <div className="w-48 h-2 bg-gray-200 rounded-full mt-3 overflow-hidden">
                          <div
                            className="h-full bg-primary-500 transition-all duration-300 ease-out"
                            style={{
                              width: `${(translationProgress.current / translationProgress.total) * 100}%`
                            }}
                          />
                        </div>
                      </>
                    )}
                    {translationProgress.chunkTotal > 1 && (
                      <p className="text-xs text-purple-600 mt-2">
                        {translationProgress.chunkMessage || `段落 ${translationProgress.chunkCurrent}/${translationProgress.chunkTotal}`}
                      </p>
                    )}
                    {translationProgress.toolCall && (
                      <div className="mt-4 px-4 py-2 bg-blue-50 border border-blue-200 rounded-lg text-left max-w-xs">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            "w-2 h-2 rounded-full",
                            translationProgress.toolCall.status === 'calling'
                              ? "bg-blue-500 animate-pulse"
                              : "bg-green-500"
                          )} />
                          <span className="text-xs font-medium text-blue-700">
                            {translationProgress.toolCall.tool === 'arxiv_search' && 'arXiv 搜索'}
                            {translationProgress.toolCall.tool === 'tavily_search' && 'Tavily 搜索'}
                            {translationProgress.toolCall.tool === 'searxng_search' && 'SearXNG 搜索'}
                            {!['arxiv_search', 'tavily_search', 'searxng_search'].includes(translationProgress.toolCall.tool) && translationProgress.toolCall.tool}
                          </span>
                        </div>
                        <p className="text-xs text-blue-600 mt-1 truncate">
                          {translationProgress.toolCall.query}
                        </p>
                        {translationProgress.toolCall.status === 'done' && translationProgress.toolCall.resultCount !== undefined && (
                          <p className="text-xs text-green-600 mt-1">
                            找到 {translationProgress.toolCall.resultCount} 条结果
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
              {translationProgress.status === 'failed' && (
                <div className="flex flex-col items-center gap-4">
                  <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
                    <svg className="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                  <p className="text-gray-700">翻译失败</p>
                  <button
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
                    onClick={() => startTranslation('deep')}
                  >
                    重试
                  </button>
                </div>
              )}
            </div>
          )
        ) : activeTab === 'comparison' ? (
          <div className="h-full overflow-y-auto">
            <ComparisonView groups={translationGroups} />
          </div>
        ) : activeTab === 'analysis' ? (
          analysisReport && ['idle', 'succeeded'].includes(analysisProgress.status) ? (
            <div>
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded">
                    AI深度解析
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => startDeepAnalysis()}
                >
                  重新分析
                </Button>
              </div>
              <MemoizedContent content={analysisReport} render={renderContent} />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 gap-4">
              {analysisProgress.status === 'idle' && (
                <>
                  <p>{currentPaper ? '暂无深度解析' : '请先选择论文'}</p>
                  <button
                    className={cn(
                      "px-4 py-2 rounded-lg transition-colors",
                      currentPaper
                        ? "bg-purple-600 text-white hover:bg-purple-700"
                        : "bg-gray-300 text-gray-500 cursor-not-allowed"
                    )}
                    onClick={() => currentPaper && startDeepAnalysis()}
                    disabled={!currentPaper}
                  >
                    开始深度解析
                  </button>
                </>
              )}
              {(analysisProgress.status === 'queued' || analysisProgress.status === 'running') && (
                <div className="flex flex-col items-center gap-4 p-8">
                  <div className="relative w-16 h-16">
                    <div className="absolute inset-0 border-4 border-gray-200 rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-purple-500 rounded-full border-t-transparent animate-spin"></div>
                  </div>
                  <div className="text-center">
                    <p className="text-gray-700 font-medium">
                      {analysisProgress.status === 'queued' ? '准备中...' : '深度解析中...'}
                    </p>
                    {analysisProgress.total > 0 && (
                      <>
                        <p className="text-sm text-gray-500 mt-1">
                          {analysisProgress.current} / {analysisProgress.total} 维度
                        </p>
                        <p className="text-xs text-gray-500 mt-1 max-w-xs truncate">
                          {analysisProgress.dimensionTitle}
                        </p>
                        <div className="w-48 h-2 bg-gray-200 rounded-full mt-3 overflow-hidden">
                          <div
                            className="h-full bg-purple-500 transition-all duration-300 ease-out"
                            style={{
                              width: `${(analysisProgress.current / analysisProgress.total) * 100}%`
                            }}
                          />
                        </div>
                      </>
                    )}
                    {analysisProgress.toolCall && (
                      <div className="mt-4 px-4 py-2 bg-blue-50 border border-blue-200 rounded-lg text-left max-w-xs">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            "w-2 h-2 rounded-full",
                            analysisProgress.toolCall.status === 'calling'
                              ? "bg-blue-500 animate-pulse"
                              : "bg-green-500"
                          )} />
                          <span className="text-xs font-medium text-blue-700">
                            {analysisProgress.toolCall.tool === 'arxiv_search' && 'arXiv 搜索'}
                            {analysisProgress.toolCall.tool === 'tavily_search' && 'Tavily 搜索'}
                            {analysisProgress.toolCall.tool === 'searxng_search' && 'SearXNG 搜索'}
                            {!['arxiv_search', 'tavily_search', 'searxng_search'].includes(analysisProgress.toolCall.tool) && analysisProgress.toolCall.tool}
                          </span>
                        </div>
                        <p className="text-xs text-blue-600 mt-1 truncate">
                          {analysisProgress.toolCall.query}
                        </p>
                        {analysisProgress.toolCall.status === 'done' && analysisProgress.toolCall.resultCount !== undefined && (
                          <p className="text-xs text-green-600 mt-1">
                            找到 {analysisProgress.toolCall.resultCount} 条结果
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
              {analysisProgress.status === 'failed' && (
                <div className="flex flex-col items-center gap-4">
                  <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
                    <svg className="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                  <p className="text-gray-700">深度解析失败</p>
                  {analysisProgress.error && (
                    <p className="text-sm text-gray-500 max-w-xs text-center">{analysisProgress.error}</p>
                  )}
                  <button
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                    onClick={() => startDeepAnalysis()}
                  >
                    重试
                  </button>
                </div>
              )}
            </div>
          )
        ) : (
          <div className="h-full min-h-0 flex flex-col">
            <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
              <span className="text-xs text-gray-500">原PDF</span>
              <Button
                size="sm"
                variant="outline"
                disabled={!currentPaper || pdfStatus === 'loading'}
                onClick={() => {
                  if (!currentPaper) return
                  if (pdfObjectUrlRef.current) {
                    URL.revokeObjectURL(pdfObjectUrlRef.current)
                    pdfObjectUrlRef.current = null
                  }
                  setPdfUrl(null)
                  setPdfStatus('idle')
                  setPdfError(null)
                }}
              >
                {pdfStatus === 'loading' ? '加载中...' : '重新加载'}
              </Button>
            </div>

            <div className="flex-1 min-h-0">
              {!currentPaper ? (
                <div className="flex items-center justify-center h-full text-gray-500">
                  请选择或上传论文
                </div>
              ) : pdfStatus === 'failed' ? (
                <div className="flex items-center justify-center h-full text-gray-500 px-6 text-center">
                  {pdfError || 'PDF加载失败'}
                </div>
              ) : pdfUrl ? (
                <iframe
                  className="w-full h-full border-0"
                  src={pdfUrl}
                  title="Original PDF"
                />
              ) : (
                <div className="flex items-center justify-center h-full text-gray-500">
                  {pdfStatus === 'loading' ? 'PDF加载中...' : '准备加载PDF...'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const MemoizedContent: React.FC<{ content: string; render: (c: string) => JSX.Element }> = React.memo(
  ({ content, render }) => render(content),
  (prev, next) => prev.content === next.content
)

export default PaperReader
