"use client";

import { useEffect, useState } from "react";
import { Icon } from "./Icon";

type Theme = "system" | "light" | "dark";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const ICON: Record<Theme, string> = { system: "brightness_auto", light: "light_mode", dark: "dark_mode" };
const LABEL: Record<Theme, string> = { system: "Theme: System", light: "Theme: Light", dark: "Theme: Dark" };

function readTheme(): Theme {
  const m = document.cookie.match(/(?:^|; )theme=(light|dark)/);
  return (m?.[1] as Theme) ?? "system";
}

export function ThemeToggle({ withLabel = false }: { withLabel?: boolean }) {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => setTheme(readTheme()), []);

  function cycle() {
    const next = NEXT[theme];
    setTheme(next);
    if (next === "system") {
      document.cookie = "theme=; path=/; max-age=0; samesite=lax";
      delete document.documentElement.dataset.theme;
    } else {
      document.cookie = `theme=${next}; path=/; max-age=31536000; samesite=lax`;
      document.documentElement.dataset.theme = next;
    }
  }

  if (withLabel) {
    return (
      <button className="li" onClick={cycle}>
        <span className="lead"><Icon n={ICON[theme]} /></span>
        <span className="txt"><span className="h">Appearance</span><span className="s" style={{ display: "block" }}>{LABEL[theme].replace("Theme: ", "")}</span></span>
      </button>
    );
  }
  return (
    <button className="icon-btn" onClick={cycle} aria-label={LABEL[theme]} title={LABEL[theme]}>
      <Icon n={ICON[theme]} />
    </button>
  );
}
