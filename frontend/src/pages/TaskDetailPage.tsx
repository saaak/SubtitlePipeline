import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getTask, getTaskLogs, LogResponse, Task } from '../api'
import { usePolling } from '../hooks'

export function TaskDetailPage() {
  const { taskId } = useParams()
  const [task, setTask] = useState<Task | null>(null)
  const [logs, setLogs] = useState<LogResponse>({ items: [], total: 0, page: 1, page_size: 20 })
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')

  const loadTask = useCallback(async () => {
    if (!taskId) {
      return
    }
    try {
      setTask(await getTask(taskId))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务详情读取失败')
    }
  }, [taskId])

  const loadLogs = useCallback(
    async (targetPage: number) => {
      if (!taskId) {
        return
      }
      try {
        setLogs(await getTaskLogs(taskId, targetPage))
        setPage(targetPage)
      } catch (err) {
        setError(err instanceof Error ? err.message : '日志读取失败')
      }
    },
    [taskId],
  )

  const poll = useCallback(async () => {
    await loadTask()
    await loadLogs(page)
  }, [loadLogs, loadTask, page])

  usePolling(poll, 3000, [page])

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
                {task.result_payload?.mux_path ? <li>{task.result_payload.mux_path}</li> : null}
              </ul>
            </div>
          </div>
          <div className="card">
            <div className="card-header">
              <h2>日志</h2>
              <div className="pagination">
                <button disabled={page <= 1} onClick={() => void loadLogs(page - 1)}>
                  上一页
                </button>
                <span>
                  第 {page} 页 / 共 {Math.max(Math.ceil(logs.total / logs.page_size), 1)} 页
                </span>
                <button
                  disabled={page >= Math.ceil(logs.total / logs.page_size)}
                  onClick={() => void loadLogs(page + 1)}
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
