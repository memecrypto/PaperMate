import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Card } from '@/components/ui/Card'
import api from '@/lib/api'

const LoginPage: React.FC = () => {
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [registrationOpen, setRegistrationOpen] = useState<boolean | null>(null)
  const { login, register, isLoading, error, clearError } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/auth/registration-status')
      .then(res => {
        setRegistrationOpen(res.data.registration_open)
        if (!res.data.registration_open) setIsLogin(true)
      })
      .catch(() => {
        setRegistrationOpen(false)
        setIsLogin(true)
      })
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    try {
      if (isLogin) {
        await login(email, password)
        navigate('/')
      } else {
        await register(email, password, name || undefined)
        setIsLogin(true)
        alert('注册成功，请登录')
      }
    } catch {
      // Error handled in store
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 p-4">
      <Card className="w-full max-w-md p-8 space-y-6 bg-white shadow-xl rounded-2xl">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900">PaperMate</h1>
          <p className="text-gray-500 mt-2">
            {isLogin ? '欢迎回来' : '创建新账户'}
          </p>
        </div>

        {error && (
          <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isLogin && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">姓名</label>
              <Input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="您的姓名"
              />
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">邮箱</label>
            <Input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">密码</label>
            <Input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>

          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? '处理中...' : isLogin ? '登录' : '注册'}
          </Button>
        </form>

        <div className="text-center text-sm">
          {registrationOpen === false && !isLogin ? (
            <p className="text-gray-500">注册已关闭，请联系管理员</p>
          ) : registrationOpen !== false && (
            <button
              type="button"
              onClick={() => {
                setIsLogin(!isLogin)
                clearError()
              }}
              className="text-blue-600 hover:underline"
            >
              {isLogin ? '没有账号？去注册' : '已有账号？去登录'}
            </button>
          )}
        </div>
      </Card>
    </div>
  )
}

export default LoginPage
