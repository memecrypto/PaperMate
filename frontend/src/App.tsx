import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useEffect, useState } from 'react'
import LoginPage from '@/pages/LoginPage'
import DashboardPage from '@/pages/DashboardPage'
import PaperPage from '@/pages/PaperPage'
import SettingsModal from '@/components/SettingsModal'

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { fetchMe, user } = useAuthStore()
  const [isChecking, setIsChecking] = useState(true)

  useEffect(() => {
    const checkAuth = async () => {
      if (!user) {
        await fetchMe()
      }
      setIsChecking(false)
    }
    checkAuth()
  }, [])

  if (isChecking) {
    return null
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <SettingsModal />
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/paper/:id"
          element={
            <ProtectedRoute>
              <PaperPage />
            </ProtectedRoute>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
