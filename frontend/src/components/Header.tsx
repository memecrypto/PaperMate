import React from 'react'
import { BookOpen, PanelLeft, PanelRight, Upload, Settings } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useUIStore } from '@/stores/uiStore'

const Header: React.FC = () => {
  const { toggleMemoryPanel, toggleChatPanel, toggleSettings } = useUIStore()

  return (
    <header className="h-14 bg-white border-b border-gray-200 px-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={toggleMemoryPanel} title="切换术语面板">
          <PanelLeft className="h-5 w-5" />
        </Button>

        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-primary-600" />
          <h1 className="text-lg font-bold text-gray-900">PaperMate</h1>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm">
          <Upload className="h-4 w-4 mr-2" />
          上传论文
        </Button>

        <Button variant="ghost" size="icon" title="设置" onClick={toggleSettings}>
          <Settings className="h-5 w-5" />
        </Button>

        <Button variant="ghost" size="icon" onClick={toggleChatPanel} title="切换对话面板">
          <PanelRight className="h-5 w-5" />
        </Button>
      </div>
    </header>
  )
}

export default Header
