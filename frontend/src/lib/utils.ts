import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Copy text to clipboard. Prefers navigator.clipboard; falls back to
 * execCommand for HTTP LAN admin consoles where Clipboard API is blocked.
 */
export async function copyTextToClipboard(text: string): Promise<void> {
  const value = String(text ?? "")
  if (!value) throw new Error("empty")

  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Non-secure context (http://LAN-IP) or permission denied → fallback.
    }
  }

  const textarea = document.createElement("textarea")
  textarea.value = value
  textarea.setAttribute("readonly", "")
  textarea.style.position = "fixed"
  textarea.style.top = "0"
  textarea.style.left = "0"
  textarea.style.width = "1px"
  textarea.style.height = "1px"
  textarea.style.padding = "0"
  textarea.style.border = "none"
  textarea.style.outline = "none"
  textarea.style.boxShadow = "none"
  textarea.style.background = "transparent"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)

  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null

  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, value.length)

  let ok = false
  try {
    ok = document.execCommand("copy")
  } finally {
    document.body.removeChild(textarea)
    if (selection) {
      selection.removeAllRanges()
      if (previousRange) selection.addRange(previousRange)
    }
  }
  if (!ok) throw new Error("copy failed")
}
