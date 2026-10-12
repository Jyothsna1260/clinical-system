import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

/** Run an async loader on mount (and when deps change), with a reload function. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const prevDeps = useRef<unknown[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    // New inputs (e.g. another run id in the URL) clear old data; a plain reload keeps it on screen.
    const changed = prevDeps.current !== null && deps.some((d, i) => !Object.is(d, prevDeps.current?.[i]));
    prevDeps.current = deps;
    if (changed) setData(null);
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The caller owns `deps` (like useEffect's own dependency list); `nonce` forces a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload, setData };
}
