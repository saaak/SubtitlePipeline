export type Task = {
  id: number
  file_path: string
  status: string
  stage: string
  progress: number
  retry_count: number
  max_retries: number
  cancel_requested: number | boolean
  restart_required?: number | boolean
  error_message?: string | null
  result_payload?: {
    subtitle_paths?: string[]
    mux_path?: string
  } | null
  config_snapshot?: Record<string, unknown> | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type TaskListResponse = {
  items: Task[]
  total: number
  page: number
  page_size: number
  status_counts: Record<string, number>
}

export type LogItem = {
  id: number
  stage: string
  level: string
  message: string
  timestamp: string
}

export type LogResponse = {
  items: LogItem[]
  total: number
  page: number
  page_size: number
}

export type RetryMode = 'restart' | 'resume'
export type BilingualMode = 'merge' | 'separate'
export type SourceLanguage = string

export type TranslationContentType =
  | 'general'
  | 'movie'
  | 'documentary'
  | 'anime'
  | 'tech_talk'
  | 'variety_show'
  | 'news'

export type LLMType = 'openai-chat' | 'openai-responses' | 'openai-compatible' | 'anthropic' | 'lmstudio' | 'ollama'
export type ASRProvider = 'whisperx' | 'faster-whisper' | 'anime-whisper' | 'qwen'
export type AlignProvider = 'auto' | 'whisperx' | 'qwen-forced' | 'none'
export type ModelProvider = ASRProvider | 'qwen-forced'

export type AdvancedConfig = {
  whisperx_align_extend: number
  whisperx_compute_type: string
  faster_whisper_word_timestamps: boolean
  faster_whisper_compute_type: string
  anime_whisper_enhance_dialogue: boolean
  anime_whisper_dtype: string
  qwen_temperature: number
  qwen_dtype: string
  qwen_max_inference_batch_size: number
  qwen_max_new_tokens: number
}

export type ProviderInfo = {
  display_name: string
  description: string
  features: string[]
  best_for: string
}

export type AppConfig = {
  file: {
    input_dir: string
    output_to_source_dir: boolean
    allowed_extensions: string[]
    scan_interval_seconds: number
    min_size_mb: number
    max_size_mb: number
  }
  processing: {
    max_retries: number
    retry_mode: 'restart' | 'resume'
    keep_intermediates: boolean
    poll_interval_seconds: number
    work_dir: string
  }
  whisper: {
    provider: ASRProvider
    model_name: string
    device: string
    audio_format: string
    sample_rate: number
    beam_size: number
    vad_filter: boolean
    vad_threshold: number
    align_provider: AlignProvider
    advanced: AdvancedConfig
  }
  translation: {
    enabled: boolean
    target_languages: string[]
    max_retries: number
    timeout_seconds: number
    llm_type: LLMType
    api_base_url: string
    api_key: string
    model: string
    content_type: TranslationContentType
    custom_prompt: string
  }
  subtitle: {
    bilingual: boolean
    bilingual_mode: BilingualMode
    filename_template: string
    source_language: SourceLanguage
  }
  mux: {
    enabled: boolean
    filename_template: string
  }
  logging: {
    level: string
  }
  meta?: {
    restart_required: boolean
  }
}

export type SystemStatus = {
  setup_complete: boolean
  asr_ready: boolean
  translation_ready: boolean
  current_model: string
  current_provider?: ASRProvider
  proxy: {
    http_proxy: string | null
    https_proxy: string | null
    hf_endpoint: string | null
  }
}

export type ModelItem = {
  name: string
  repo_id: string
  size_label: string
  estimated_size_bytes: number
  status: 'not_installed' | 'downloading' | 'installed'
  progress: number
  current: boolean
  path: string
  provider: ModelProvider
  display_name: string
  description: string
  tags: string[]
  model_type: 'asr' | 'aligner'
  error?: string | null
  stalled?: boolean
  manual_download_url?: string | null
}

export type ModelListResponse = {
  items: ModelItem[]
  current_model: string
  current_provider?: ASRProvider
  providers?: Record<string, ProviderInfo>
}

export type TranslationTestPayload = {
  enabled: boolean
  llm_type: LLMType
  api_base_url: string
  api_key: string
  model: string
  timeout_seconds: number
  target_language?: string
  content_type?: TranslationContentType
  custom_prompt?: string
}

export type TranslationTestResponse = {
  success: boolean
  message: string
}

export type ResumeCheckResponse = {
  can_resume: boolean
  missing: string[]
}

export type BrowseDirectoryResponse = {
  current: string
  parent?: string | null
  dirs: string[]
}

export const translationContentTypeOptions: Array<{ value: TranslationContentType; label: string }> = [
  { value: 'general', label: '通用' },
  { value: 'movie', label: '电影/电视剧' },
  { value: 'documentary', label: '纪录片' },
  { value: 'anime', label: '动漫' },
  { value: 'tech_talk', label: '技术讲座' },
  { value: 'variety_show', label: '综艺/脱口秀' },
  { value: 'news', label: '新闻' },
]

export const llmTypeOptions: Array<{ value: LLMType; label: string; defaultBaseUrl: string }> = [
  { value: 'openai-chat', label: 'OpenAI Chat Completions', defaultBaseUrl: 'https://api.openai.com' },
  { value: 'openai-responses', label: 'OpenAI Responses', defaultBaseUrl: 'https://api.openai.com' },
  { value: 'openai-compatible', label: 'OpenAI Compatible', defaultBaseUrl: 'https://api.openai.com' },
  { value: 'anthropic', label: 'Anthropic Messages', defaultBaseUrl: 'https://api.anthropic.com' },
  { value: 'lmstudio', label: 'LM Studio', defaultBaseUrl: 'http://localhost:1234' },
  { value: 'ollama', label: 'Ollama', defaultBaseUrl: 'http://localhost:11434' },
]

export const bilingualModeOptions: Array<{ value: BilingualMode; label: string }> = [
  { value: 'merge', label: '合并显示' },
  { value: 'separate', label: '分离显示' },
]

export const retryModeOptions: Array<{ value: RetryMode; label: string }> = [
  { value: 'restart', label: '从头重试' },
  { value: 'resume', label: '断点续传' },
]

export const sourceLanguageOptions: Array<{ value: SourceLanguage; label: string }> = [
  { value: 'auto', label: '自动检测' },
  { value: 'zh', label: '中文' },
  { value: 'yue', label: '粤语' },
  { value: 'en', label: '英语' },
  { value: 'ja', label: '日语' },
  { value: 'ko', label: '韩语' },
  { value: 'fr', label: '法语' },
  { value: 'de', label: '德语' },
  { value: 'es', label: '西班牙语' },
  { value: 'pt', label: '葡萄牙语' },
  { value: 'it', label: '意大利语' },
  { value: 'ru', label: '俄语' },
  { value: 'ar', label: '阿拉伯语' },
  { value: 'th', label: '泰语' },
  { value: 'vi', label: '越南语' },
  { value: 'id', label: '印尼语' },
  { value: 'tr', label: '土耳其语' },
  { value: 'hi', label: '印地语' },
  { value: 'ms', label: '马来语' },
  { value: 'nl', label: '荷兰语' },
  { value: 'sv', label: '瑞典语' },
  { value: 'da', label: '丹麦语' },
  { value: 'fi', label: '芬兰语' },
  { value: 'pl', label: '波兰语' },
  { value: 'cs', label: '捷克语' },
  { value: 'fil', label: '菲律宾语' },
  { value: 'fa', label: '波斯语' },
  { value: 'el', label: '希腊语' },
  { value: 'ro', label: '罗马尼亚语' },
  { value: 'hu', label: '匈牙利语' },
]

export const asrProviderOptions: Array<{ value: ASRProvider; label: string }> = [
  { value: 'whisperx', label: 'WhisperX' },
  { value: 'faster-whisper', label: 'Faster-Whisper' },
  { value: 'anime-whisper', label: 'Anime-Whisper' },
  { value: 'qwen', label: 'Qwen-ASR' },
]

export const defaultAppConfig: AppConfig = {
  file: {
    input_dir: '/data',
    output_to_source_dir: true,
    allowed_extensions: ['.mp4', '.mkv', '.mov', '.avi'],
    scan_interval_seconds: 5,
    min_size_mb: 1,
    max_size_mb: 4096,
  },
  processing: {
    max_retries: 1,
    retry_mode: 'restart',
    keep_intermediates: false,
    poll_interval_seconds: 2,
    work_dir: '/config/work',
  },
  whisper: {
    provider: 'whisperx',
    model_name: 'whisperx-small',
    device: 'auto',
    audio_format: 'wav',
    sample_rate: 16000,
    beam_size: 5,
    vad_filter: true,
    vad_threshold: 0.5,
    align_provider: 'auto',
    advanced: {
      whisperx_align_extend: 2,
      whisperx_compute_type: 'auto',
      faster_whisper_word_timestamps: false,
      faster_whisper_compute_type: 'auto',
      anime_whisper_enhance_dialogue: true,
      anime_whisper_dtype: 'auto',
      qwen_temperature: 0,
      qwen_dtype: 'auto',
      qwen_max_inference_batch_size: 32,
      qwen_max_new_tokens: 256,
    },
  },
  translation: {
    enabled: true,
    target_languages: ['zh'],
    max_retries: 2,
    timeout_seconds: 30,
    llm_type: 'openai-chat',
    api_base_url: 'https://api.openai.com',
    api_key: '',
    model: 'gpt-4o-mini',
    content_type: 'general',
    custom_prompt: '',
  },
  subtitle: {
    bilingual: true,
    bilingual_mode: 'merge',
    filename_template: '{stem}.{lang}.srt',
    source_language: 'auto',
  },
  mux: {
    enabled: false,
    filename_template: '{stem}.subbed.mkv',
  },
  logging: {
    level: 'INFO',
  },
  meta: {
    restart_required: false,
  },
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    let message = response.statusText
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') {
        message = payload.detail
      } else {
        message = JSON.stringify(payload)
      }
    } catch {
      message = await response.text()
    }
    throw new Error(message || '请求失败')
  }
  if (response.status === 204) {
    return undefined as T
  }
  return response.json() as Promise<T>
}

