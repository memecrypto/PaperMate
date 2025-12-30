import React from 'react'
import { X, Check, User, BookOpen, Lightbulb, Settings } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import type { PendingProfileUpdate } from '@/stores/chatStore'

interface ProfileUpdateBarProps {
  update: PendingProfileUpdate
  onSave: () => void
  onCancel: () => void
}

const getUpdateIcon = (type: PendingProfileUpdate['updateType']) => {
  switch (type) {
    case 'expertise':
      return <User className="w-4 h-4" />
    case 'difficulty':
      return <BookOpen className="w-4 h-4" />
    case 'mastery':
      return <Lightbulb className="w-4 h-4" />
    case 'preference':
      return <Settings className="w-4 h-4" />
  }
}

const getUpdateLabel = (update: PendingProfileUpdate) => {
  switch (update.updateType) {
    case 'expertise':
      return `${update.topic}: ${update.value}`
    case 'difficulty':
      return `${update.topic}`
    case 'mastery':
      return `${update.topic}`
    case 'preference':
      return `${update.topic}: ${update.value}`
  }
}

const getUpdateDescription = (type: PendingProfileUpdate['updateType']) => {
  switch (type) {
    case 'expertise':
      return '知识水平'
    case 'difficulty':
      return '困难话题'
    case 'mastery':
      return '已掌握'
    case 'preference':
      return '偏好设置'
  }
}

const ProfileUpdateBar: React.FC<ProfileUpdateBarProps> = ({
  update,
  onSave,
  onCancel
}) => {
  if (update.status === 'saved') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-green-100 rounded-lg text-sm">
        <Check className="w-4 h-4 text-green-600" />
        <span className="text-green-700">已更新: {getUpdateLabel(update)}</span>
      </div>
    )
  }

  if (update.status === 'cancelled') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg text-sm opacity-50">
        <X className="w-4 h-4 text-gray-500" />
        <span className="text-gray-500">已取消</span>
      </div>
    )
  }

  if (update.status === 'saving') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 rounded-lg text-sm">
        <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-blue-700">保存中...</span>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2 bg-purple-50 border border-purple-200 rounded-lg text-sm">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <div className="flex-shrink-0 text-purple-600">
          {getUpdateIcon(update.updateType)}
        </div>
        <div className="min-w-0 flex-1">
          <span className="text-purple-600 text-xs">{getUpdateDescription(update.updateType)}</span>
          <div className="font-medium text-gray-900 truncate">{getUpdateLabel(update)}</div>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="relative w-7 h-7">
          <svg className="w-7 h-7 transform -rotate-90">
            <circle
              cx="14"
              cy="14"
              r="12"
              fill="none"
              stroke="#e9d5ff"
              strokeWidth="2"
            />
            <circle
              cx="14"
              cy="14"
              r="12"
              fill="none"
              stroke="#9333ea"
              strokeWidth="2"
              strokeDasharray={`${(update.countdown / 3) * 75.4} 75.4`}
              className="transition-all duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-xs font-medium text-purple-600">
            {update.countdown}
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onCancel}
          className="p-1 h-7 w-7 text-gray-500 hover:text-red-500"
        >
          <X className="w-4 h-4" />
        </Button>
        <Button
          size="sm"
          onClick={onSave}
          className="h-7 px-2 bg-purple-600 hover:bg-purple-700 text-white"
        >
          <Check className="w-4 h-4" />
        </Button>
      </div>
    </div>
  )
}

export default ProfileUpdateBar
