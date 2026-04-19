import { ReactNode, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AppConfig,
  AlignProvider,
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

const alignProviderOptions: Array<{ value: AlignProvider; label: string }> = [
  { value: 'auto', label: '自动（推荐）' },
  { value: 'whisperx', label: 'WhisperX 强制对齐' },
  { value: 'qwen-forced', label: 'Qwen 强制对齐' },
  { value: 'none', label: '禁用' },
]

const initialExpandedState: Record<string, boolean> = {
  file: false,
  asr: false,
  align: false,
  translation: false,
  subtitle: false,
  mux: false,
  system: false,
}

type StepTone = 'success' | 'warning' | 'neutral' | 'muted'

function TagEditor({
  label,
  values,
  placeholder,
  hint,
  onAdd,
  onRemove,
  disabled = false,
}: {
  label: string
  values: string[]
  placeholder: string
  hint?: ReactNode
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
      {hint ? <span className="muted">{hint}</span> : null}
    </div>
  )
}

function StepCard({
  index,
  title,
  description,
  statusLabel,
  tone,
  pills,
  expanded,
  onToggle,
  basicContent,
  advancedContent,
  headerActions,
}: {
  index: string
  title: string
  description: string
  statusLabel: string
  tone: StepTone
  pills: string[]
  expanded: boolean
  onToggle: () => void
  basicContent: ReactNode
  advancedContent?: ReactNode
  headerActions?: ReactNode
}) {
  const expandable = Boolean(advancedContent)
  const isExpanded = expandable && expanded
  return (
    <article className={`card pipeline-step-card tone-${tone} ${isExpanded ? 'is-expanded' : ''}`}>
      <div className="pipeline-step-header">
        <div className="pipeline-step-toggle">
          <span className="pipeline-step-rail" aria-hidden="true">
            <span className="pipeline-step-index">{index}</span>
            <span className="pipeline-step-line" />
          </span>
          <span className="pipeline-step-content">
            <span className="pipeline-step-topline">
              <strong>{title}</strong>
              <span className={`step-badge tone-${tone}`}>{statusLabel}</span>
            </span>
            <span className="pipeline-step-description">{description}</span>
            <span className="pipeline-step-pills" aria-hidden="true">
              {pills.map((pill) => (
                <span key={pill} className="summary-pill">
                  {pill}
                </span>
              ))}
            </span>
          </span>
        </div>
        {headerActions ? <div className="pipeline-step-actions">{headerActions}</div> : null}
      </div>
      <div className="pipeline-step-body">
        <div className="pipeline-step-basic">{basicContent}</div>
        {expandable ? (
          <button type="button" className={`pipeline-step-disclosure ${isExpanded ? 'is-open' : ''}`} onClick={onToggle}>
            <span className="pipeline-step-disclosure-label">{isExpanded ? '收起高级设置' : '高级设置'}</span>
          </button>
        ) : null}
        {isExpanded && advancedContent ? (
          <div className="pipeline-step-advanced">
            <div className="pipeline-step-advanced-header">
              <span className="pipeline-step-advanced-title">高级配置</span>
              <span className="muted">用于细化调优与运行策略，通常不需要频繁修改。</span>
            </div>
            {advancedContent}
          </div>
        ) : null}
      </div>
    </article>
  )
}

function countChangedSections(current: AppConfig, saved: AppConfig): number {
  const groups: Array<keyof AppConfig> = ['file', 'whisper', 'translation', 'subtitle', 'mux', 'processing', 'logging']
  return groups.reduce((count, group) => {
    return JSON.stringify(current[group]) === JSON.stringify(saved[group]) ? count : count + 1
  }, 0)
}

function getTranslationStatus(config: AppConfig): { tone: StepTone; label: string } {
  if (!config.translation.enabled) {
    return { tone: 'muted', label: '已关闭' }
  }
  const required = [
    config.translation.api_base_url.trim(),
    config.translation.api_key.trim(),
    config.translation.model.trim(),
    config.translation.target_languages.length > 0 ? 'ok' : '',
  ]
  return required.every(Boolean)
    ? { tone: 'success', label: '已就绪' }
    : { tone: 'warning', label: '待补充' }
}

function getAlignStatus(
  alignProvider: AlignProvider,
  hintLevel: 'success' | 'warning' | 'muted',
): { tone: StepTone; label: string } {
  if (alignProvider === 'none') {
    return { tone: 'muted', label: '已禁用' }
  }
  if (hintLevel === 'warning') {
    return { tone: 'warning', label: '需注意' }
  }
  if (hintLevel === 'success') {
    return { tone: 'success', label: '已就绪' }
  }
  return { tone: 'neutral', label: '自动模式' }
}

export function SettingsPage() {
  const [config, setConfig] = useState<AppConfig>(cloneConfig(defaultAppConfig))
  const [loadedConfig, setLoadedConfig] = useState<AppConfig>(cloneConfig(defaultAppConfig))
  const [models, setModels] = useState<ModelListResponse>({ items: [], current_model: '' })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>(initialExpandedState)
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

  const installedAsrModels = useMemo(
    () => models.items.filter((item) => item.model_type === 'asr' && item.status === 'installed'),
    [models.items],
  )
  const selectedAsrModel = useMemo(
    () => models.items.find((item) => item.name === config.whisper.model_name) || null,
    [config.whisper.model_name, models.items],
  )
  const qwenAligner = useMemo(
    () => models.items.find((item) => item.name === 'qwen3-forced-aligner'),
    [models.items],
  )

  const usingCustomPrompt = config.translation.custom_prompt.trim().length > 0
  const currentProvider = selectedAsrModel?.provider ?? config.whisper.provider
  const qwenAlignerInstalled = qwenAligner?.status === 'installed'
  const changedSectionCount = useMemo(() => countChangedSections(config, loadedConfig), [config, loadedConfig])
  const sourceLanguageLabel = useMemo(
    () => sourceLanguageOptions.find((option) => option.value === config.subtitle.source_language)?.label || config.subtitle.source_language,
    [config.subtitle.source_language],
  )

  const toggleExpanded = (key: string) => {
    setExpanded((current) => ({ ...current, [key]: !current[key] }))
  }

  const fileDescription = useMemo(() => {
    return config.file.output_to_source_dir ? '扫描媒体目录并直接输出回源文件位置。' : '扫描媒体目录并统一输出到 /output。'
  }, [config.file.output_to_source_dir])

  const asrDescription = useMemo(() => '选择识别模型、源语言与常用识别参数。', [])

  const alignHint = useMemo(() => {
    if (config.whisper.align_provider === 'auto' && currentProvider === 'whisperx') {
      return { level: 'success' as const, text: '当前将使用 WhisperX 内置对齐' }
    }
    if (config.whisper.align_provider === 'auto' && currentProvider !== 'whisperx' && !qwenAlignerInstalled) {
      return { level: 'warning' as const, text: '建议下载 Qwen3 强制对齐模型以提升精度' }
    }
    if (config.whisper.align_provider === 'qwen-forced' && qwenAlignerInstalled) {
      return { level: 'success' as const, text: 'Qwen3-ForcedAligner 已就绪' }
    }
    if (config.whisper.align_provider === 'qwen-forced' && !qwenAlignerInstalled) {
      return { level: 'warning' as const, text: '模型未下载，任务将报错停止' }
    }
    if (config.whisper.align_provider === 'none') {
      return { level: 'muted' as const, text: '将直接使用 ASR 内置时间戳' }
    }
    return { level: 'muted' as const, text: '自动模式会根据当前 ASR Provider 和本地模型状态选择对齐器' }
  }, [config.whisper.align_provider, currentProvider, qwenAlignerInstalled])

  const translationStatus = useMemo(() => getTranslationStatus(config), [config])
  const alignStatus = useMemo(() => getAlignStatus(config.whisper.align_provider, alignHint.level), [alignHint.level, config.whisper.align_provider])
  const fileStatus = useMemo<{ tone: StepTone; label: string }>(
    () => (config.file.input_dir.trim() && config.file.allowed_extensions.length > 0 ? { tone: 'success', label: '已配置' } : { tone: 'warning', label: '待补充' }),
    [config.file.allowed_extensions.length, config.file.input_dir],
  )
  const asrStatus = useMemo<{ tone: StepTone; label: string }>(
    () => (selectedAsrModel?.status === 'installed' ? { tone: 'success', label: '已就绪' } : { tone: 'warning', label: '待安装' }),
    [selectedAsrModel?.status],
  )
  const subtitleStatus = useMemo<{ tone: StepTone; label: string }>(
    () => ({ tone: 'success', label: config.subtitle.bilingual ? '双语输出' : '单语输出' }),
    [config.subtitle.bilingual],
  )
  const muxStatus = useMemo<{ tone: StepTone; label: string }>(
    () => (config.mux.enabled ? { tone: 'neutral', label: '已启用' } : { tone: 'muted', label: '可选步骤' }),
    [config.mux.enabled],
  )
  const systemStatus = useMemo<{ tone: StepTone; label: string }>(
    () => ({ tone: 'neutral', label: '高级参数' }),
    [],
  )

  const overviewStats = useMemo(
    () => [
      { label: '流水线步骤', value: '7', hint: '扫描到系统参数' },
      { label: '未保存变更', value: String(changedSectionCount), hint: changedSectionCount > 0 ? '建议保存后生效' : '当前与已保存一致' },
      { label: '已选模型', value: selectedAsrModel?.display_name || config.whisper.model_name, hint: currentProvider },
      { label: '对齐状态', value: alignStatus.label, hint: alignHint.text },
    ],
    [alignHint.text, alignStatus.label, changedSectionCount, config.whisper.model_name, currentProvider, selectedAsrModel?.display_name],
  )

  const handleSelectAsrModel = (modelName: string) => {
    const nextModel = models.items.find((item) => item.name === modelName && item.model_type === 'asr')
    if (!nextModel) {
      return
    }
    setConfig((current) => ({
      ...current,
      whisper: {
        ...current.whisper,
        model_name: nextModel.name,
        provider: nextModel.provider === 'qwen-forced' ? current.whisper.provider : nextModel.provider,
      },
    }))
  }

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
        target_language: config.translation.target_languages[0] || 'zh',
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
    return <div className="card muted settings-loading">配置加载中…</div>
  }

  return (
    <section className="settings-page">
      <header className="page-header settings-header">
        <div className="settings-header-main">
          <h1>设置</h1>
          <p>管理扫描目录、识别模型、时间轴对齐、翻译和输出设置。</p>
        </div>
        <div className="inline-actions settings-top-actions">
          <button className="ghost-button" onClick={handleRestoreLoaded}>恢复已保存</button>
          <button className="ghost-button" onClick={() => void load()}>重新加载</button>
        </div>
      </header>
      {message ? <div className="alert success">{message}</div> : null}
      {error ? <div className="alert error">{error}</div> : null}
      {config.meta?.restart_required ? <div className="alert warning">检测到系统级配置更新，需要重启 Scanner / Worker。</div> : null}

      <section className="settings-overview card">
        <div className="settings-overview-main">
          <div className="settings-overview-copy">
            <div className="settings-overview-badges">
              <span className="summary-pill emphasis">配置概览</span>
              <span className={`step-badge ${changedSectionCount > 0 ? 'tone-warning' : 'tone-success'}`}>
                {changedSectionCount > 0 ? `未保存 ${changedSectionCount} 项` : '已同步'}
              </span>
            </div>
            <h2>当前配置概览</h2>
            <p>汇总当前模型、对齐状态和未保存改动，便于保存前快速检查。</p>
          </div>
          <div className="settings-overview-stats">
            {overviewStats.map((stat) => (
              <div key={stat.label} className="overview-stat">
                <span className="overview-stat-label">{stat.label}</span>
                <strong className="overview-stat-value">{stat.value}</strong>
                <span className="overview-stat-hint">{stat.hint}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="pipeline-steps">
        <StepCard
          index="01"
          title="文件扫描"
          description={fileDescription}
          statusLabel={fileStatus.label}
          tone={fileStatus.tone}
          pills={[config.file.input_dir, ...config.file.allowed_extensions.slice(0, 3), config.file.output_to_source_dir ? '输出回源' : '输出 /output']}
          expanded={expanded.file}
          onToggle={() => toggleExpanded('file')}
          basicContent={(
            <div className="field-grid">
              <DirectoryPicker
                label="输入目录"
                value={config.file.input_dir}
                onChange={(value) => setField('file', 'input_dir', value)}
                placeholder="例如 /data"
              />
              <TagEditor
                label="允许文件类型"
                values={config.file.allowed_extensions}
                placeholder="例如 .mp4"
                onAdd={addFileExtension}
                onRemove={removeFileExtension}
              />
              <div className="field-block">
                <label className="switch-row">
                  <span>输出到源文件目录</span>
                  <input type="checkbox" checked={config.file.output_to_source_dir} onChange={(event) => setField('file', 'output_to_source_dir', event.target.checked)} />
                </label>
                <span className="muted">
                  {config.file.output_to_source_dir ? '字幕和压片文件会写回源视频所在目录。' : '字幕和压片文件会统一输出到 /output 目录。'}
                </span>
              </div>
            </div>
          )}
          advancedContent={(
            <section className="advanced-section">
              <div className="field-grid">
                <label>
                  <span>扫描间隔（秒）</span>
                  <input type="number" value={config.file.scan_interval_seconds} onChange={(event) => setField('file', 'scan_interval_seconds', Number(event.target.value))} />
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
            </section>
          )}
        />

        <StepCard
          index="02"
          title="语音识别"
          description={asrDescription}
          statusLabel={asrStatus.label}
          tone={asrStatus.tone}
          pills={[selectedAsrModel?.display_name || config.whisper.model_name, `语言 ${sourceLanguageLabel}`, currentProvider]}
          expanded={expanded.asr}
          onToggle={() => toggleExpanded('asr')}
          basicContent={(
            <div className="field-grid">
              <label>
                <span>识别模型</span>
                <select value={config.whisper.model_name} onChange={(event) => handleSelectAsrModel(event.target.value)} disabled={installedAsrModels.length === 0}>
                  {installedAsrModels.length === 0 ? <option value={config.whisper.model_name}>暂无已安装模型</option> : null}
                  {installedAsrModels.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.display_name}
                    </option>
                  ))}
                </select>
                <span className="muted">{selectedAsrModel?.description || '可在模型管理页下载后在这里直接切换。'}</span>
              </label>
              <label>
                <span>视频源语言</span>
                <select value={config.subtitle.source_language} onChange={(event) => setField('subtitle', 'source_language', event.target.value as AppConfig['subtitle']['source_language'])}>
                  {sourceLanguageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          advancedContent={(
            <section className="advanced-section">
              <div className="field-grid">
                <label>
                  <span>Beam Size</span>
                  <input type="number" value={config.whisper.beam_size} onChange={(event) => setField('whisper', 'beam_size', Number(event.target.value))} />
                </label>
                <label className="switch-row">
                  <span>VAD 过滤</span>
                  <input type="checkbox" checked={config.whisper.vad_filter} onChange={(event) => setField('whisper', 'vad_filter', event.target.checked)} />
                </label>
                <label>
                  <span>VAD 阈值</span>
                  <input type="number" step="0.1" value={config.whisper.vad_threshold} onChange={(event) => setField('whisper', 'vad_threshold', Number(event.target.value))} />
                </label>
                <label>
                  <span>音频格式</span>
                  <select value={config.whisper.audio_format} onChange={(event) => setField('whisper', 'audio_format', event.target.value)}>
                    <option value="wav">wav</option>
                    <option value="mp3">mp3</option>
                  </select>
                </label>
                <label>
                  <span>采样率</span>
                  <input type="number" value={config.whisper.sample_rate} onChange={(event) => setField('whisper', 'sample_rate', Number(event.target.value))} />
                </label>
                <label>
                  <span>设备</span>
                  <input type="text" value={config.whisper.device} readOnly disabled />
                </label>
                <label>
                  <span>WhisperX 对齐扩展时长</span>
                  <input type="number" value={config.whisper.advanced.whisperx_align_extend} onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, whisperx_align_extend: Number(event.target.value) })} />
                </label>
                <label className="switch-row">
                  <span>Faster-Whisper 词级时间戳</span>
                  <input type="checkbox" checked={config.whisper.advanced.faster_whisper_word_timestamps} onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, faster_whisper_word_timestamps: event.target.checked })} />
                </label>
                <label className="switch-row">
                  <span>Anime-Whisper 对话增强</span>
                  <input type="checkbox" checked={config.whisper.advanced.anime_whisper_enhance_dialogue} onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, anime_whisper_enhance_dialogue: event.target.checked })} />
                </label>
                <label>
                  <span>Qwen Temperature</span>
                  <input type="number" step="0.1" value={config.whisper.advanced.qwen_temperature} onChange={(event) => setField('whisper', 'advanced', { ...config.whisper.advanced, qwen_temperature: Number(event.target.value) })} />
                </label>
                <div className="field-block pipeline-wide">
                  <span className="field-label">模型管理</span>
                  <div className="model-summary">
                    <span className={`status-chip ${selectedAsrModel?.status || 'not_installed'}`}>{selectedAsrModel?.status || 'not_installed'}</span>
                    <Link to="/models">前往模型管理页下载或删除模型</Link>
                  </div>
                </div>
              </div>
            </section>
          )}
        />

        <StepCard
          index="03"
          title="时间轴对齐"
          description="根据当前 ASR Provider 和对齐模型状态决定是否精修时间戳。"
          statusLabel={alignStatus.label}
          tone={alignStatus.tone}
          pills={[config.whisper.align_provider, `当前 ASR ${currentProvider}`, qwenAlignerInstalled ? 'Qwen 对齐已下载' : 'Qwen 对齐未下载']}
          expanded={expanded.align}
          onToggle={() => toggleExpanded('align')}
          basicContent={(
            <div className="field-grid">
              <label>
                <span>对齐方式</span>
                <select value={config.whisper.align_provider} onChange={(event) => setField('whisper', 'align_provider', event.target.value as AlignProvider)}>
                  {alignProviderOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className={`alert ${alignHint.level === 'warning' ? 'warning' : alignHint.level === 'success' ? 'success' : 'card-muted'}`}>
                {alignHint.text}
                {(config.whisper.align_provider === 'qwen-forced' || alignHint.level === 'warning') ? (
                  <span className="inline-link">
                    {' '}
                    <Link to="/models">前往下载</Link>
                  </span>
                ) : null}
              </div>
              <div className="field-block">
                <span className="field-label">对齐说明</span>
                <span className="muted">手动选择 WhisperX 时，也可以对非 WhisperX 的识别结果做二次时间轴对齐；`auto` 模式不会自动这样做。</span>
              </div>
            </div>
          )}
        />

        <StepCard
          index="04"
          title="翻译"
          description="配置翻译服务、目标语言与内容风格。关闭后会保留参数但跳过翻译阶段。"
          statusLabel={translationStatus.label}
          tone={translationStatus.tone}
          pills={[
            config.translation.enabled ? '已启用' : '已关闭',
            config.translation.target_languages.join(', ') || '未设置目标语言',
            config.translation.model || '未设置模型',
          ]}
          expanded={expanded.translation}
          onToggle={() => toggleExpanded('translation')}
          headerActions={(
            <label className="switch-row">
              <span>启用</span>
              <input type="checkbox" checked={config.translation.enabled} onChange={(event) => setField('translation', 'enabled', event.target.checked)} />
            </label>
          )}
          basicContent={(
            <div className={config.translation.enabled ? '' : 'disabled-section'}>
              <div className="field-grid">
                <label>
                  <span>API Base URL</span>
                  <input disabled={!config.translation.enabled} value={config.translation.api_base_url} onChange={(event) => setField('translation', 'api_base_url', event.target.value)} />
                </label>
                <label>
                  <span>API Key</span>
                  <input disabled={!config.translation.enabled} type="password" value={config.translation.api_key} onChange={(event) => setField('translation', 'api_key', event.target.value)} />
                </label>
                <label>
                  <span>模型</span>
                  <input disabled={!config.translation.enabled} value={config.translation.model} onChange={(event) => setField('translation', 'model', event.target.value)} />
                </label>
                <TagEditor
                  label="目标语言代码"
                  values={config.translation.target_languages}
                  placeholder="例如 zh、en、ja"
                  hint="建议优先填写媒体库识别更友好的语言代码，例如 zh、en、ja；如确有需要也可手动填写 zh-CN 这类地区代码。"
                  disabled={!config.translation.enabled}
                  onAdd={addTargetLanguage}
                  onRemove={removeTargetLanguage}
                />
              </div>
              <button disabled={testing || !config.translation.enabled} onClick={() => void handleTestTranslation()}>
                {testing ? '测试中…' : '测试连接'}
              </button>
            </div>
          )}
          advancedContent={(
            <div className={config.translation.enabled ? '' : 'disabled-section'}>
              <section className="advanced-section">
                <div className="field-grid">
                  <label>
                    <span>超时（秒）</span>
                    <input disabled={!config.translation.enabled} type="number" value={config.translation.timeout_seconds} onChange={(event) => setField('translation', 'timeout_seconds', Number(event.target.value))} />
                  </label>
                  <label>
                    <span>最大重试</span>
                    <input disabled={!config.translation.enabled} type="number" value={config.translation.max_retries} onChange={(event) => setField('translation', 'max_retries', Number(event.target.value))} />
                  </label>
                  <label>
                    <span>内容类型</span>
                    <select disabled={!config.translation.enabled || usingCustomPrompt} value={config.translation.content_type} onChange={(event) => setField('translation', 'content_type', event.target.value as AppConfig['translation']['content_type'])}>
                      {translationContentTypeOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="field-block pipeline-wide">
                    <span className="field-label">自定义 Prompt</span>
                    <textarea disabled={!config.translation.enabled} rows={5} value={config.translation.custom_prompt} placeholder="留空使用预设，填写后将替换预设 prompt" onChange={(event) => setField('translation', 'custom_prompt', event.target.value)} />
                    <span className="muted">{usingCustomPrompt ? '当前已启用自定义 prompt，内容类型预设已禁用。' : '留空时使用上方内容类型预设。'}</span>
                  </div>
                </div>
              </section>
            </div>
          )}
        />

        <StepCard
          index="05"
          title="字幕输出"
          description="定义双语策略与输出文件命名模板。"
          statusLabel={subtitleStatus.label}
          tone={subtitleStatus.tone}
          pills={[config.subtitle.bilingual ? '双语' : '单语', config.subtitle.bilingual_mode, config.subtitle.filename_template]}
          expanded={expanded.subtitle}
          onToggle={() => toggleExpanded('subtitle')}
          basicContent={(
            <div className="field-grid">
              <label className="switch-row">
                <span>双语字幕</span>
                <input type="checkbox" checked={config.subtitle.bilingual} onChange={(event) => setField('subtitle', 'bilingual', event.target.checked)} />
              </label>
              <label>
                <span>双语模式</span>
                <select value={config.subtitle.bilingual_mode} disabled={!config.subtitle.bilingual} onChange={(event) => setField('subtitle', 'bilingual_mode', event.target.value as AppConfig['subtitle']['bilingual_mode'])}>
                  {bilingualModeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          advancedContent={(
            <section className="advanced-section">
              <div className="field-grid">
                <div className="field-block pipeline-wide">
                  <span className="field-label">文件名模板</span>
                  <input value={config.subtitle.filename_template} onChange={(event) => setField('subtitle', 'filename_template', event.target.value)} />
                  <span className="muted">{'可用占位符：{stem} = 源文件名（不含扩展名），{lang} = 语言代码或 bilingual / source'}</span>
                </div>
              </div>
            </section>
          )}
        />

        <StepCard
          index="06"
          title="字幕压片"
          description="是否将字幕封装回视频容器。通常作为可选收尾步骤。"
          statusLabel={muxStatus.label}
          tone={muxStatus.tone}
          pills={[config.mux.enabled ? '已启用' : '已关闭', config.file.output_to_source_dir ? '跟随源目录' : '统一输出', config.mux.filename_template]}
          expanded={expanded.mux}
          onToggle={() => toggleExpanded('mux')}
          headerActions={(
            <label className="switch-row">
              <span>启用</span>
              <input type="checkbox" checked={config.mux.enabled} onChange={(event) => setField('mux', 'enabled', event.target.checked)} />
            </label>
          )}
          basicContent={(
            <div className={config.mux.enabled ? '' : 'disabled-section'}>
              <div className="field-grid">
                <div className="field-block">
                  <span className="field-label">输出位置</span>
                  <span className="muted">{config.file.output_to_source_dir ? '当前跟随源文件目录输出。' : '当前统一输出到 /output 目录。'}</span>
                </div>
              </div>
            </div>
          )}
          advancedContent={(
            <div className={config.mux.enabled ? '' : 'disabled-section'}>
              <section className="advanced-section">
                <div className="field-grid">
                  <div className="field-block pipeline-wide">
                    <span className="field-label">压片文件名模板</span>
                    <input disabled={!config.mux.enabled} value={config.mux.filename_template} onChange={(event) => setField('mux', 'filename_template', event.target.value)} />
                    <span className="muted">{'可用占位符：{stem} = 源文件名（不含扩展名）'}</span>
                  </div>
                </div>
              </section>
            </div>
          )}
        />

        <StepCard
          index="07"
          title="系统参数"
          description="放置工作目录、自动重试与轮询间隔等运行时高级设置。"
          statusLabel={systemStatus.label}
          tone={systemStatus.tone}
          pills={[config.processing.work_dir, config.processing.retry_mode, `轮询 ${config.processing.poll_interval_seconds}s`, config.logging.level]}
          expanded={expanded.system}
          onToggle={() => toggleExpanded('system')}
          basicContent={(
            <div className="field-grid">
              <label>
                <span>工作目录</span>
                <input value={config.processing.work_dir} onChange={(event) => setField('processing', 'work_dir', event.target.value)} />
              </label>
              <label>
                <span>自动重试模式</span>
                <select value={config.processing.retry_mode} onChange={(event) => setField('processing', 'retry_mode', event.target.value as AppConfig['processing']['retry_mode'])}>
                  {retryModeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          advancedContent={(
            <section className="advanced-section">
              <div className="field-grid">
                <label>
                  <span>任务最大重试</span>
                  <input type="number" value={config.processing.max_retries} onChange={(event) => setField('processing', 'max_retries', Number(event.target.value))} />
                </label>
                <label>
                  <span>轮询间隔（秒）</span>
                  <input type="number" value={config.processing.poll_interval_seconds} onChange={(event) => setField('processing', 'poll_interval_seconds', Number(event.target.value))} />
                </label>
                <label className="switch-row">
                  <span>保留中间产物</span>
                  <input type="checkbox" checked={config.processing.keep_intermediates} onChange={(event) => setField('processing', 'keep_intermediates', event.target.checked)} />
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
            </section>
          )}
        />
      </div>

      <div className="page-actions settings-action-bar">
        <div className="settings-action-meta">
          <span className="settings-action-title">配置变更</span>
          <span className="muted">{changedSectionCount > 0 ? `当前有 ${changedSectionCount} 个分组未保存` : '当前没有未保存改动'}</span>
        </div>
        <div className="inline-actions">
          <button className="ghost-button" onClick={handleReset}>重置默认</button>
          <button disabled={saving} onClick={() => void submit()}>
            {saving ? '保存中…' : '保存设置'}
          </button>
        </div>
      </div>
    </section>
  )
}