export function cloneConfig(config: AppConfig): AppConfig {
  return structuredClone(config)
}

export function getTasks(status?: string, page = 1, pageSize = 20): Promise<TaskListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (status) {
    params.set('status', status)
  }
  return request<TaskListResponse>(`/api/tasks?${params.toString()}`)
}

export function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}`)
}

export function getTaskLogs(taskId: string, page: number): Promise<LogResponse> {
  return request<LogResponse>(`/api/tasks/${taskId}/logs?page=${page}&page_size=20`)
}

export function retryTask(taskId: number, mode: RetryMode): Promise<void> {
  return request<void>(`/api/tasks/${taskId}/retry`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}

export function cancelTask(taskId: number): Promise<void> {
  return request<void>(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
}

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>('/api/config')
}

export function updateConfig(config: Partial<AppConfig>): Promise<AppConfig> {
  return request<AppConfig>('/api/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  })
}

export function browseDirectory(path?: string): Promise<BrowseDirectoryResponse> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<BrowseDirectoryResponse>(`/api/browse${query}`)
}

export function checkResumeFeasibility(taskId: number): Promise<ResumeCheckResponse> {
  return request<ResumeCheckResponse>(`/api/tasks/${taskId}/resume-check`)
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>('/api/system/status')
}

export function setSetupComplete(setup_complete: boolean): Promise<SystemStatus> {
  return request<SystemStatus>('/api/system/setup-complete', {
    method: 'POST',
    body: JSON.stringify({ setup_complete }),
  })
}

export function testTranslation(payload: TranslationTestPayload): Promise<TranslationTestResponse> {
  return request<TranslationTestResponse>('/api/translation/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getModels(): Promise<ModelListResponse> {
  return request<ModelListResponse>('/api/models')
}

export function downloadModel(name: string): Promise<{ message: string }> {
  return request<{ message: string }>(`/api/models/${name}/download`, { method: 'POST' })
}

export function deleteModel(name: string): Promise<{ message: string }> {
  return request<{ message: string }>(`/api/models/${name}`, { method: 'DELETE' })
}

export function activateModel(name: string): Promise<{ message: string; config: AppConfig }> {
  return request<{ message: string; config: AppConfig }>(`/api/models/${name}/activate`, { method: 'POST' })
}
