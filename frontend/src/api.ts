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

export type AppConfig = {
  file: {
    input_dir: string
    output_dir: string
    allowed_extensions: string[]
    scan_interval_seconds: number
    min_size_mb: number
    max_size_mb: number
    in_place: boolean
  }
  processing: {
    max_retries: number
    poll_interval_seconds: number
    work_dir: string
  }
  whisper: {
    model_name: string
    device: string
    audio_format: string
    sample_rate: number
    align_model: string
  }
  translation: {
    enabled: boolean
    target_languages: string[]
    max_retries: number
    timeout_seconds: number
    api_base_url: string
    api_key: string
    model: string
  }
  subtitle: {
    bilingual: boolean
    bilingual_mode: string
    filename_template: string
    source_language: string
    text_process_style: string
  }
  logging: {
    page_size: number
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
}

export type TranslationTestResponse = {
  success: boolean
  message: string
}

export const defaultAppConfig: AppConfig = {
  file: {
    input_dir: '/data',
    output_dir: '/output',
    allowed_extensions: ['.mp4', '.mkv', '.mov', '.avi'],
    scan_interval_seconds: 5,
    min_size_mb: 1,
    max_size_mb: 4096,
    in_place: false,
  },
  processing: {
    max_retries: 1,
    poll_interval_seconds: 2,
    work_dir: '/config/work',
  },
  whisper: {
    model_name: 'small',
    device: 'cpu',
    audio_format: 'wav',
    sample_rate: 16000,
    align_model: 'auto',
  },
  translation: {
    enabled: true,
    target_languages: ['zh-CN'],
    max_retries: 2,
    timeout_seconds: 30,
    api_base_url: 'https://api.openai.com',
    api_key: '',
    model: 'gpt-4o-mini',
  },
  subtitle: {
    bilingual: true,
    bilingual_mode: 'merge',
    filename_template: '{stem}.{lang}.srt',
    source_language: 'auto',
    text_process_style: 'basic',
  },
  logging: {
    page_size: 50,
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

export function getTasks(): Promise<TaskListResponse> {
  return request<TaskListResponse>('/api/tasks?page=1&page_size=20')
}

export function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}`)
}

export function getTaskLogs(taskId: string, page: number): Promise<LogResponse> {
  return request<LogResponse>(`/api/tasks/${taskId}/logs?page=${page}&page_size=20`)
}

export function retryTask(taskId: number): Promise<void> {
  return request<void>(`/api/tasks/${taskId}/retry`, { method: 'POST' })
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
