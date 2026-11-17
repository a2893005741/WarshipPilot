import { useCallback, useSyncExternalStore } from 'react'

/** 与 CSS 断点同步；只在查询结果改变时通知组件。 */
export function useMediaQuery(query: string) {
  const subscribe = useCallback((listener: () => void) => {
    if (typeof window === 'undefined' || !window.matchMedia) return () => {}
    const media = window.matchMedia(query)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [query])
  const snapshot = useCallback(() => typeof window !== 'undefined' && Boolean(window.matchMedia?.(query).matches), [query])
  return useSyncExternalStore(subscribe, snapshot, () => false)
}
