import React, { useEffect, useState } from 'react'
import { X, Eye, EyeOff, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { useUIStore } from '@/stores/uiStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Card } from '@/components/ui/Card'
import api from '@/lib/api'

interface UserSettings {
  mineru_api_key_masked: string | null
  mineru_api_url: string | null
  mineru_use_cloud: boolean | null
  openai_api_key_masked: string | null
  openai_base_url: string | null
  openai_model: string | null
  tavily_api_key_masked: string | null
  has_mineru_key: boolean
  has_openai_key: boolean
  has_tavily_key: boolean
}

const SettingsModal: React.FC = () => {
  const { isSettingsOpen, toggleSettings } = useUIStore()

  const [formData, setFormData] = useState({
    mineru_api_key: '',
    mineru_api_url: '',
    mineru_use_cloud: true,
    tavily_api_key: '',
    openai_base_url: '',
    openai_api_key: '',
    openai_model: '',
  })

  const [currentSettings, setCurrentSettings] = useState<UserSettings | null>(null)
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({})
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({})

  useEffect(() => {
    if (isSettingsOpen) {
      fetchSettings()
    }
  }, [isSettingsOpen])

  const fetchSettings = async () => {
    try {
      const response = await api.get('/settings')
      setCurrentSettings(response.data)
      setFormData({
        mineru_api_key: '',
        mineru_api_url: response.data.mineru_api_url || '',
        mineru_use_cloud: response.data.mineru_use_cloud ?? true,
        tavily_api_key: '',
        openai_base_url: response.data.openai_base_url || '',
        openai_api_key: '',
        openai_model: response.data.openai_model || '',
      })
      setSaveStatus('idle')
      setStatusMessage('')
      setTestResults({})
    } catch (error) {
      console.error('Failed to fetch settings:', error)
    }
  }

  if (!isSettingsOpen) return null

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    setSaveStatus('idle')
  }

  const toggleShowKey = (field: string) => {
    setShowKeys(prev => ({ ...prev, [field]: !prev[field] }))
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveStatus('saving')

    try {
      const updateData: Record<string, string | boolean | null> = {}

      if (formData.mineru_api_key) {
        updateData.mineru_api_key = formData.mineru_api_key
      }
      if (formData.mineru_use_cloud !== (currentSettings?.mineru_use_cloud ?? true)) {
        updateData.mineru_use_cloud = formData.mineru_use_cloud
      }
      // Only send mineru_api_url when not using cloud
      if (!formData.mineru_use_cloud && formData.mineru_api_url !== (currentSettings?.mineru_api_url || '')) {
        updateData.mineru_api_url = formData.mineru_api_url || null
      }
      // Clear mineru_api_url when switching to cloud mode
      if (formData.mineru_use_cloud && currentSettings?.mineru_api_url) {
        updateData.mineru_api_url = null
      }
      if (formData.openai_api_key) {
        updateData.openai_api_key = formData.openai_api_key
      }
      if (formData.openai_base_url !== (currentSettings?.openai_base_url || '')) {
        updateData.openai_base_url = formData.openai_base_url || null
      }
      if (formData.openai_model !== (currentSettings?.openai_model || '')) {
        updateData.openai_model = formData.openai_model || null
      }
      if (formData.tavily_api_key) {
        updateData.tavily_api_key = formData.tavily_api_key
      }

      if (Object.keys(updateData).length === 0) {
        setSaveStatus('error')
        setStatusMessage('没有需要保存的更改')
        return
      }

      const response = await api.put('/settings', updateData)
      setCurrentSettings(response.data)
      setFormData({
        mineru_api_key: '',
        mineru_api_url: response.data.mineru_api_url || '',
        mineru_use_cloud: response.data.mineru_use_cloud ?? true,
        tavily_api_key: '',
        openai_base_url: response.data.openai_base_url || '',
        openai_api_key: '',
        openai_model: response.data.openai_model || '',
      })
      setSaveStatus('success')
      setStatusMessage('设置已保存')
      setTestResults({})

      setTimeout(() => {
        setSaveStatus('idle')
      }, 3000)
    } catch (error: any) {
      setSaveStatus('error')
      setStatusMessage(error.response?.data?.detail || '保存失败，请重试')
    }
  }

  const handleTestConnection = async (provider: string) => {
    setTestingProvider(provider)
    try {
      const response = await api.post(`/settings/test/${provider}`)
      setTestResults(prev => ({
        ...prev,
        [provider]: response.data
      }))
    } catch (error: any) {
      setTestResults(prev => ({
        ...prev,
        [provider]: {
          success: false,
          message: error.response?.data?.detail || '测试失败'
        }
      }))
    } finally {
      setTestingProvider(null)
    }
  }

  const renderPasswordField = (
    label: string,
    name: 'mineru_api_key' | 'openai_api_key' | 'tavily_api_key',
    placeholder: string,
    provider: string,
    required: boolean = false
  ) => {
    const hasKey = currentSettings?.[`has_${provider}_key` as keyof UserSettings]
    const maskedKey = currentSettings?.[`${provider}_api_key_masked` as keyof UserSettings]
    const testResult = testResults[provider]

    return (
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-700 flex justify-between">
          <span>{label} {required && <span className="text-red-500">*</span>}</span>
          {hasKey && (
            <span className="text-xs text-green-600 font-normal">已配置</span>
          )}
        </label>
        <div className="relative">
          <Input
            type={showKeys[name] ? 'text' : 'password'}
            name={name}
            value={formData[name]}
            onChange={handleChange}
            placeholder={hasKey ? `当前: ${maskedKey}` : placeholder}
            className="pr-10"
          />
          <button
            type="button"
            onClick={() => toggleShowKey(name)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          >
            {showKeys[name] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {hasKey && (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleTestConnection(provider)}
              disabled={testingProvider === provider}
              className="text-xs"
            >
              {testingProvider === provider ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : null}
              测试连接
            </Button>
            {testResult && (
              <span className={`text-xs flex items-center gap-1 ${testResult.success ? 'text-green-600' : 'text-red-600'}`}>
                {testResult.success ? <CheckCircle className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                {testResult.message}
              </span>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <Card className="w-full max-w-lg shadow-xl animate-in fade-in zoom-in duration-200 bg-white">
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <h2 className="text-xl font-semibold text-gray-900">API 设置</h2>
          <button onClick={toggleSettings} className="text-gray-400 hover:text-gray-500">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSave} className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          <div className="space-y-4">
            <div className="pb-4 border-b border-gray-100">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">MinerU 配置 (PDF 解析)</h3>
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="mineru_use_cloud"
                    checked={formData.mineru_use_cloud}
                    onChange={(e) => setFormData(prev => ({ ...prev, mineru_use_cloud: e.target.checked }))}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <label htmlFor="mineru_use_cloud" className="text-sm font-medium text-gray-700">
                    使用云服务
                  </label>
                </div>
                {!formData.mineru_use_cloud && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-700">API URL</label>
                    <Input
                      type="text"
                      name="mineru_api_url"
                      value={formData.mineru_api_url}
                      onChange={handleChange}
                      placeholder="e.g. http://localhost:8010"
                    />
                    <p className="text-xs text-gray-500">本地部署的 MinerU 服务地址</p>
                  </div>
                )}
                {renderPasswordField('API Key', 'mineru_api_key', '请输入 MinerU API Key', 'mineru', formData.mineru_use_cloud)}
              </div>
              <p className="text-xs text-gray-500 mt-2">
                从 <a href="https://mineru.net" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">mineru.net</a> 获取 API Key
              </p>
            </div>

            <div className="pb-4 border-b border-gray-100">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">OpenAI 配置 (AI 分析)</h3>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-700">
                    Base URL <span className="text-red-500">*</span>
                  </label>
                  <Input
                    type="text"
                    name="openai_base_url"
                    value={formData.openai_base_url}
                    onChange={handleChange}
                    placeholder="e.g. https://api.openai.com/v1"
                  />
                  <p className="text-xs text-gray-500">支持 OpenAI 兼容的 API 服务</p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-700">Model</label>
                  <Input
                    type="text"
                    name="openai_model"
                    value={formData.openai_model}
                    onChange={handleChange}
                    placeholder="e.g. gpt-4o"
                  />
                  <p className="text-xs text-gray-500">使用的模型名称，如 gpt-4o、gpt-4-turbo 等</p>
                </div>
                {renderPasswordField('API Key', 'openai_api_key', 'sk-...', 'openai', true)}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">搜索配置 (可选)</h3>
              {renderPasswordField('Tavily API Key', 'tavily_api_key', 'tvly-...', 'tavily')}
              <p className="text-xs text-gray-500 mt-2">
                用于 AI 对话中的网络搜索功能
              </p>
            </div>
          </div>

          {saveStatus !== 'idle' && saveStatus !== 'saving' && (
            <div className={`flex items-center gap-2 text-sm p-3 rounded-md ${
              saveStatus === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
            }`}>
              {saveStatus === 'success' ? (
                <CheckCircle className="h-4 w-4" />
              ) : (
                <AlertCircle className="h-4 w-4" />
              )}
              {statusMessage}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={toggleSettings}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={saveStatus === 'saving'}
            >
              {saveStatus === 'saving' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  保存中...
                </>
              ) : '保存配置'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}

export default SettingsModal
