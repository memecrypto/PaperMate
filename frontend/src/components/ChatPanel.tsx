import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, X, Check, Edit2, Plus, MessageSquare, Trash2, ChevronDown, ChevronLeft, ChevronRight, RotateCcw, Copy, ImagePlus } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useChatStore, PendingTermSuggestion, ChatAttachment } from '@/stores/chatStore'
import { usePaperStore } from '@/stores/paperStore'
import { cn } from '@/lib/utils'
import MarkdownMessage from '@/components/MarkdownMessage'
import ProfileUpdateBar from '@/components/ProfileUpdateBar'
import ToolCallIndicator from '@/components/ToolCallIndicator'

const ChatPanel: React.FC = () => {
  const {
    messages,
    isStreaming,
    currentThreadId,
    pendingTerms,
    pendingProfileUpdates,
    threads,
    isLoadingThreads,
    error,
    sendMessage,
    savePendingTerm,
    cancelPendingTerm,
    updatePendingTerm,
    tickCountdown,
    savePendingProfileUpdate,
    cancelPendingProfileUpdate,
    tickProfileCountdown,
    createThread,
    switchThread,
    deleteThread,
    editMessage,
    deleteMessage,
    switchBranch,
    setError,
    toolCalls
  } = useChatStore()
  const { currentPaper } = usePaperStore()
  const [showThreadList, setShowThreadList] = useState(false)
  const [input, setInput] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fileToDataUrl = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || ''))
      reader.onerror = () => reject(new Error('Failed to read file'))
      reader.readAsDataURL(file)
    })

  const addImageFiles = useCallback(async (files: File[]) => {
    const next: ChatAttachment[] = []
    for (const file of files) {
      if (!file.type.startsWith('image/')) continue
      const dataUrl = await fileToDataUrl(file)
      next.push({ type: 'image', data_url: dataUrl, name: file.name, size: file.size })
    }
    if (next.length) setAttachments((prev) => [...prev, ...next])
  }, [])

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData?.items || [])
    const imageFiles = items
      .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
      .map((it) => it.getAsFile())
      .filter((f): f is File => Boolean(f))
    if (imageFiles.length) {
      e.preventDefault()
      await addImageFiles(imageFiles)
    }
  }, [addImageFiles])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'))
    if (files.length > 0) {
      await addImageFiles(files)
    }
  }, [addImageFiles])

  const handleCopy = (id: string, content: string) => {
    navigator.clipboard.writeText(content)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1500)
  }

  const scrollToBottom = () => {
    const container = messagesContainerRef.current
    if (!container) return
    // Only scroll the chat container, not the whole page.
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const hasPendingTerms = pendingTerms.some((t) => t.status === 'pending')
  useEffect(() => {
    if (!hasPendingTerms) return

    const timer = setInterval(() => {
      tickCountdown()
    }, 1000)

    return () => clearInterval(timer)
  }, [hasPendingTerms, tickCountdown])

  const hasPendingProfileUpdates = pendingProfileUpdates.some((p) => p.status === 'pending')
  useEffect(() => {
    if (!hasPendingProfileUpdates) return

    const timer = setInterval(() => {
      tickProfileCountdown()
    }, 1000)

    return () => clearInterval(timer)
  }, [hasPendingProfileUpdates, tickProfileCountdown])


  const handleNewThread = async () => {
    if (!currentPaper) return
    await createThread('paper', currentPaper.id)
    setShowThreadList(false)
  }

  const handleSwitchThread = async (threadId: string) => {
    await switchThread(threadId)
    setShowThreadList(false)
  }

  const handleDeleteThread = async (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation()
    if (!window.confirm('确定删除这个对话吗？')) return
    await deleteThread(threadId)
  }

  const currentThread = threads.find((t) => t.id === currentThreadId)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if ((input.trim().length === 0 && attachments.length === 0) || isStreaming || !currentThreadId) return

    const text = input
    setInput('')
    const currentAttachments = attachments
    setAttachments([])

    try {
      await sendMessage(text, undefined, currentAttachments)
    } catch (error) {
      console.error('Failed to send message', error)
    }
  }

  return (
    <div
      className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200 relative"
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="absolute inset-0 bg-primary-500/10 border-2 border-dashed border-primary-500 z-50 flex items-center justify-center rounded-lg backdrop-blur-sm">
          <p className="text-primary-600 font-medium text-lg">拖放图片到这里</p>
        </div>
      )}
      <div className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-gray-900">AI 助手</h3>
              <button
                onClick={() => setShowThreadList(!showThreadList)}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100"
              >
                <MessageSquare className="w-3 h-3" />
                {threads.length} 个对话
                <ChevronDown className={cn("w-3 h-3 transition-transform", showThreadList && "rotate-180")} />
              </button>
            </div>
            <p className="text-xs text-gray-500 truncate">
              {currentThread?.title || (currentThreadId ? '新对话' : '加载中...')}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={handleNewThread} title="新建对话">
            <Plus className="w-4 h-4" />
          </Button>
        </div>

        {showThreadList && (
          <div className="mt-2 border border-gray-200 rounded-lg bg-white max-h-48 overflow-y-auto">
            {isLoadingThreads ? (
              <div className="p-3 text-center text-sm text-gray-500">加载中...</div>
            ) : threads.length === 0 ? (
              <div className="p-3 text-center text-sm text-gray-500">暂无对话</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {threads.map((thread) => (
                  <li
                    key={thread.id}
                    onClick={() => handleSwitchThread(thread.id)}
                    className={cn(
                      "px-3 py-2 cursor-pointer hover:bg-gray-50 flex items-center justify-between group",
                      thread.id === currentThreadId && "bg-primary-50"
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900 truncate">
                        {thread.title || '新对话'}
                      </p>
                      <p className="text-xs text-gray-500">
                        {new Date(thread.createdAt).toLocaleDateString()}
                      </p>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="opacity-0 group-hover:opacity-100"
                      onClick={(e) => handleDeleteThread(e, thread.id)}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 text-sm">
            <p>还没有对话记录</p>
            <p className="mt-1">试着问一些关于论文的问题吧</p>
          </div>
        ) : (
          messages.map((msg) => {
            const isEditing = editingId === msg.id
            const hasSiblings = msg.siblingCount > 1
            const isValidId = !msg.id.startsWith('temp-')

            return (
              <div
                key={msg.id}
                className={cn(
                  "flex flex-col",
                  msg.role === 'user' ? "items-end" : "items-start"
                )}
              >
                {hasSiblings && (
                  <div className="flex items-center gap-1 mb-1 text-xs text-gray-500">
                    <button
                      onClick={() => switchBranch(msg.id, 'prev')}
                      disabled={msg.siblingIndex === 0 || isStreaming}
                      className="p-0.5 hover:bg-gray-200 rounded disabled:opacity-30"
                    >
                      <ChevronLeft className="w-3 h-3" />
                    </button>
                    <span>{msg.siblingIndex + 1}/{msg.siblingCount}</span>
                    <button
                      onClick={() => switchBranch(msg.id, 'next')}
                      disabled={msg.siblingIndex >= msg.siblingCount - 1 || isStreaming}
                      className="p-0.5 hover:bg-gray-200 rounded disabled:opacity-30"
                    >
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </div>
                )}
                <div className="relative group">
                  <div
                    className={cn(
                      "max-w-[80%] rounded-lg px-3 py-2",
                      msg.role === 'user'
                        ? "bg-primary-600 text-white"
                        : "bg-gray-100 text-gray-900"
                    )}
                  >
                    {isEditing ? (
                      <div className="space-y-2">
                        <textarea
                          value={editingText}
                          onChange={(e) => setEditingText(e.target.value)}
                          className="w-full resize-none rounded border border-gray-300 px-2 py-1 text-sm text-gray-900"
                          rows={3}
                        />
                        <div className="flex items-center justify-end gap-2">
                          <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>取消</Button>
                          <Button size="sm" onClick={() => { editMessage(msg.id, editingText); setEditingId(null) }}>保存</Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {Array.isArray(msg.attachments) && msg.attachments.length > 0 && (
                          <div className="mb-2 grid grid-cols-2 gap-2">
                            {msg.attachments.map((a, i) => (
                              <img
                                key={`${msg.id}-img-${i}`}
                                src={a.data_url}
                                alt={a.name || 'attachment'}
                                className="max-w-full rounded border border-gray-200"
                              />
                            ))}
                          </div>
                        )}
                        <div className={cn(
                          "text-[15px] leading-relaxed max-w-none",
                          msg.role === 'user'
                            ? "[&_*]:text-white [&_a]:text-blue-200 [&_code]:bg-white/20 [&_code]:text-white"
                            : "prose prose-sm prose-p:my-2 prose-headings:my-3 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 [&_p]:text-[15px] [&_li]:text-[15px]"
                        )}>
                          {msg.role === 'assistant' && isStreaming && messages[messages.length - 1].id === msg.id && (
                            <ToolCallIndicator toolCalls={toolCalls} />
                          )}
                          <MarkdownMessage content={msg.content} />
                        </div>
                        {msg.role === 'assistant' && isStreaming && messages[messages.length - 1].id === msg.id && (
                          <span className="inline-block w-1 h-4 bg-gray-400 animate-pulse ml-1" />
                        )}
                      </>
                    )}
                  </div>
                  {isValidId && !isEditing && !isStreaming && (
                    <div className={cn(
                      "flex gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity",
                      msg.role === 'user' ? "justify-end" : "justify-start"
                    )}>
                      <button
                        onClick={() => handleCopy(msg.id, msg.content)}
                        className="p-1 hover:bg-gray-200 rounded"
                        title="复制"
                      >
                        {copiedId === msg.id ? (
                          <Check className="w-3 h-3 text-green-500" />
                        ) : (
                          <Copy className="w-3 h-3 text-gray-500" />
                        )}
                      </button>
                      <button
                        onClick={() => { setEditingId(msg.id); setEditingText(msg.content) }}
                        className="p-1 hover:bg-gray-200 rounded"
                        title="编辑"
                      >
                        <Edit2 className="w-3 h-3 text-gray-500" />
                      </button>
                      {msg.role === 'user' && (
                        <button
                          onClick={() => {
                            sendMessage(msg.content, msg.parentId, msg.attachments ?? [])
                          }}
                          className="p-1 hover:bg-gray-200 rounded"
                          title="重新发送"
                        >
                          <RotateCcw className="w-3 h-3 text-gray-500" />
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (window.confirm('确定删除这条消息吗？')) {
                            deleteMessage(msg.id)
                          }
                        }}
                        className="p-1 hover:bg-gray-200 rounded"
                        title="删除"
                      >
                        <Trash2 className="w-3 h-3 text-gray-500" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {pendingTerms.length > 0 && (
        <div className="px-4 py-2 border-t border-gray-200 space-y-2 bg-amber-50">
          {pendingTerms.map((term) => (
            <TermSuggestionBar
              key={term.id}
              term={term}
              onSave={() => savePendingTerm(term.id)}
              onCancel={() => cancelPendingTerm(term.id)}
              onEdit={() => updatePendingTerm(term.id, { status: 'editing' })}
              onUpdate={(updates) => updatePendingTerm(term.id, updates)}
            />
          ))}
        </div>
      )}

      {pendingProfileUpdates.length > 0 && (
        <div className="px-4 py-2 border-t border-gray-200 space-y-2 bg-purple-50">
          {pendingProfileUpdates.map((update) => (
            <ProfileUpdateBar
              key={update.id}
              update={update}
              onSave={() => savePendingProfileUpdate(update.id)}
              onCancel={() => cancelPendingProfileUpdate(update.id)}
            />
          ))}
        </div>
      )}

      {error && (
        <div className="px-4 py-2 border-t border-gray-200 bg-red-50">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-red-700">{error}</p>
            <button
              onClick={() => setError(null)}
              className="p-1 hover:bg-red-100 rounded"
            >
              <X className="w-4 h-4 text-red-500" />
            </button>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200">
        {attachments.length > 0 && (
          <div className="flex gap-2 mb-2 overflow-x-auto pb-2">
            {attachments.map((a, i) => (
              <div key={`pending-img-${i}`} className="relative group flex-shrink-0">
                <img src={a.data_url} alt={a.name || 'preview'} className="h-16 w-16 object-cover rounded border border-gray-200" />
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((_, idx) => idx !== i))}
                  className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                  title="移除"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="relative">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={async (e) => {
              const files = Array.from(e.target.files || [])
              e.target.value = ''
              await addImageFiles(files)
            }}
          />
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handlePaste}
            placeholder={currentThreadId ? "输入问题..." : "等待连接..."}
            className="w-full resize-none rounded-lg border border-gray-300 pl-12 py-3 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            rows={2}
            disabled={!currentThreadId}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit(e)
              }
            }}
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="absolute left-2 bottom-2"
            disabled={!currentThreadId || isStreaming}
            onClick={() => fileInputRef.current?.click()}
            title="添加图片"
          >
            <ImagePlus className="h-5 w-5" />
          </Button>
          <Button
            type="submit"
            size="icon"
            variant="ghost"
            className="absolute right-2 bottom-2"
            disabled={(input.trim().length === 0 && attachments.length === 0) || isStreaming || !currentThreadId}
          >
            {isStreaming ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}

interface TermSuggestionBarProps {
  term: PendingTermSuggestion
  onSave: () => void
  onCancel: () => void
  onEdit: () => void
  onUpdate: (updates: Partial<PendingTermSuggestion>) => void
}

const TermSuggestionBar: React.FC<TermSuggestionBarProps> = ({
  term,
  onSave,
  onCancel,
  onEdit,
  onUpdate
}) => {
  const [editTranslation, setEditTranslation] = useState(term.translation)
  const [editExplanation, setEditExplanation] = useState(term.explanation)

  const handleSaveEdit = () => {
    onUpdate({
      translation: editTranslation,
      explanation: editExplanation,
      status: 'pending',
      countdown: 5
    })
  }

  if (term.status === 'saved') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-green-100 rounded-lg text-sm">
        <Check className="w-4 h-4 text-green-600" />
        <span className="text-green-700">已保存: {term.term}</span>
      </div>
    )
  }

  if (term.status === 'cancelled') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg text-sm opacity-50">
        <X className="w-4 h-4 text-gray-500" />
        <span className="text-gray-500">已取消: {term.term}</span>
      </div>
    )
  }

  if (term.status === 'saving') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-blue-100 rounded-lg text-sm">
        <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
        <span className="text-blue-700">保存中: {term.term}</span>
      </div>
    )
  }

  if (term.status === 'editing') {
    return (
      <div className="px-3 py-2 bg-white border border-amber-300 rounded-lg space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-900">{term.term}</span>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="ghost" onClick={() => onUpdate({ status: 'pending', countdown: 5 })}>
              取消
            </Button>
            <Button size="sm" onClick={handleSaveEdit}>
              确定
            </Button>
          </div>
        </div>
        <input
          type="text"
          value={editTranslation}
          onChange={(e) => setEditTranslation(e.target.value)}
          placeholder="中文翻译"
          className="w-full px-2 py-1 text-sm border border-gray-300 rounded"
        />
        <textarea
          value={editExplanation}
          onChange={(e) => setEditExplanation(e.target.value)}
          placeholder="解释说明"
          rows={2}
          className="w-full px-2 py-1 text-sm border border-gray-300 rounded resize-none"
        />
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-white border border-amber-300 rounded-lg">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-gray-900 truncate">{term.term}</span>
          <span className="text-xs text-amber-600">（{term.translation}）</span>
        </div>
        <p className="text-xs text-gray-500 truncate">{term.explanation}</p>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="relative w-8 h-8">
          <svg className="w-8 h-8 transform -rotate-90">
            <circle
              cx="16"
              cy="16"
              r="14"
              fill="none"
              stroke="#e5e7eb"
              strokeWidth="2"
            />
            <circle
              cx="16"
              cy="16"
              r="14"
              fill="none"
              stroke="#f59e0b"
              strokeWidth="2"
              strokeDasharray={`${(term.countdown / 5) * 88} 88`}
              className="transition-all duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-xs font-medium text-amber-600">
            {term.countdown}
          </span>
        </div>

        <Button size="icon" variant="ghost" onClick={onEdit} title="编辑">
          <Edit2 className="w-4 h-4" />
        </Button>
        <Button size="icon" variant="ghost" onClick={onCancel} title="取消">
          <X className="w-4 h-4" />
        </Button>
        <Button size="icon" onClick={onSave} title="立即保存">
          <Check className="w-4 h-4" />
        </Button>
      </div>
    </div>
  )
}

export default ChatPanel
