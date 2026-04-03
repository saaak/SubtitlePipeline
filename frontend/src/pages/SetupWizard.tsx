import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  activateModel,
  AppConfig,
  cloneConfig,
  defaultAppConfig,
  downloadModel,
  getConfig,
  getModels,
  ModelListResponse,
  setSetupComplete,
  testTranslation,
  translationContentTypeOptions,
  updateConfig,
} from '../api'

export function SetupWizard({
  onCompleted,
}: {
  onCompleted: () => Promise<void> | void
}) {
  const [step, setStep] = useState(1)
  const [config, setConfig] = useState<AppConfig>(cloneConfig(defaultAppConfig))
  const [models, setModels] = useState<ModelListResponse>({ items: [], current_model: '' })
  const [selectedModel, setSelectedModel] = useState('')
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const load = async () => {
    setLoading(true)
    try {
      const [nextConfig, nextModels] = await Promise.all([getConfig(), getModels()])
      setConfig(nextConfig)
      setModels(nextModels)
      setSelectedModel((current) => current || nextModels.current_model || nextModels.items.find((item) => item.status === 'installed')?.name || 'small')
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化信息读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const selectedModelItem = useMemo(
    () => models.items.find((item) => item.name === selectedModel),
    [models.items, selectedModel],
  )

  const canMoveFromStepOne = Boolean(selectedModelItem && selectedModelItem.status === 'installed')

  const handleDownload = async (name: string) => {
    try {
      const result = await downloadModel(name)
      setMessage(result.message)
      setSelectedModel(name)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型下载启动失败')
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const result = await testTranslation({
        enabled: config.translation.enabled,
        api_base_url: config.translation.api_base_url,
        api_key: config.translation.api_key,
        model: config.translation.model,
        timeout_seconds: config.translation.timeout_seconds,
        target_language: config.translation.target_languages[0] || 'zh-CN',
        content_type: config.translation.content_type,
      })
      if (result.success) {
        setMessage(result.message)
        setError('')
      } else {
        setError(result.message)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '翻译连接测试失败')
    } finally {
      setTesting(false)
    }
  }

  const completeSetup = async () => {
    if (!selectedModel) {
      setError('请先选择已安装模型')
      return
    }
    setFinishing(true)
    try {
      if (!selectedModelItem || selectedModelItem.status !== 'installed') {
        throw new Error('所选模型尚未安装完成')
      }
      await activateModel(selectedModel)
      await updateConfig({
        translation: config.translation,
      })
      await setSetupComplete(true)
      await onCompleted()
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化完成失败')
    } finally {
      setFinishing(false)
    }
  }

  if (loading) {
    return <div className="card muted">引导信息加载中…</div>
  }

  return (
    <section className="wizard-shell">
      <header className="wizard-header">
        <div>
          <h1>首次引导</h1>
          <p>完成模型准备与翻译配置后，即可进入任务主界面。</p>
        </div>
        <div className="wizard-steps">
          {[1, 2, 3].map((value) => (
            <span key={value} className={`wizard-step ${value === step ? 'active' : value < step ? 'done' : ''}`}>
              {value}
            </span>
          ))}
        </div>
      </header>

      {message ? <div className="alert success">{message}</div> : null}
      {error ? <div className="alert error">{error}</div> : null}

      {step === 1 ? (
        <div className="card">
          <div className="card-header">
            <div>
              <h2>步骤 1：模型准备</h2>
              <p>请选择一个已安装模型，或先触发下载。也可手动挂载本地模型到 /models 目录。</p>
            </div>
            <button onClick={() => void load()}>检测本地模型</button>
          </div>
          <div className="model-grid">
            {models.items.map((item) => (
              <button
                key={item.name}
                type="button"
                className={`model-card ${selectedModel === item.name ? 'selected' : ''}`}
                onClick={() => setSelectedModel(item.name)}
              >
                <div className="table-main">
                  <strong>{item.name}</strong>
                  <span className={`status-chip ${item.status}`}>{item.status}</span>
                </div>
                <span className="muted">{item.size_label}</span>
                {item.status === 'downloading' ? (
                  <div className="progress-block">
                    <div className="progress-bar">
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    <span>{item.progress}%</span>
                  </div>
                ) : null}
                {item.stalled ? <span className="status-chip stalled">下载超时</span> : null}
                {item.error ? <span className="muted">{item.error}</span> : null}
                {item.stalled && item.manual_download_url ? (
                  <a href={item.manual_download_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
                    前往 HuggingFace 手动下载
                  </a>
                ) : null}
                <span className="muted">{item.path}</span>
                <div className="inline-actions">
                  <button
                    type="button"
                    disabled={item.status !== 'not_installed'}
                    onClick={(event) => {
                      event.stopPropagation()
                      void handleDownload(item.name)
                    }}
                  >
                    下载
                  </button>
                  <span>{item.current ? '当前默认模型' : '可选模型'}</span>
                </div>
              </button>
            ))}
          </div>
          <div className="page-actions">
            <button disabled>上一步</button>
            <button disabled={!canMoveFromStepOne} onClick={() => setStep(2)}>
              下一步
            </button>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="card">
          <div className="card-header">
            <div>
              <h2>步骤 2：翻译配置</h2>
              <p>翻译配置为可选项，关闭后系统只生成源语言字幕。</p>
            </div>
            <label className="switch-row">
              <span>启用翻译</span>
              <input
                type="checkbox"
                checked={config.translation.enabled}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      enabled: event.target.checked,
                    },
                  }))
                }
              />
            </label>
          </div>
          <div className={`field-grid ${config.translation.enabled ? '' : 'disabled-section'}`}>
            <label>
              <span>API Base URL</span>
              <input
                disabled={!config.translation.enabled}
                value={config.translation.api_base_url}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      api_base_url: event.target.value,
                    },
                  }))
                }
              />
            </label>
            <label>
              <span>API Key</span>
              <input
                disabled={!config.translation.enabled}
                type="password"
                value={config.translation.api_key}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      api_key: event.target.value,
                    },
                  }))
                }
              />
            </label>
            <label>
              <span>模型</span>
              <input
                disabled={!config.translation.enabled}
                value={config.translation.model}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      model: event.target.value,
                    },
                  }))
                }
              />
            </label>
            <label>
              <span>目标语言</span>
              <input
                disabled={!config.translation.enabled}
                value={config.translation.target_languages.join(', ')}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      target_languages: event.target.value
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    },
                  }))
                }
              />
            </label>
            <label>
              <span>内容类型</span>
              <select
                disabled={!config.translation.enabled}
                value={config.translation.content_type}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    translation: {
                      ...current.translation,
                      content_type: event.target.value as AppConfig['translation']['content_type'],
                    },
                  }))
                }
              >
                {translationContentTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="page-actions">
            <button onClick={() => setStep(1)}>上一步</button>
            <div className="inline-actions">
              <button disabled={testing} onClick={() => void handleTest()}>
                {testing ? '测试中…' : '测试连接'}
              </button>
              <button onClick={() => setStep(3)}>下一步</button>
            </div>
          </div>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="card">
          <h2>步骤 3：完成确认</h2>
          <div className="summary-grid">
            <div className="summary-item">
              <span>模型</span>
              <strong>{selectedModel || '-'}</strong>
            </div>
            <div className="summary-item">
              <span>翻译</span>
              <strong>{config.translation.enabled ? '已启用' : '已关闭'}</strong>
            </div>
            <div className="summary-item">
              <span>翻译模型</span>
              <strong>{config.translation.enabled ? config.translation.model : '-'}</strong>
            </div>
            <div className="summary-item">
              <span>目标语言</span>
              <strong>{config.translation.enabled ? config.translation.target_languages.join(', ') || '-' : '-'}</strong>
            </div>
            <div className="summary-item">
              <span>内容类型</span>
              <strong>
                {config.translation.enabled
                  ? translationContentTypeOptions.find((option) => option.value === config.translation.content_type)?.label || config.translation.content_type
                  : '-'}
              </strong>
            </div>
          </div>
          <div className="page-actions">
            <button onClick={() => setStep(2)}>上一步</button>
            <button disabled={finishing} onClick={() => void completeSetup()}>
              {finishing ? '完成中…' : '完成初始化'}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  )
}
