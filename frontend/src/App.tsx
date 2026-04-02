import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { getSystemStatus, SystemStatus } from './api'
import { ModelManagerPage } from './pages/ModelManagerPage'
import { SettingsPage } from './pages/SettingsPage'
import { SetupWizard } from './pages/SetupWizard'
import { TaskDetailPage } from './pages/TaskDetailPage'
import { TasksPage } from './pages/TasksPage'

function SidebarLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">SubPipeline</div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            任务列表
          </NavLink>
          <NavLink to="/models" className={({ isActive }) => (isActive ? 'active' : '')}>
            模型管理
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? 'active' : '')}>
            设置
          </NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<TasksPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          <Route path="/models" element={<ModelManagerPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const location = useLocation()

  const loadStatus = async () => {
    setLoading(true)
    try {
      setStatus(await getSystemStatus())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '系统状态读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  if (loading) {
    return <div className="app-loading">系统状态加载中…</div>
  }

  if (error) {
    return (
      <div className="app-loading">
        <div className="alert error">{error}</div>
        <button onClick={() => void loadStatus()}>重试</button>
      </div>
    )
  }

  if (!status) {
    return <div className="app-loading">缺少系统状态</div>
  }

  if (!status.setup_complete) {
    return (
      <Routes>
        <Route path="/setup" element={<SetupWizard onCompleted={loadStatus} />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    )
  }

  if (location.pathname === '/setup') {
    return <Navigate to="/" replace />
  }

  return <SidebarLayout />
}
