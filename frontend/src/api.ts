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
export type SourceLanguage = 'auto' | 'en' | 'zh' | 'ja'

export type TranslationContentType =
  | 'general'
  | 'movie'
  | 'documentary'
  | 'anime'
  | 'tech_talk'
  | 'variety_show'
  | 'news'

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
  scanner: {
    max_pending_tasks: number
  }
  whisper: {
    model_name: string
    device: string
    audio_format: string
    sample_rate: number
  }
  translation: {
    enabled: boolean
    target_languages: string[]
    max_retries: number
    timeout_seconds: number
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
  error?: string | null
  stalled?: boolean
  manual_download_url?: string | null
}

export type ModelListResponse = {
  items: ModelItem[]
  current_model: string
}

export type TranslationTestPayload = {
  enabled: boolean
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
  { value: 'en', label: '英语' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日语' },
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
  scanner: {
    max_pending_tasks: 5,
  },
  whisper: {
    model_name: 'small',
    device: 'auto',
    audio_format: 'wav',
    sample_rate: 16000,
  },
  translation: {
    enabled: true,
    target_languages: ['zh-CN'],
    max_retries: 2,
    timeout_seconds: 30,
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
