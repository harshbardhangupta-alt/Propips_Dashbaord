import { useEffect, useState } from "react";

type Code = "D1_MTF" | "D2_MECH";
const KEY = "pt.selectedAccount";
const listeners = new Set<(c: Code) => void>();

function read(): Code {
  try {
    const v = localStorage.getItem(KEY);
    return v === "D2_MECH" ? "D2_MECH" : "D1_MTF";
  } catch {
    return "D1_MTF";
  }
}

/** Selected paper account shown in the header (a per-browser display preference only). */
export function useAccount(): [Code, (c: Code) => void] {
  const [v, setV] = useState<Code>(read);
  useEffect(() => {
    listeners.add(setV);
    return () => void listeners.delete(setV);
  }, []);
  const set = (c: Code) => {
    try {
      localStorage.setItem(KEY, c);
    } catch {
      /* storage unavailable */
    }
    listeners.forEach((l) => l(c));
  };
  return [v, set];
}
