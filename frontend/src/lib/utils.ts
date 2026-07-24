import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Copy text to clipboard. Prefers navigator.clipboard; falls back to
 * execCommand for HTTP / dialog focus traps where Clipboard API is blocked.
 */
export async function copyTextToClipboard(text: string): Promise<void> {
  const value = String(text ?? "")
  if (!value) throw new Error("empty")

  if (typeof navigator !== "undefined" && window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Fall through to execCommand (some browsers deny clipboard even on https).
    }
  }

  // Prefer mounting inside the open dialog so Radix focus scope allows select/copy.
  const mountParent =
    (typeof document !== "undefined" &&
      (document.activeElement?.closest?.('[role="dialog"]') as HTMLElement | null)) ||
    document.body

  const textarea = document.createElement("textarea")
  textarea.value = value
  textarea.setAttribute("readonly", "")
  textarea.setAttribute("aria-hidden", "true")
  // iOS / focus-trap friendly: keep in viewport, not opacity-0 only.
  textarea.style.cssText =
    "position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:0;outline:none;box-shadow:none;background:transparent;opacity:0.01;z-index:2147483647;"
  mountParent.appendChild(textarea)

  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null

  textarea.focus({ preventScroll: true })
  textarea.select()
  textarea.setSelectionRange(0, value.length)

  let ok = false
  try {
    ok = document.execCommand("copy")
  } finally {
    mountParent.removeChild(textarea)
    if (selection) {
      selection.removeAllRanges()
      if (previousRange) {
        try {
          selection.addRange(previousRange)
        } catch {
          /* ignore */
        }
      }
    }
  }
  if (!ok) throw new Error("copy failed")
}
