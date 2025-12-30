import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, LogOut, FileText, Upload, LayoutGrid, Search, Settings } from 'lucide-react'
import { useProjectStore } from '@/stores/projectStore'
import { usePaperStore } from '@/stores/paperStore'
import { useAuthStore } from '@/stores/authStore'
import { useUIStore } from '@/stores/uiStore'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'

const DashboardPage: React.FC = () => {
  const { projects, fetchProjects, createProject, currentProject, setCurrentProject } = useProjectStore()
  const { papers, fetchPapers, uploadPaper } = usePaperStore()
  const { logout, user } = useAuthStore()
  const { toggleSettings } = useUIStore()
  const [isCreating, setIsCreating] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  useEffect(() => {
    if (currentProject) {
      fetchPapers(currentProject.id)
    }
  }, [currentProject, fetchPapers])

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newProjectName.trim()) return
    const project = await createProject({
      name: newProjectName,
      org_id: projects[0]?.org_id || ''
    })
    setCurrentProject(project)
    setNewProjectName('')
    setIsCreating(false)
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !currentProject) return

    setIsUploading(true)
    try {
      const paper = await uploadPaper(file, currentProject.id)
      navigate(`/paper/${paper.id}`)
    } catch (error) {
      console.error('Upload failed', error)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 flex flex-col overflow-hidden">
      {/* Header */}
      <header className="z-10 h-16 border-b border-gray-200 bg-white flex items-center justify-between px-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-primary-500 to-blue-600 flex items-center justify-center">
            <span className="font-bold text-white text-lg">P</span>
          </div>
          <span className="font-bold text-lg tracking-tight text-gray-900">PAPER<span className="text-primary-600">MATE</span></span>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3 px-4 py-1.5 rounded-full bg-gray-100 border border-gray-200">
            <div className="w-2 h-2 rounded-full bg-green-500"></div>
            <span className="text-xs font-mono text-gray-600 uppercase tracking-wider">{user?.email}</span>
          </div>
          <Button variant="ghost" size="sm" onClick={toggleSettings} className="text-gray-500 hover:text-primary-600" title="API 设置">
            <Settings className="h-4 w-4 mr-2" />
            设置
          </Button>
          <Button variant="ghost" size="sm" onClick={logout} className="text-gray-500 hover:text-red-500">
            <LogOut className="h-4 w-4 mr-2" />
            退出
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-72 border-r border-gray-200 bg-white flex flex-col">
          <div className="p-6">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-xs font-bold text-gray-500 uppercase tracking-widest">项目列表</h2>
              <button
                onClick={() => setIsCreating(true)}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-primary-600 transition-colors border border-transparent hover:border-primary-200"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>

            {isCreating && (
              <form onSubmit={handleCreateProject} className="mb-6 p-4 rounded-lg bg-gray-50 border border-gray-200">
                <Input
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="项目名称..."
                  className="mb-3 h-9"
                  autoFocus
                />
                <div className="flex gap-2">
                  <Button type="submit" size="sm" variant="default" className="flex-1 h-8 text-xs">创建</Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setIsCreating(false)} className="h-8 text-xs">取消</Button>
                </div>
              </form>
            )}

            <div className="space-y-1">
              {projects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => setCurrentProject(project)}
                  className={`w-full text-left px-4 py-3 rounded-lg transition-all duration-200 group ${
                    currentProject?.id === project.id
                      ? 'bg-primary-50 text-primary-700 border border-primary-200'
                      : 'hover:bg-gray-50 text-gray-600 hover:text-gray-900 border border-transparent'
                  }`}
                >
                  <div className="font-medium truncate flex items-center gap-2">
                    <LayoutGrid className={`h-4 w-4 ${currentProject?.id === project.id ? 'text-primary-600' : 'text-gray-400 group-hover:text-gray-600'}`} />
                    {project.name}
                  </div>
                  {project.domain && (
                    <div className="text-xs text-gray-500 mt-1 ml-6">{project.domain}</div>
                  )}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-8 overflow-y-auto bg-gray-50">
          {currentProject ? (
            <div className="max-w-7xl mx-auto space-y-8">
              <div className="flex justify-between items-end pb-6 border-b border-gray-200">
                <div>
                  <h1 className="text-4xl font-bold text-gray-900 tracking-tight mb-2">{currentProject.name}</h1>
                  <p className="text-gray-500 font-mono text-sm">
                    {currentProject.domain || '研究与分析'}
                  </p>
                </div>
                <label className="cursor-pointer group relative">
                  <input
                    type="file"
                    accept=".pdf"
                    onChange={handleFileUpload}
                    className="hidden"
                    disabled={isUploading}
                  />
                  <Button as="span" disabled={isUploading}>
                    <Upload className={`h-4 w-4 mr-2 ${isUploading ? 'animate-bounce' : ''}`} />
                    {isUploading ? '上传中...' : '上传论文'}
                  </Button>
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {papers.map((paper) => (
                  <Card
                    key={paper.id}
                    className="group hover:-translate-y-1 hover:shadow-lg cursor-pointer overflow-hidden"
                    onClick={() => navigate(`/paper/${paper.id}`)}
                  >
                    <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary-500 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    <div className="p-5 flex flex-col h-full">
                      <div className="flex items-start gap-4 mb-4">
                        <div className="p-3 rounded-lg bg-primary-50 text-primary-600 group-hover:bg-primary-100 transition-colors">
                          <FileText className="h-6 w-6" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h3 className="font-semibold text-gray-900 leading-snug line-clamp-2 group-hover:text-primary-700 transition-colors">
                            {paper.title}
                          </h3>
                          {paper.authors && (
                            <p className="text-xs text-gray-500 mt-2 truncate">{paper.authors}</p>
                          )}
                        </div>
                      </div>

                      <div className="mt-auto pt-4 border-t border-gray-100 flex items-center justify-between">
                        <span className={`text-xs px-2 py-1 rounded border ${
                          paper.status === 'ready'
                            ? 'border-green-200 text-green-700 bg-green-50'
                            : paper.status === 'parsing'
                            ? 'border-yellow-200 text-yellow-700 bg-yellow-50'
                            : 'border-gray-200 text-gray-600 bg-gray-50'
                        }`}>
                          {paper.status === 'ready' ? '已解析' : paper.status === 'parsing' ? '解析中...' : paper.status}
                        </span>
                        <span className="text-xs text-gray-400 font-mono">PDF</span>
                      </div>
                    </div>
                  </Card>
                ))}

                {papers.length === 0 && (
                  <div className="col-span-full py-20 flex flex-col items-center justify-center text-gray-500 border-2 border-dashed border-gray-200 rounded-2xl bg-white">
                    <Search className="h-12 w-12 mb-4 text-gray-300" />
                    <p className="text-lg">暂无论文</p>
                    <p className="text-sm text-gray-400">上传一篇PDF开始分析</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-gray-500 space-y-4">
              <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center">
                <LayoutGrid className="h-8 w-8 text-gray-400" />
              </div>
              <p>选择一个项目开始</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default DashboardPage
