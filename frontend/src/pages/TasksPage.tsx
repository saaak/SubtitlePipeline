import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { cancelTask, checkResumeFeasibility, getTasks, ResumeCheckResponse, retryTask, TaskListResponse } from '../api'
import { usePolling } from '../hooks'

const PAGE_SIZE = 20

type TaskTab = 'all' | 'processing' | 'pending' | 'done' | 'failed'

const tabs: Array<{ key: TaskTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'processing', label: '进行中' },
  { key: 'pending', label: '待处理' },
  { key: 'done', label: '已完成' },
  { key: 'failed', label: '失败' },
]

function getVisiblePages(currentPage: number, totalPages: number): number[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1)
  }
  if (currentPage <= 3) {
    return [1, 2, 3, 4, totalPages]
  }
  if (currentPage >= totalPages - 2) {
    return [1, totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
  }
  return [1, currentPage - 1, currentPage, currentPage + 1, totalPages]
}

export function TasksPage() {
  const [data, setData] = useState<TaskListResponse>({ items: [], total: 0, page: 1, page_size: PAGE_SIZE, status_counts: {} })
  const [resumeChecks, setResumeChecks] = useState<Record<number, ResumeCheckResponse>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<TaskTab>('all')
  const [currentPage, setCurrentPage] = useState(1)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const nextData = await getTasks(activeTab === 'all' ? undefined : activeTab, currentPage, PAGE_SIZE)
      setData(nextData)
      if (activeTab === 'failed') {
        const checkEntries = await Promise.all(
          nextData.items
            .filter((task) => task.status === 'failed')
            .map(async (task) => {
              try {
                return [task.id, await checkResumeFeasibility(task.id)] as const
              } catch {
                return [task.id, { can_resume: false, missing: [] }] as const
              }
            }),
        )
        setResumeChecks(Object.fromEntries(checkEntries))
      } else {
        setResumeChecks({})
      }
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务读取失败')
    } finally {
      setLoading(false)
    }
  }, [activeTab, currentPage])

  usePolling(load, 3000, [activeTab, currentPage])

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size))
  const visiblePages = useMemo(() => getVisiblePages(currentPage, totalPages), [currentPage, totalPages])
  const statusCounts = data.status_counts
  const totalCount = useMemo(
    () => Object.values(statusCounts).reduce((sum, count) => sum + count, 0),
    [statusCounts],
  )

  const handleTabChange = (tab: TaskTab) => {
    setActiveTab(tab)
    setCurrentPage(1)
    if (tab !== 'failed') {
      setResumeChecks({})
    }
  }

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
        <div className="task-toolbar">
          <div className="tab-row">
            {tabs.map((tab) => {
              const count = tab.key === 'all' ? totalCount : statusCounts[tab.key] ?? 0
              return (
                <button
                  key={tab.key}
                  className={tab.key === activeTab ? 'tab-button active' : 'tab-button'}
                  onClick={() => handleTabChange(tab.key)}
                  type="button"
                >
                  <span>{tab.label}</span>
                  <strong>{count}</strong>
                </button>
              )
            })}
          </div>
          <div className="pagination">
            <span className="muted">第 {data.page} / {totalPages} 页</span>
            <button disabled={currentPage <= 1} onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))} type="button">
              上一页
            </button>
            {visiblePages.map((page) => (
              <button
                key={page}
                className={page === currentPage ? 'page-button active' : 'page-button'}
                onClick={() => setCurrentPage(page)}
                type="button"
              >
                {page}
              </button>
            ))}
            <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))} type="button">
              下一页
            </button>
          </div>
        </div>
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
                      {task.status === 'failed' ? (
                        <>
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
