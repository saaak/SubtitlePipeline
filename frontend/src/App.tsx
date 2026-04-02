import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'

type Task = {
  id: number
  file_path: string
  status: string
  stage: string
  progress: number
  retry_count: number
  max_retries: number
  cancel_requested: number | boolean
  restart_required?: number | boolean
  error_message?: string | null
  result_payload?: {
    subtitle_paths?: string[]
  } | null
  config_snapshot?: Record<string, unknown> | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

type TaskListResponse = {
  items: Task[]
  total: number
  page: number
  page_size: number
}

type LogItem = {
  id: number
  stage: string
  level: string
  message: string
  timestamp: string
}

type LogResponse = {
  items: LogItem[]
  total: number
  page: number
  page_size: number
}

type ConfigState = {
  file: Record<string, unknown>
  processing: Record<string, unknown>
  whisper: Record<string, unknown>
  translation: Record<string, unknown>
  subtitle: Record<string, unknown>
  logging: Record<string, unknown>
  meta?: {
    restart_required: boolean
  }
}

const defaultConfig: ConfigState = {
  file: {},
  processing: {},
  whisper: {},
  translation: {},
  subtitle: {},
  logging: {},
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.json() as Promise<T>
}

function usePolling(callback: () => void, intervalMs: number) {
  useEffect(() => {
    callback()
    const timer = window.setInterval(callback, intervalMs)
    return () => window.clearInterval(timer)
  }, [callback, intervalMs])
}

function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">SubPipeline</div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            任务列表
          </NavLink>
          <NavLink to="/config" className={({ isActive }) => (isActive ? 'active' : '')}>
            配置管理
          </NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<TasksPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          <Route path="/config" element={<ConfigPage />} />
        </Routes>
      </main>
    </div>
  )
}

