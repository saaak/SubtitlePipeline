import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AppConfig,
  AlignMethod,
  bilingualModeOptions,
  cloneConfig,
  defaultAppConfig,
  getConfig,
  getModels,
  ModelListResponse,
  retryModeOptions,
  sourceLanguageOptions,
  testTranslation,
  translationContentTypeOptions,
  updateConfig,
} from '../api'
import { DirectoryPicker } from '../components/DirectoryPicker'

type GroupName = 'file' | 'processing' | 'whisper' | 'translation' | 'subtitle' | 'mux' | 'logging'

const alignMethodOptions = [
  { value: 'auto', label: '自动（推荐）' },
  { value: 'whisperx', label: 'WhisperX 强制对齐' },
  { value: 'simple', label: '简单分段' },
  { value: 'none', label: '禁用' },
]

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

  const usingCustomPrompt = config.translation.custom_prompt.trim().length > 0

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
        content_type: config.translation.content_type,
        custom_prompt: config.translation.custom_prompt,
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
            <div className="field-block">
              <label className="switch-row">
                <span>输出到源文件目录</span>
                <input
                  type="checkbox"
                  checked={config.file.output_to_source_dir}
                  onChange={(event) => setField('file', 'output_to_source_dir', event.target.checked)}
                />
              </label>
              <span className="muted">
                {config.file.output_to_source_dir
                  ? '开启后，字幕和压片文件会写回源视频所在目录。'
                  : '关闭后，字幕和压片文件会统一输出到 /output 目录。'}
              </span>
            </div>
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
                <strong>{currentModel?.display_name || config.whisper.model_name}</strong>
                <span className={`status-chip ${currentModel?.status || 'not_installed'}`}>{currentModel?.status || 'not_installed'}</span>
                <Link to="/models">前往模型管理</Link>
              </div>
              <span className="muted">{currentModel?.description || '可在模型管理页下载并切换模型。'}</span>
            </div>
            <label>
              <span>Beam Size</span>
              <input type="number" value={config.whisper.beam_size} onChange={(event) => setField('whisper', 'beam_size', Number(event.target.value))} />
            </label>
            <label className="switch-row">
              <span>VAD 过滤</span>
              <input
                type="checkbox"
                checked={config.whisper.vad_filter}
                onChange={(event) => setField('whisper', 'vad_filter', event.target.checked)}
              />
            </label>
            <label>
              <span>VAD 阈值</span>
              <input
                type="number"
                step="0.1"
                value={config.whisper.vad_threshold}
                onChange={(event) => setField('whisper', 'vad_threshold', Number(event.target.value))}
              />
            </label>
            <label>
              <span>对齐方法</span>
              <select value={config.whisper.align_method} onChange={(event) => setField('whisper', 'align_method', event.target.value as AlignMethod)}>
                {alignMethodOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>采样率</span>
              <input type="number" value={config.whisper.sample_rate} onChange={(event) => setField('whisper', 'sample_rate', Number(event.target.value))} />
            </label>
            <label>
              <span>设备</span>
              <input type="text" value={config.whisper.device} readOnly disabled style={{ opacity: 0.7, cursor: 'not-allowed' }} />
            </label>
            <label>
              <span>音频格式</span>
              <select value={config.whisper.audio_format} onChange={(event) => setField('whisper', 'audio_format', event.target.value)}>
                <option value="wav">wav</option>
                <option value="mp3">mp3</option>
              </select>
            </label>
          </div>
          <details className="advanced-section">
            <summary>高级选项</summary>
            <div className="field-grid">
              <label>
                <span>WhisperX 对齐扩展时长</span>
                <input
                  type="number"
                  value={config.whisper.advanced.whisperx_align_extend}
                  onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, whisperx_align_extend: Number(event.target.value) })}
                />
              </label>
              <label className="switch-row">
                <span>Faster-Whisper 词级时间戳</span>
                <input
                  type="checkbox"
                  checked={config.whisper.advanced.faster_whisper_word_timestamps}
                  onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, faster_whisper_word_timestamps: event.target.checked })}
                />
              </label>
              <label className="switch-row">
                <span>Anime-Whisper 对话增强</span>
                <input
                  type="checkbox"
                  checked={config.whisper.advanced.anime_whisper_enhance_dialogue}
                  onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, anime_whisper_enhance_dialogue: event.target.checked })}
                />
              </label>
              <label>
                <span>Qwen Temperature</span>
                <input
                  type="number"
                  step="0.1"
                  value={config.whisper.advanced.qwen_temperature}
                  onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, qwen_temperature: Number(event.target.value) })}
                />
              </label>
            </div>
          </details>
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
            <label>
              <span>内容类型</span>
              <select
                disabled={!config.translation.enabled || usingCustomPrompt}
                value={config.translation.content_type}
                onChange={(event) => setField('translation', 'content_type', event.target.value as AppConfig['translation']['content_type'])}
              >
                {translationContentTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field-block">
            <span className="field-label">自定义 Prompt</span>
            <textarea
              disabled={!config.translation.enabled}
              rows={5}
              value={config.translation.custom_prompt}
              placeholder="留空使用预设，填写后将替换预设 prompt"
              onChange={(event) => setField('translation', 'custom_prompt', event.target.value)}
            />
            <span className="muted">{usingCustomPrompt ? '当前已启用自定义 prompt，内容类型预设已禁用。' : '留空时使用上方内容类型预设。'}</span>
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
              <select
                value={config.subtitle.bilingual_mode}
                disabled={!config.subtitle.bilingual}
                onChange={(event) =>
                  setField('subtitle', 'bilingual_mode', event.target.value as AppConfig['subtitle']['bilingual_mode'])
                }
              >
                {bilingualModeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>源语言</span>
              <select
                value={config.subtitle.source_language}
                onChange={(event) =>
                  setField('subtitle', 'source_language', event.target.value as AppConfig['subtitle']['source_language'])
                }
              >
                {sourceLanguageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="muted">选错源语言可能影响识别准确度，无法确定时建议保持自动检测。</span>
            </label>
            <div className="field-block">
              <span className="field-label">文件名模板</span>
              <input value={config.subtitle.filename_template} onChange={(event) => setField('subtitle', 'filename_template', event.target.value)} />
              <span className="muted">{'可用占位符：{stem} = 源文件名（不含扩展名），{lang} = 语言代码（为你在翻译配置中填写的语言）或 bilingual / source'}</span>
            </div>
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
            <div className="field-block">
              <span className="field-label">输出位置</span>
              <span className="muted">
                {config.file.output_to_source_dir
                  ? '当前跟随源文件目录输出。'
                  : '当前统一输出到 /output 目录。'}
              </span>
            </div>
            <div className="field-block">
              <span className="field-label">压片文件名模板</span>
              <input
                disabled={!config.mux.enabled}
                value={config.mux.filename_template}
                onChange={(event) => setField('mux', 'filename_template', event.target.value)}
              />
              <span className="muted">{'可用占位符：{stem} = 源文件名（不含扩展名）'}</span>
            </div>
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
              <select
                value={config.processing.retry_mode}
                onChange={(event) => setField('processing', 'retry_mode', event.target.value as AppConfig['processing']['retry_mode'])}
              >
                {retryModeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
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
