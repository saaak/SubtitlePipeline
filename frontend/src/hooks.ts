import { DependencyList, useEffect } from 'react'

export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  deps: DependencyList = [],
  enabled: boolean = true,
) {
  useEffect(() => {
    if (!enabled) return
    void callback()
    const timer = window.setInterval(() => {
      void callback()
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [callback, intervalMs, enabled, ...deps])
}
