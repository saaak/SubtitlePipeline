import { useEffect, useMemo, useState } from 'react'

import { browseDirectory, BrowseDirectoryResponse } from '../api'

type DirectoryPickerProps = {
  value: string
  onChange: (value: string) => void
  label?: string
  placeholder?: string
  disabled?: boolean
}

function getInitialPath(value: string) {
  const trimmed = value.trim()
  return trimmed || undefined
}

export function DirectoryPicker({
  value,
  onChange,
  label,
  placeholder,
  disabled = false,
}: DirectoryPickerProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [browser, setBrowser] = useState<BrowseDirectoryResponse | null>(null)
  const initialPath = useMemo(() => getInitialPath(value), [value])

  const load = async (path?: string) => {
    setLoading(true)
    try {
      const result = await browseDirectory(path)
      setBrowser(result)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '目录读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) {
      return
    }
    void load(initialPath)
  }, [initialPath, open])

  return (
    <div className="directory-picker">
      {label ? <span>{label}</span> : null}
      <div className="directory-picker-row">
        <input value={value} placeholder={placeholder} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
        <button type="button" className="ghost-button" disabled={disabled} onClick={() => setOpen(true)}>
          浏览
        </button>
      </div>
      {open ? (
        <div className="dialog-backdrop" role="presentation">
          <div className="dialog-card">
            <div className="card-header">
              <div>
                <h3>选择目录</h3>
                <p className="muted">{browser?.current || '加载中…'}</p>
              </div>
              <button type="button" className="text-button" onClick={() => setOpen(false)}>
                关闭
              </button>
            </div>
            {error ? <div className="alert error">{error}</div> : null}
            <div className="directory-browser-toolbar">
              <button type="button" className="ghost-button" disabled={loading || !browser?.parent} onClick={() => void load(browser?.parent || undefined)}>
                上一级
              </button>
              <button type="button" disabled={loading || !browser?.current} onClick={() => {
                if (browser?.current) {
                  onChange(browser.current)
                  setOpen(false)
                }
              }}>
                选择此目录
              </button>
            </div>
            <div className="directory-browser-list">
              {loading ? <div className="muted">目录加载中…</div> : null}
              {!loading && browser?.dirs.length === 0 ? <div className="muted">当前目录下没有子目录</div> : null}
              {!loading
                ? browser?.dirs.map((name) => {
                    const separator = browser.current.includes('\\') ? '\\' : '/'
                    const nextPath = browser.current.endsWith(separator) ? `${browser.current}${name}` : `${browser.current}${separator}${name}`
                    return (
                      <button key={nextPath} type="button" className="directory-entry" onClick={() => void load(nextPath)}>
                        {name}
                      </button>
                    )
                  })
                : null}
            </div>
            <div className="page-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => {
                  onChange(browser?.current || value)
                  setOpen(false)
                }}
                disabled={!browser?.current}
              >
                使用当前路径
              </button>
              <button type="button" className="text-button" onClick={() => setOpen(false)}>
                取消
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
