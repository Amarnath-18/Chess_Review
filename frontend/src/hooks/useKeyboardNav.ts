import { useEffect } from "react";

export interface NavHandlers {
  prev: () => void;
  next: () => void;
  first: () => void;
  last: () => void;
  flip: () => void;
  escape?: () => void;
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
};

/** ←/→ step, Home/End jump, F flips the board, Esc leaves a variation. */
export function useKeyboardNav(h: NavHandlers) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const map: Record<string, (() => void) | undefined> = {
        ArrowLeft: h.prev,
        ArrowRight: h.next,
        Home: h.first,
        End: h.last,
        f: h.flip,
        F: h.flip,
        Escape: h.escape,
      };
      const fn = map[e.key];
      if (fn) {
        e.preventDefault();
        fn();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [h]);
}
