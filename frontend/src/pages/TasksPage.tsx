import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { cancelTask, getTasks, retryTask, TaskListResponse } from '../api'
import { usePolling } from '../hooks'

export function TasksPage() {
  const [data, setData] = useState<TaskListResponse>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getTasks())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务读取失败')
    } finally {
      setLoading(false)
    }
  }, [])

  usePolling(load, 3000, [])

  const handleAction = async (taskId: number, type: 'cancel' | 'retry') => {
    try {
      if (type === 'cancel') {
        await cancelTask(taskId)
      } else {
        await retryTask(taskId)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务操作失败')
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>任务列表</h1>
          <p>轮询刷新当前任务状态、阶段和进度。</p>
        </div>
        <button onClick={() => void load()}>立即刷新</button>
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
                      void handleAction(task.id, 'retry')
                    }}
                  >
                    重试
                  </button>
                  <button
                    onClick={(event) => {
                      event.stopPropagation()
                      void handleAction(task.id, 'cancel')
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
