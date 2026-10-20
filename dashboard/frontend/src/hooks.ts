import { useEffect, useRef, useState } from "react";

export function usePoll<T>(path: string, interval: number) {
  const [result, setResult] = useState<{
    data?: T;
    error?: string;
    lastSuccess?: Date;
  }>({});
  const [revision, setRevision] = useState(0);
  const pathRef = useRef(path);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    if (pathRef.current !== path) {
      setResult({});
      pathRef.current = path;
    }
    async function run() {
      try {
        const response = await fetch(path, {
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(8000)]),
        });
        if (!response.ok) throw new Error(`API ${response.status}`);
        const data: T = await response.json();
        if (alive) setResult({ data, lastSuccess: new Date() });
      } catch (error) {
        if (alive)
          setResult((old) => ({
            ...old,
            error: error instanceof Error ? error.message : "Connection failed",
          }));
      } finally {
        if (alive) timer = setTimeout(run, interval);
      }
    }
    void run();
    return () => {
      alive = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [path, interval, revision]);
  return { ...result, refresh: () => setRevision((r) => r + 1) };
}

export function useClock() {
  const [time, setTime] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setTime(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return time;
}
