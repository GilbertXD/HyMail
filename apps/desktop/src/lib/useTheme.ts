import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyTheme,
  nextTheme,
  persistTheme,
  resolveInitialTheme,
  type Theme,
} from "./theme";

/**
 * Owns the current theme and keeps `<html class="dark">` in sync.
 *
 * The starting value is only persisted once the user actually toggles, so a
 * user who never touches the control keeps following the operating system.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(resolveInitialTheme);
  const explicitlyChosen = useRef(false);

  useEffect(() => {
    applyTheme(theme);
    if (explicitlyChosen.current) {
      persistTheme(theme);
    }
  }, [theme]);

  const toggle = useCallback(() => {
    explicitlyChosen.current = true;
    setTheme(nextTheme);
  }, []);

  return { theme, toggle };
}
