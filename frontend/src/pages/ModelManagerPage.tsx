import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { activateModel, deleteModel, downloadModel, getModels, ModelItem, ModelListResponse } from '../api'
import { usePolling } from '../hooks'

const emptyModels: ModelListResponse = {
  items: [],
  current_model: '',
}

export function ModelManagerPage() {
  const [data, setData] = useState<ModelListResponse>(emptyModels)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busyModel, setBusyModel] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await getModels())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型读取失败')
    }
  }, [])

  usePolling(load, 2000, [])

  const hasDownloading = useMemo(
    () => data.items.some((item) => item.status === 'downloading'),
    [data.items],
  )

  const runAction = async (model: ModelItem, action: 'download' | 'delete' | 'activate') => {
    setBusyModel(model.name)
    try {
      if (action === 'download') {
        const result = await downloadModel(model.name)
        setMessage(result.message)
      }
      if (action === 'delete') {
        const result = await deleteModel(model.name)
        setMessage(result.message)
      }
      if (action === 'activate') {
        const result = await activateModel(model.name)
        setMessage(result.message)
      }
      await load()
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型操作失败')
    } finally {
      setBusyModel('')
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>模型管理</h1>
          <p>查看本地模型状态，支持下载、删除和切换当前使用的 ASR 模型。</p>
        </div>
        <button onClick={() => void load()}>立即刷新</button>
      </header>
      {message ? <div className="alert success">{message}</div> : null}
      {error ? <div className="alert error">{error}</div> : null}
      <div className="alert warning">
        可将模型文件直接挂载到 <strong>/models/&lt;模型名&gt;</strong> 目录，系统会在下次刷新时自动识别。
      </div>
      <div className="card">
        <div className="card-header">
          <h2>已知模型</h2>
          <span className="muted">{hasDownloading ? '检测到下载任务进行中' : `当前模型：${data.current_model || '-'}`}</span>
        </div>
        <table className="task-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>大小</th>
              <th>状态</th>
              <th>路径</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.name}>
                <td>
                  <div className="table-main">
                    <strong>{item.name}</strong>
                    {item.current ? <span className="status-chip installed">当前使用</span> : null}
                  </div>
                </td>
                <td>{item.size_label}</td>
                <td>
                  <div className="status-stack">
                    <span className={`status-chip ${item.status}`}>{item.status}</span>
                    {item.status === 'downloading' ? (
                      <div className="progress-inline">
                        <div className="progress-bar">
                          <span style={{ width: `${item.progress}%` }} />
                        </div>
                        <span>{item.progress}%</span>
                      </div>
                    ) : null}
                    {item.error ? <span className="muted">{item.error}</span> : null}
                  </div>
                </td>
                <td className="task-file">{item.path}</td>
                <td className="actions-cell wrap">
                  <button
                    disabled={item.status !== 'not_installed' || busyModel === item.name}
                    onClick={() => void runAction(item, 'download')}
                  >
                    下载
                  </button>
                  <button
                    disabled={item.status !== 'installed' || item.current || busyModel === item.name}
                    onClick={() => void runAction(item, 'activate')}
                  >
                    切换
                  </button>
                  <button
                    disabled={item.status !== 'installed' || item.current || busyModel === item.name}
                    onClick={() => void runAction(item, 'delete')}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card compact">
        <h2>使用建议</h2>
        <ul className="simple-list">
          <li>下载中的模型会自动展示进度，页面每 2 秒刷新一次。</li>
          <li>切换模型后会标记需要重启，任务页面会提示是否存在系统级变更。</li>
          <li>
            若首次部署后尚未完成初始化，可前往 <Link to="/setup">引导向导</Link> 完成模型准备与翻译配置。
          </li>
        </ul>
      </div>
    </section>
  )
}
