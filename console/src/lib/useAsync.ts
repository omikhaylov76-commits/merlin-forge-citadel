import { useCallback, useEffect, useState } from 'react'

export type AsyncState<T> = { loading: boolean; error: Error | null; data: T | null }

// Единый хук загрузки: экраны получают состояния грузится/ошибка/данные из одного места (#32).
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ loading: true, error: null, data: null })

  const run = useCallback(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((data) => {
        if (alive) setState({ loading: false, error: null, data })
      })
      .catch((error: unknown) => {
        if (alive) setState({ loading: false, error: error as Error, data: null })
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(run, [run])
  return { ...state, reload: run }
}
