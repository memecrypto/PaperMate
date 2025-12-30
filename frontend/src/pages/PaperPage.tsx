import React, { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, MessageSquare, BookOpen, Trash2, User } from 'lucide-react'
import { usePaperStore } from '@/stores/paperStore'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useTermStore } from '@/stores/termStore'
import PaperReader from '@/components/PaperReader'
import ChatPanel from '@/components/ChatPanel'
import MemoryPanel from '@/components/MemoryPanel'
import UserProfilePanel from '@/components/UserProfilePanel'
import CountdownConfirmation from '@/components/CountdownConfirmation'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

const PaperPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { fetchPaperDetails, currentPaper, isLoading, deletePaper } = usePaperStore()
  const { isChatPanelOpen, isMemoryPanelOpen, isProfilePanelOpen, toggleChatPanel, toggleMemoryPanel, toggleProfilePanel } = useUIStore()
  const { fetchTerms } = useTermStore()

  const handleDeletePaper = async () => {
    if (!currentPaper) return
    const confirmed = window.confirm(`确定删除论文 "${currentPaper.title}" 吗？此操作不可撤销。`)
    if (!confirmed) return
    try {
      await deletePaper(currentPaper.id)
      navigate('/')
    } catch (error) {
      console.error('Delete failed', error)
    }
  }

  useEffect(() => {
    if (!id) return
    fetchPaperDetails(id)

    const chat = useChatStore.getState()
    const scopeKey = `paper:${id}`
    if (chat.initializedScopeKey !== scopeKey) {
      chat.clearMessages()
    }
    void chat.initializeForScope('paper', id)
  }, [id, fetchPaperDetails])

  // Lock outer (body) scroll on paper view to avoid double-scroll/blank space.
  useEffect(() => {
    const prevHtmlOverflow = document.documentElement.style.overflow
    const prevBodyOverflow = document.body.style.overflow
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    return () => {
      document.documentElement.style.overflow = prevHtmlOverflow
      document.body.style.overflow = prevBodyOverflow
    }
  }, [])

  // Load project terms for highlighting/memory and set projectId for chat
  useEffect(() => {
    if (currentPaper?.project_id) {
      fetchTerms(currentPaper.project_id)
      useChatStore.getState().setProjectId(currentPaper.project_id)
    }
  }, [currentPaper?.project_id, fetchTerms])

  // Poll status while parsing to update UI automatically
  useEffect(() => {
    if (!id || currentPaper?.status !== 'parsing') return
    const interval = setInterval(() => {
      fetchPaperDetails(id)
    }, 3000)
    return () => clearInterval(interval)
  }, [id, currentPaper?.status, fetchPaperDetails])

  if (isLoading && !currentPaper) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500">加载中...</div>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-gray-100 overflow-hidden">
      {/* Header */}
      <header className="h-14 bg-white border-b border-gray-200 flex items-center px-4 justify-between shrink-0">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate('/')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <h1 className="font-semibold text-gray-900 truncate max-w-md">
            {currentPaper?.title || '加载中...'}
          </h1>
          {currentPaper?.status && currentPaper.status !== 'ready' && (
            <span className="text-sm text-yellow-600 bg-yellow-50 px-2 py-1 rounded">
              {currentPaper.status === 'parsing' ? '解析中...' : currentPaper.status}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {currentPaper && (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDeletePaper}
            >
              <Trash2 className="h-4 w-4 mr-1" />
              删除
            </Button>
          )}
          <Button
            variant={isMemoryPanelOpen ? 'default' : 'ghost'}
            size="sm"
            onClick={toggleMemoryPanel}
          >
            <BookOpen className="h-4 w-4 mr-1" />
            术语
          </Button>
          <Button
            variant={isProfilePanelOpen ? 'default' : 'ghost'}
            size="sm"
            onClick={toggleProfilePanel}
          >
            <User className="h-4 w-4 mr-1" />
            画像
          </Button>
          <Button
            variant={isChatPanelOpen ? 'default' : 'ghost'}
            size="sm"
            onClick={toggleChatPanel}
          >
            <MessageSquare className="h-4 w-4 mr-1" />
            对话
          </Button>
        </div>
      </header>
      {currentPaper?.status === 'parsing' && (
        <div className="h-1 bg-gray-200">
          <div className="h-full bg-primary-500 w-1/3 animate-pulse" />
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 min-h-0 flex gap-4 p-4 overflow-hidden">
        {/* Left Panel - Memory/Terms */}
        <div className={cn(
          "transition-all duration-300 min-h-0",
          isMemoryPanelOpen ? "w-80" : "w-0 opacity-0"
        )}>
          {isMemoryPanelOpen && <MemoryPanel />}
        </div>

        {/* Center - Paper Reader */}
        <div className="flex-1 min-w-0 min-h-0">
          <PaperReader />
        </div>

        {/* Right Panel - Profile */}
        <div className={cn(
          "transition-all duration-300 min-h-0",
          isProfilePanelOpen ? "w-80" : "w-0 opacity-0"
        )}>
          {isProfilePanelOpen && <UserProfilePanel />}
        </div>

        {/* Right Panel - Chat */}
        <div className={cn(
          "transition-all duration-300 min-h-0",
          isChatPanelOpen
            ? isMemoryPanelOpen || isProfilePanelOpen
              ? "w-[420px]"
              : "w-[520px]"
            : "w-0 opacity-0"
        )}>
          {isChatPanelOpen && <ChatPanel />}
        </div>
      </main>

      <CountdownConfirmation />
    </div>
  )
}

export default PaperPage
