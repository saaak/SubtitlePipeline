import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AppConfig,
  cloneConfig,
  defaultAppConfig,
  getConfig,
  getModels,
  ModelListResponse,
  testTranslation,
  updateConfig,
} from '../api'
import { DirectoryPicker } from '../components/DirectoryPicker'

type GroupName = 'file' | 'processing' | 'whisper' | 'translation' | 'subtitle' | 'mux' | 'logging'

function TagEditor({
  label,
  values,
  placeholder,
  onAdd,
  onRemove,
  disabled = false,
}: {
  label: string
  values: string[]
  placeholder: string
  onAdd: (value: string) => void
  onRemove: (value: string) => void
  disabled?: boolean
}) {
  const [draft, setDraft] = useState('')

  return (
    <div className="field-block">
      <span className="field-label">{label}</span>
      <div className={`tag-editor ${disabled ? 'disabled' : ''}`}>
        <div className="tag-list">
          {values.map((value) => (
            <button
              key={value}
              type="button"
              className="tag-chip"
              onClick={() => onRemove(value)}
              disabled={disabled}
            >
              {value}
            </button>
          ))}
        </div>
        <div className="tag-input-row">
          <input
            value={draft}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                const next = draft.trim()
                if (next) {
                  onAdd(next)
                  setDraft('')
                }
              }
            }}
          />
          <button
            type="button"
            disabled={disabled || !draft.trim()}
            onClick={() => {
              const next = draft.trim()
              if (next) {
                onAdd(next)
                setDraft('')
              }
            }}
          >
            添加
          </button>
        </div>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const [config, setConfig] = useState<AppConfig>(cloneConfig(defaultAppConfig))
  const [loadedConfig, setLoadedConfig] = useState<AppConfig>(cloneConfig(defaultAppConfig))
  const [models, setModels] = useState<ModelListResponse>({ items: [], current_model: '' })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const [nextConfig, nextModels] = await Promise.all([getConfig(), getModels()])
      setConfig(nextConfig)
      setLoadedConfig(nextConfig)
      setModels(nextModels)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '配置加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const setField = <T extends GroupName, K extends keyof AppConfig[T]>(group: T, key: K, value: AppConfig[T][K]) => {
    setConfig((current) => ({
      ...current,
      [group]: {
        ...current[group],
        [key]: value,
      },
    }))
  }

  const addFileExtension = (value: string) => {
    const list = [...config.file.allowed_extensions]
    if (!list.includes(value)) {
      setField('file', 'allowed_extensions', [...list, value])
    }
  }

  const removeFileExtension = (value: string) => {
    setField(
      'file',
      'allowed_extensions',
      config.file.allowed_extensions.filter((item) => item !== value),
    )
  }

  const addTargetLanguage = (value: string) => {
    const list = [...config.translation.target_languages]
    if (!list.includes(value)) {
      setField('translation', 'target_languages', [...list, value])
    }
  }

  const removeTargetLanguage = (value: string) => {
    setField(
      'translation',
      'target_languages',
      config.translation.target_languages.filter((item) => item !== value),
    )
  }

  const currentModel = useMemo(
    () => models.items.find((item) => item.current),
    [models.items],
  )

  const submit = async () => {
    setSaving(true)
    try {
      const updated = await updateConfig({
        file: config.file,
        processing: config.processing,
        whisper: config.whisper,
        translation: config.translation,
        subtitle: config.subtitle,
        mux: config.mux,
        logging: config.logging,
      })
      setConfig(updated)
      setLoadedConfig(updated)
      setMessage('设置已保存')
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '设置保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    const next = cloneConfig(defaultAppConfig)
    setConfig(next)
    setMessage('已恢复默认值，可继续保存生效')
    setError('')
  }

  const handleRestoreLoaded = () => {
    setConfig(cloneConfig(loadedConfig))
    setMessage('已恢复当前已保存配置')
    setError('')
  }

  const handleTestTranslation = async () => {
    setTesting(true)
    try {
      const result = await testTranslation({
        enabled: config.translation.enabled,
        api_base_url: config.translation.api_base_url,
        api_key: config.translation.api_key,
        model: config.translation.model,
        timeout_seconds: config.translation.timeout_seconds,
        target_language: config.translation.target_languages[0] || 'zh-CN',
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

  if (loading) {
    return <div className="card muted">配置加载中…</div>
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>设置</h1>
          <p>按业务语义管理扫描、识别、翻译、字幕输出与高级运行参数。</p>
        </div>
        <div className="inline-actions">
          <button onClick={handleRestoreLoaded}>恢复已保存</button>
          <button onClick={() => void load()}>重新加载</button>
        </div>
      </header>
      {message ? <div className="alert success">{message}</div> : null}
      {error ? <div className="alert error">{error}</div> : null}
      {config.meta?.restart_required ? <div className="alert warning">检测到系统级配置更新，需要重启 Scanner / Worker。</div> : null}

      <div className="settings-grid">
        <div className="card">
          <h2>文件扫描</h2>
          <div className="field-grid">
            <DirectoryPicker
              label="输入目录"
              value={config.file.input_dir}
              onChange={(value) => setField('file', 'input_dir', value)}
              placeholder="例如 /data"
            />
            <DirectoryPicker
              label="输出目录"
              value={config.file.output_dir}
              onChange={(value) => setField('file', 'output_dir', value)}
              placeholder="留空则输出到源文件目录"
            />
            <label>
              <span>扫描间隔（秒）</span>
              <input
                type="number"
                value={config.file.scan_interval_seconds}
                onChange={(event) => setField('file', 'scan_interval_seconds', Number(event.target.value))}
              />
            </label>
            <label>
              <span>最小文件（MB）</span>
              <input type="number" value={config.file.min_size_mb} onChange={(event) => setField('file', 'min_size_mb', Number(event.target.value))} />
            </label>
            <label>
              <span>最大文件（MB）</span>
              <input type="number" value={config.file.max_size_mb} onChange={(event) => setField('file', 'max_size_mb', Number(event.target.value))} />
            </label>
          </div>
          <TagEditor
            label="允许扩展名"
            values={config.file.allowed_extensions}
            placeholder="例如 .mp4"
            onAdd={addFileExtension}
            onRemove={removeFileExtension}
          />
        </div>

        <div className="card">
          <h2>语音识别</h2>
          <div className="field-grid">
            <div className="field-block">
              <span className="field-label">当前模型</span>
              <div className="model-summary">
                <strong>{config.whisper.model_name}</strong>
                <span className={`status-chip ${currentModel?.status || 'not_installed'}`}>{currentModel?.status || 'not_installed'}</span>
                <Link to="/models">前往模型管理</Link>
              </div>
            </div>
            <label>
              <span>采样率</span>
              <input type="number" value={config.whisper.sample_rate} onChange={(event) => setField('whisper', 'sample_rate', Number(event.target.value))} />
            </label>
            <label>
              <span>设备</span>
              <select value={config.whisper.device} onChange={(event) => setField('whisper', 'device', event.target.value)}>
                <option value="cpu">cpu</option>
              </select>
            </label>
            <label>
              <span>音频格式</span>
              <select value={config.whisper.audio_format} onChange={(event) => setField('whisper', 'audio_format', event.target.value)}>
                <option value="wav">wav</option>
                <option value="mp3">mp3</option>
              </select>
            </label>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>翻译</h2>
            <label className="switch-row">
              <span>启用翻译</span>
              <input
                type="checkbox"
                checked={config.translation.enabled}
                onChange={(event) => setField('translation', 'enabled', event.target.checked)}
              />
            </label>
          </div>
          <div className={`field-grid ${config.translation.enabled ? '' : 'disabled-section'}`}>
            <label>
              <span>API Base URL</span>
              <input
                disabled={!config.translation.enabled}
                value={config.translation.api_base_url}
                onChange={(event) => setField('translation', 'api_base_url', event.target.value)}
              />
            </label>
            <label>
              <span>API Key</span>
              <input
                disabled={!config.translation.enabled}
                type="password"
                value={config.translation.api_key}
                onChange={(event) => setField('translation', 'api_key', event.target.value)}
              />
            </label>
            <label>
              <span>模型</span>
              <input
                disabled={!config.translation.enabled}
                value={config.translation.model}
                onChange={(event) => setField('translation', 'model', event.target.value)}
              />
            </label>
            <label>
              <span>超时（秒）</span>
              <input
                disabled={!config.translation.enabled}
                type="number"
                value={config.translation.timeout_seconds}
                onChange={(event) => setField('translation', 'timeout_seconds', Number(event.target.value))}
              />
            </label>
            <label>
              <span>最大重试</span>
              <input
                disabled={!config.translation.enabled}
                type="number"
                value={config.translation.max_retries}
                onChange={(event) => setField('translation', 'max_retries', Number(event.target.value))}
              />
            </label>
          </div>
          <TagEditor
            label="目标语言"
            values={config.translation.target_languages}
            placeholder="例如 zh-CN"
            disabled={!config.translation.enabled}
            onAdd={addTargetLanguage}
            onRemove={removeTargetLanguage}
          />
          <button disabled={testing} onClick={() => void handleTestTranslation()}>
            {testing ? '测试中…' : '测试连接'}
          </button>
        </div>

        <div className="card">
          <h2>字幕输出</h2>
          <div className="field-grid">
            <label className="switch-row">
              <span>双语字幕</span>
              <input type="checkbox" checked={config.subtitle.bilingual} onChange={(event) => setField('subtitle', 'bilingual', event.target.checked)} />
            </label>
            <label>
              <span>双语模式</span>
              <select value={config.subtitle.bilingual_mode} onChange={(event) => setField('subtitle', 'bilingual_mode', event.target.value)}>
                <option value="merge">merge</option>
                <option value="separate">separate</option>
              </select>
            </label>
            <label>
              <span>源语言</span>
              <select value={config.subtitle.source_language} onChange={(event) => setField('subtitle', 'source_language', event.target.value)}>
                <option value="auto">auto</option>
                <option value="en">en</option>
                <option value="zh">zh</option>
                <option value="ja">ja</option>
              </select>
            </label>
            <label>
              <span>文件名模板</span>
              <input value={config.subtitle.filename_template} onChange={(event) => setField('subtitle', 'filename_template', event.target.value)} />
            </label>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>字幕压片</h2>
            <label className="switch-row">
              <span>启用压片</span>
              <input type="checkbox" checked={config.mux.enabled} onChange={(event) => setField('mux', 'enabled', event.target.checked)} />
            </label>
          </div>
          <div className={`field-grid ${config.mux.enabled ? '' : 'disabled-section'}`}>
            <DirectoryPicker
              label="压片输出目录"
              value={config.mux.output_dir}
              onChange={(value) => setField('mux', 'output_dir', value)}
              placeholder="留空则输出到源文件目录"
              disabled={!config.mux.enabled}
            />
            <label>
              <span>压片文件名模板</span>
              <input
                disabled={!config.mux.enabled}
                value={config.mux.filename_template}
                onChange={(event) => setField('mux', 'filename_template', event.target.value)}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="card">
        <button className="text-button" onClick={() => setShowAdvanced((current) => !current)}>
          {showAdvanced ? '收起高级设置' : '展开高级设置'}
        </button>
        {showAdvanced ? (
          <div className="field-grid advanced-grid">
            <label>
              <span>工作目录</span>
              <input value={config.processing.work_dir} onChange={(event) => setField('processing', 'work_dir', event.target.value)} />
            </label>
            <label>
              <span>任务最大重试</span>
              <input type="number" value={config.processing.max_retries} onChange={(event) => setField('processing', 'max_retries', Number(event.target.value))} />
            </label>
            <label>
              <span>自动重试模式</span>
              <select value={config.processing.retry_mode} onChange={(event) => setField('processing', 'retry_mode', event.target.value as AppConfig['processing']['retry_mode'])}>
                <option value="restart">restart</option>
                <option value="resume">resume</option>
              </select>
            </label>
            <label>
              <span>轮询间隔（秒）</span>
              <input
                type="number"
                value={config.processing.poll_interval_seconds}
                onChange={(event) => setField('processing', 'poll_interval_seconds', Number(event.target.value))}
              />
            </label>
            <label className="switch-row">
              <span>保留中间产物</span>
              <input
                type="checkbox"
                checked={config.processing.keep_intermediates}
                onChange={(event) => setField('processing', 'keep_intermediates', event.target.checked)}
              />
            </label>
            <label>
              <span>日志级别</span>
              <select value={config.logging.level} onChange={(event) => setField('logging', 'level', event.target.value)}>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </label>
            <label>
              <span>日志分页大小</span>
              <input type="number" value={config.logging.page_size} onChange={(event) => setField('logging', 'page_size', Number(event.target.value))} />
            </label>
            <label>
              <span>对齐模型</span>
              <input value={config.whisper.align_model} onChange={(event) => setField('whisper', 'align_model', event.target.value)} />
            </label>
          </div>
        ) : null}
      </div>

      <div className="page-actions">
        <button className="ghost-button" onClick={handleReset}>
          重置默认
        </button>
        <button disabled={saving} onClick={() => void submit()}>
          {saving ? '保存中…' : '保存设置'}
        </button>
      </div>
    </section>
  )
}
