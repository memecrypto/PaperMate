import React, { useEffect, useState } from 'react'
import { User, X, RefreshCw, Plus } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useUserProfileStore } from '@/stores/userProfileStore'
import { cn } from '@/lib/utils'

const EXPERTISE_LEVELS = ['beginner', 'intermediate', 'advanced'] as const
const LEVEL_LABELS: Record<string, string> = {
  beginner: '初学者',
  intermediate: '中级',
  advanced: '高级'
}

const UserProfilePanel: React.FC = () => {
  const { profile, isLoading, fetchProfile, updateProfile, resetProfile, removeExpertise, removeDifficultTopic, removeMasteredTopic } = useUserProfileStore()
  const [newExpertise, setNewExpertise] = useState({ topic: '', level: 'intermediate' })
  const [newDifficult, setNewDifficult] = useState('')
  const [newMastered, setNewMastered] = useState('')
  const [editingPrefs, setEditingPrefs] = useState(false)
  const [prefsForm, setPrefsForm] = useState({
    explanation_style: 'balanced',
    likes_examples: false,
    likes_analogies: false,
    math_comfort: 'medium'
  })

  useEffect(() => {
    fetchProfile()
  }, [fetchProfile])

  useEffect(() => {
    if (profile?.preferences) {
      setPrefsForm({
        explanation_style: profile.preferences.explanation_style || 'balanced',
        likes_examples: profile.preferences.likes_examples || false,
        likes_analogies: profile.preferences.likes_analogies || false,
        math_comfort: profile.preferences.math_comfort || 'medium'
      })
    }
  }, [profile?.preferences])

  const handleAddExpertise = async () => {
    if (!newExpertise.topic.trim()) return
    await updateProfile({
      expertise_levels: { [newExpertise.topic.trim()]: newExpertise.level }
    })
    setNewExpertise({ topic: '', level: 'intermediate' })
  }

  const handleAddDifficult = async () => {
    if (!newDifficult.trim() || !profile) return
    await updateProfile({
      difficult_topics: [...(profile.difficult_topics || []), newDifficult.trim()]
    })
    setNewDifficult('')
  }

  const handleAddMastered = async () => {
    if (!newMastered.trim() || !profile) return
    await updateProfile({
      mastered_topics: [...(profile.mastered_topics || []), newMastered.trim()]
    })
    setNewMastered('')
  }

  const handleSavePrefs = async () => {
    await updateProfile({ preferences: prefsForm })
    setEditingPrefs(false)
  }

  if (isLoading && !profile) {
    return (
      <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200 items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-primary-500" />
        <p className="mt-2 text-sm text-gray-500">加载中...</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <User className="h-4 w-4 text-primary-500" />
            学习画像
          </h3>
          <p className="text-xs text-gray-500">AI会根据画像调整回答风格</p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (window.confirm('确定重置画像吗？所有学习记录将被清除。')) {
              resetProfile()
            }
          }}
          title="重置画像"
          className="text-gray-400 hover:text-red-500"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Expertise Levels */}
        <section>
          <h4 className="text-sm font-medium text-gray-700 mb-2">知识水平</h4>
          <div className="space-y-2">
            {Object.entries(profile?.expertise_levels || {}).map(([topic, level]) => (
              <div key={topic} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
                <div>
                  <span className="text-sm text-gray-900">{topic}</span>
                  <span className={cn(
                    "ml-2 text-xs px-2 py-0.5 rounded-full",
                    level === 'beginner' && "bg-green-100 text-green-700 border border-green-200",
                    level === 'intermediate' && "bg-blue-100 text-blue-700 border border-blue-200",
                    level === 'advanced' && "bg-purple-100 text-purple-700 border border-purple-200"
                  )}>
                    {LEVEL_LABELS[level] || level}
                  </span>
                </div>
                <Button variant="ghost" size="icon" onClick={() => removeExpertise(topic)} className="text-gray-400 hover:text-red-500">
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="添加主题..."
                value={newExpertise.topic}
                onChange={(e) => setNewExpertise({ ...newExpertise, topic: e.target.value })}
                className="flex-1 text-sm border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                onKeyDown={(e) => e.key === 'Enter' && handleAddExpertise()}
              />
              <select
                value={newExpertise.level}
                onChange={(e) => setNewExpertise({ ...newExpertise, level: e.target.value })}
                className="text-sm border border-gray-300 bg-white rounded-lg px-2 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                {EXPERTISE_LEVELS.map(l => (
                  <option key={l} value={l}>{LEVEL_LABELS[l]}</option>
                ))}
              </select>
              <Button size="sm" onClick={handleAddExpertise} disabled={!newExpertise.topic.trim()}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>

        {/* Difficult Topics */}
        <section>
          <h4 className="text-sm font-medium text-gray-700 mb-2">困难主题</h4>
          <p className="text-xs text-gray-500 mb-2">AI会对这些主题进行更详细的解释</p>
          <div className="flex flex-wrap gap-2 mb-2">
            {(profile?.difficult_topics || []).map((topic) => (
              <span key={topic} className="inline-flex items-center gap-1 bg-red-50 text-red-700 text-xs px-2 py-1 rounded-full border border-red-200">
                {topic}
                <button onClick={() => removeDifficultTopic(topic)} className="hover:text-red-500">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="添加困难主题..."
              value={newDifficult}
              onChange={(e) => setNewDifficult(e.target.value)}
              className="flex-1 text-sm border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              onKeyDown={(e) => e.key === 'Enter' && handleAddDifficult()}
            />
            <Button size="sm" onClick={handleAddDifficult} disabled={!newDifficult.trim()}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </section>

        {/* Mastered Topics */}
        <section>
          <h4 className="text-sm font-medium text-gray-700 mb-2">已掌握主题</h4>
          <p className="text-xs text-gray-500 mb-2">AI会跳过这些主题的基础解释</p>
          <div className="flex flex-wrap gap-2 mb-2">
            {(profile?.mastered_topics || []).map((topic) => (
              <span key={topic} className="inline-flex items-center gap-1 bg-green-50 text-green-700 text-xs px-2 py-1 rounded-full border border-green-200">
                {topic}
                <button onClick={() => removeMasteredTopic(topic)} className="hover:text-green-500">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="添加已掌握主题..."
              value={newMastered}
              onChange={(e) => setNewMastered(e.target.value)}
              className="flex-1 text-sm border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              onKeyDown={(e) => e.key === 'Enter' && handleAddMastered()}
            />
            <Button size="sm" onClick={handleAddMastered} disabled={!newMastered.trim()}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </section>

        {/* Preferences */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-700">偏好设置</h4>
            {!editingPrefs && (
              <Button variant="ghost" size="sm" onClick={() => setEditingPrefs(true)} className="text-primary-600">
                编辑
              </Button>
            )}
          </div>
          {editingPrefs ? (
            <div className="space-y-3 bg-gray-50 rounded-lg p-3 border border-gray-200">
              <div>
                <label className="text-xs text-gray-500">解释风格</label>
                <select
                  value={prefsForm.explanation_style}
                  onChange={(e) => setPrefsForm({ ...prefsForm, explanation_style: e.target.value })}
                  className="mt-1 w-full text-sm border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value="concise">简洁</option>
                  <option value="balanced">平衡</option>
                  <option value="detailed">详细</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">数学舒适度</label>
                <select
                  value={prefsForm.math_comfort}
                  onChange={(e) => setPrefsForm({ ...prefsForm, math_comfort: e.target.value })}
                  className="mt-1 w-full text-sm border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value="low">低 - 尽量避免公式</option>
                  <option value="medium">中 - 适度使用公式</option>
                  <option value="high">高 - 可以使用复杂公式</option>
                </select>
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={prefsForm.likes_examples}
                    onChange={(e) => setPrefsForm({ ...prefsForm, likes_examples: e.target.checked })}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  喜欢例子
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={prefsForm.likes_analogies}
                    onChange={(e) => setPrefsForm({ ...prefsForm, likes_analogies: e.target.checked })}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  喜欢类比
                </label>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" size="sm" onClick={() => setEditingPrefs(false)}>
                  取消
                </Button>
                <Button size="sm" onClick={handleSavePrefs}>
                  保存
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-sm text-gray-500 space-y-1">
              <p>解释风格: {prefsForm.explanation_style === 'concise' ? '简洁' : prefsForm.explanation_style === 'detailed' ? '详细' : '平衡'}</p>
              <p>数学舒适度: {prefsForm.math_comfort === 'low' ? '低' : prefsForm.math_comfort === 'high' ? '高' : '中'}</p>
              <p>
                {prefsForm.likes_examples && '喜欢例子 '}
                {prefsForm.likes_analogies && '喜欢类比'}
                {!prefsForm.likes_examples && !prefsForm.likes_analogies && '无特殊偏好'}
              </p>
            </div>
          )}
        </section>
      </div>

      {profile?.updated_at && (
        <div className="px-4 py-2 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500">
            上次更新: {new Date(profile.updated_at).toLocaleString()}
          </p>
        </div>
      )}
    </div>
  )
}

export default UserProfilePanel
