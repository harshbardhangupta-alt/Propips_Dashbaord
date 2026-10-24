import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, ms: number): T {
  const key = JSON.stringify(value);
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms]);
  return v;
}