function TasksPage() {
  const [data, setData] = useState<TaskListResponse>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const load = async () => {
    setLoading(true)
    try {
      setData(await api<TaskListResponse>('/api/tasks?page=1&page_size=20'))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务读取失败')
    } finally {
      setLoading(false)
    }
  }
  usePolling(load, 3000)

  const action = async (taskId: number, type: 'cancel' | 'retry') => {
    await api(`/api/tasks/${taskId}/${type}`, { method: 'POST' })
    load()
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>任务列表</h1>
          <p>轮询刷新当前任务状态、阶段和进度。</p>
        </div>
        <button onClick={load}>立即刷新</button>
      </header>
      {error ? <div className="alert error">{error}</div> : null}
      <div className="card">
        {loading ? <div className="muted">加载中…</div> : null}
        <table className="task-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>文件</th>
              <th>状态</th>
              <th>阶段</th>
              <th>进度</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((task) => (
              <tr key={task.id} onClick={() => navigate(`/tasks/${task.id}`)}>
                <td>{task.id}</td>
                <td className="task-file">{task.file_path}</td>
                <td>{task.status}</td>
                <td>{task.stage}</td>
                <td>{task.progress}%</td>
                <td>{new Date(task.updated_at).toLocaleString()}</td>
                <td className="actions-cell">
                  <button
                    onClick={(event) => {
                      event.stopPropagation()
                      action(task.id, 'retry')
                    }}
                  >
                    重试
                  </button>
                  <button
                    onClick={(event) => {
                      event.stopPropagation()
                      action(task.id, 'cancel')
                    }}
                  >
                    取消
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TaskDetailPage() {
  const { taskId } = useParams()
  const [task, setTask] = useState<Task | null>(null)
  const [logs, setLogs] = useState<LogResponse>({ items: [], total: 0, page: 1, page_size: 20 })
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')

  const loadTask = async () => {
    if (!taskId) {
      return
    }
    try {
      setTask(await api<Task>(`/api/tasks/${taskId}`))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务详情读取失败')
    }
  }

  const loadLogs = async (targetPage: number) => {
    if (!taskId) {
      return
    }
    try {
      setLogs(await api<LogResponse>(`/api/tasks/${taskId}/logs?page=${targetPage}&page_size=20`))
      setPage(targetPage)
    } catch (err) {
      setError(err instanceof Error ? err.message : '日志读取失败')
    }
  }

  usePolling(() => {
    loadTask()
    loadLogs(page)
  }, 3000)

  if (!taskId) {
    return <div className="alert error">缺少任务 ID</div>
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>任务详情 #{taskId}</h1>
          <p>查看阶段、输出路径与结构化日志。</p>
        </div>
        <Link to="/">返回列表</Link>
      </header>
      {error ? <div className="alert error">{error}</div> : null}
      {task ? (
        <>
          <div className="detail-grid">
            <div className="card">
              <h2>概览</h2>
              <dl className="detail-list">
                <div>
                  <dt>文件</dt>
                  <dd>{task.file_path}</dd>
                </div>
                <div>
                  <dt>状态</dt>
                  <dd>{task.status}</dd>
                </div>
                <div>
                  <dt>阶段</dt>
                  <dd>{task.stage}</dd>
                </div>
                <div>
                  <dt>进度</dt>
                  <dd>{task.progress}%</dd>
                </div>
                <div>
                  <dt>错误</dt>
                  <dd>{task.error_message || '-'}</dd>
                </div>
              </dl>
            </div>
            <div className="card">
              <h2>输出</h2>
              <ul className="simple-list">
                {task.result_payload?.subtitle_paths?.length ? (
                  task.result_payload.subtitle_paths.map((path) => <li key={path}>{path}</li>)
                ) : (
                  <li>暂无输出</li>
                )}
              </ul>
            </div>
          </div>
          <div className="card">
            <div className="card-header">
              <h2>日志</h2>
              <div className="pagination">
                <button disabled={page <= 1} onClick={() => loadLogs(page - 1)}>
                  上一页
                </button>
                <span>
                  第 {page} 页 / 共 {Math.max(Math.ceil(logs.total / logs.page_size), 1)} 页
                </span>
                <button
                  disabled={page >= Math.ceil(logs.total / logs.page_size)}
                  onClick={() => loadLogs(page + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
            <ul className="log-list">
              {logs.items.map((log) => (
                <li key={log.id}>
                  <span>{new Date(log.timestamp).toLocaleString()}</span>
                  <strong>{log.level}</strong>
                  <span>{log.stage}</span>
                  <span>{log.message}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : (
        <div className="card muted">加载中…</div>
      )}
    </section>
  )
}

function ConfigPage() {
  const [config, setConfig] = useState<ConfigState>(defaultConfig)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const load = async () => {
    const current = await api<ConfigState>('/api/config')
    setConfig(current)
  }

  useEffect(() => {
    load()
  }, [])

  const updateField = (group: keyof ConfigState, key: string, value: string) => {
    if (group === 'meta') {
      return
    }
    setConfig((current) => {
      const next = structuredClone(current)
      const target = next[group] as Record<string, unknown>
      const previous = target[key]
      if (Array.isArray(previous)) {
        target[key] = value.split(',').map((item) => item.trim()).filter(Boolean)
      } else if (typeof previous === 'number') {
        target[key] = Number(value)
      } else if (typeof previous === 'boolean') {
        target[key] = value === 'true'
      } else {
        target[key] = value
      }
      return next
    })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api('/api/config', {
        method: 'PUT',
        body: JSON.stringify({
          file: config.file,
          processing: config.processing,
          whisper: config.whisper,
          translation: config.translation,
          subtitle: config.subtitle,
          logging: config.logging,
        }),
      })
      setMessage('配置已保存')
      load()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '配置保存失败')
    } finally {
      setSaving(false)
    }
  }

  const groups = useMemo(
    () =>
      (['file', 'processing', 'whisper', 'translation', 'subtitle', 'logging'] as const).map((group) => ({
        group,
        values: config[group],
      })),
    [config],
  )

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>配置管理</h1>
          <p>覆盖文件、处理、识别、翻译、字幕与日志配置。</p>
        </div>
      </header>
      {message ? <div className="alert success">{message}</div> : null}
      {config.meta?.restart_required ? <div className="alert warning">检测到系统级配置更新，需要重启 Scanner/Worker。</div> : null}
      <form className="config-form" onSubmit={submit}>
        {groups.map(({ group, values }) => (
          <div className="card" key={group}>
            <h2>{group}</h2>
            <div className="config-grid">
              {Object.entries(values).map(([key, value]) => (
                <label key={key}>
                  <span>{key}</span>
                  <input
                    value={Array.isArray(value) ? value.join(', ') : String(value)}
                    onChange={(event) => updateField(group, key, event.target.value)}
                  />
                </label>
              ))}
            </div>
          </div>
        ))}
        <button type="submit" disabled={saving}>
          {saving ? '保存中…' : '保存配置'}
        </button>
      </form>
    </section>
  )
}

export default function App() {
  return <Layout />
}
