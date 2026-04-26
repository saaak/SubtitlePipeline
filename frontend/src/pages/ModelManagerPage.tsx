import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { activateModel, deleteModel, downloadModel, getModels, ModelItem, ModelListResponse } from '../api'
import { usePolling } from '../hooks'

const emptyModels: ModelListResponse = {
  items: [],
  current_model: '',
}

const modelSeries = [
  { id: 'whisperx', label: 'WhisperX 系列', description: '标准 Whisper + 强制对齐' },
  { id: 'faster-whisper', label: 'Faster-Whisper 系列', description: '轻量快速推理' },
  { id: 'anime-whisper', label: 'Anime-Whisper 系列', description: '动漫日语优化' },
  { id: 'qwen', label: 'Qwen 系列', description: '多语言 LLM-based' },
  { id: 'qwen-forced', label: 'Qwen 对齐', description: '独立强制对齐模型' },
]

export function ModelManagerPage() {
  const [data, setData] = useState<ModelListResponse>(emptyModels)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busyModel, setBusyModel] = useState('')
  const [activeTab, setActiveTab] = useState<'asr' | 'aligner'>('asr')
  const [selectedSeries, setSelectedSeries] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await getModels())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型读取失败')
    }
  }, [])

  usePolling(load, 2000, [])

  const currentModel = useMemo(
    () => data.items.find((item) => item.current) || null,
    [data.items],
  )

  const filteredModels = useMemo(() => {
    const byTab = data.items.filter((item) => item.model_type === activeTab)
    if (!selectedSeries) return byTab
    return byTab.filter((item) => item.provider === selectedSeries)
  }, [activeTab, data.items, selectedSeries])

  const availableSeries = useMemo(() => {
    const providers = new Set<string>()
    data.items
      .filter((item) => item.model_type === activeTab)
      .forEach((item) => providers.add(item.provider))
    return modelSeries.filter((series) => providers.has(series.id))
  }, [activeTab, data.items])

  const counts = useMemo(
    () => ({
      asr: data.items.filter((item) => item.model_type === 'asr').length,
      aligner: data.items.filter((item) => item.model_type === 'aligner').length,
    }),
    [data.items],
  )
  const activeTabCount = activeTab === 'asr' ? counts.asr : counts.aligner

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
          <div>
            <h2>当前使用模型</h2>
            <p>当前生效的模型和安装状态。</p>
          </div>
          <span className={`status-chip ${currentModel?.status || 'not_installed'}`}>
            {currentModel?.status || 'unknown'}
          </span>
        </div>
        {currentModel ? (
          <div className="summary-grid">
            <div className="summary-item">
              <span className="field-label">模型</span>
              <strong>{currentModel.display_name}</strong>
              <span className="muted">{currentModel.name}</span>
            </div>
            <div className="summary-item">
              <span className="field-label">说明</span>
              <span className="muted">{currentModel.description}</span>
            </div>
            <div className="summary-item">
              <span className="field-label">标签</span>
              <div className="status-stack">
                {currentModel.tags.map((tag) => (
                  <span key={tag} className="status-chip not_installed">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
            <div className="summary-item">
              <span className="field-label">本地路径</span>
              <span className="muted">{currentModel.path}</span>
            </div>
          </div>
        ) : (
          <div className="muted">当前还没有激活模型。</div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <h2>所有模型</h2>
            <p>按识别模型和对齐模型分类查看，筛选栏固定左对齐。</p>
          </div>
        </div>
        <div className="model-filter-panel">
          <div className="tab-filter">
            <button
              className={activeTab === 'asr' ? 'active' : ''}
              onClick={() => {
                setActiveTab('asr')
                setSelectedSeries(null)
              }}
            >
              识别模型 ({counts.asr})
            </button>
            <button
              className={activeTab === 'aligner' ? 'active' : ''}
              onClick={() => {
                setActiveTab('aligner')
                setSelectedSeries(null)
              }}
            >
              对齐模型 ({counts.aligner})
            </button>
          </div>
          <div className="tag-filter">
            <button
              className={selectedSeries === null ? 'active' : ''}
              onClick={() => setSelectedSeries(null)}
            >
              全部 ({activeTabCount})
            </button>
            {availableSeries.map((series) => (
              <button
                key={series.id}
                className={selectedSeries === series.id ? 'active' : ''}
                onClick={() => setSelectedSeries(series.id)}
                title={series.description}
              >
                {series.label} ({data.items.filter((item) => item.provider === series.id).length})
              </button>
            ))}
          </div>
        </div>
        <div className="model-grid advanced-grid">
          {filteredModels.map((item) => (
            <div className="model-card" key={item.name}>
              <div className="table-main">
                <strong>{item.display_name}</strong>
                {item.current ? <span className="status-chip installed">当前使用</span> : null}
                <span className="status-chip not_installed">{item.model_type === 'asr' ? '识别' : '对齐'}</span>
              </div>
              <span className="muted">{item.description}</span>
              <div className="status-stack">
                <span className={`status-chip ${item.status}`}>{item.status}</span>
                <span className="muted">{item.size_label}</span>
                {item.tags.map((tag) => (
                  <span key={`${item.name}-${tag}`} className="status-chip not_installed">
                    {tag}
                  </span>
                ))}
              </div>
              {item.status === 'downloading' ? (
                <div className="progress-inline">
                  <div className="progress-bar">
                    <span style={{ width: `${item.progress}%` }} />
                  </div>
                  <span>{item.progress}%</span>
                </div>
              ) : null}
              {item.stalled ? <span className="status-chip stalled">下载超时</span> : null}
              {item.error ? <span className="muted">{item.error}</span> : null}
              <span className="muted">{item.path}</span>
              {item.stalled && item.manual_download_url ? (
                <a href={item.manual_download_url} target="_blank" rel="noreferrer">
                  前往 HuggingFace 手动下载
                </a>
              ) : null}
              <div className="actions-cell wrap">
                <button
                  disabled={item.status !== 'not_installed' || busyModel === item.name}
                  onClick={() => void runAction(item, 'download')}
                >
                  下载
                </button>
                <button
                  disabled={item.model_type !== 'asr' || item.status !== 'installed' || item.current || busyModel === item.name}
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
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card compact">
        <h2>使用建议</h2>
        <ul className="simple-list">
          <li>下载中的模型会自动展示进度，页面每 2 秒刷新一次。</li>
          <li>若下载超过一段时间没有进度，页面会给出超时提示与对应模型的手动下载地址。</li>
          <li>识别模型支持切换激活；对齐模型用于时间轴对齐步骤，不会替换当前 ASR 模型。</li>
          <li>
            若首次部署后尚未完成初始化，可前往 <Link to="/setup">引导向导</Link> 完成模型准备与翻译配置。
          </li>
        </ul>
      </div>
    </section>
  )
}
