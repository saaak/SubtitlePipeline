import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { cancelTask, checkResumeFeasibility, getTasks, ResumeCheckResponse, retryTask, TaskListResponse } from '../api'
import { usePolling } from '../hooks'

export function TasksPage() {
  const [data, setData] = useState<TaskListResponse>({ items: [], total: 0, page: 1, page_size: 20 })
  const [resumeChecks, setResumeChecks] = useState<Record<number, ResumeCheckResponse>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const nextData = await getTasks()
      setData(nextData)
      const retryableTasks = nextData.items.filter((task) => ['failed', 'cancelled', 'done'].includes(task.status))
      const checkEntries = await Promise.all(
        retryableTasks.map(async (task) => {
          try {
            return [task.id, await checkResumeFeasibility(task.id)] as const
          } catch {
            return [task.id, { can_resume: false, missing: [] }] as const
          }
        }),
      )
      setResumeChecks(Object.fromEntries(checkEntries))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务读取失败')
    } finally {
      setLoading(false)
    }
  }, [])

  usePolling(load, 3000, [])

  const handleAction = async (taskId: number, type: 'cancel' | 'restart' | 'resume') => {
    try {
      if (type === 'cancel') {
        await cancelTask(taskId)
      } else if (type === 'resume') {
        await retryTask(taskId, 'resume')
      } else {
        await retryTask(taskId, 'restart')
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
                <td className="actions-cell wrap">
                  {['failed', 'cancelled', 'done'].includes(task.status) ? (
                    <>
                      <button
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleAction(task.id, 'restart')
                        }}
                      >
                        重新执行
                      </button>
                      <button
                        disabled={!resumeChecks[task.id]?.can_resume}
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleAction(task.id, 'resume')
                        }}
                      >
                        继续执行
                      </button>
                      {resumeChecks[task.id] && !resumeChecks[task.id].can_resume ? <span className="muted">中间文件缺失</span> : null}
                    </>
                  ) : null}
                  {task.status === 'processing' ? (
                    <button
                      onClick={(event) => {
                        event.stopPropagation()
                        void handleAction(task.id, 'cancel')
                      }}
                    >
                      取消
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
