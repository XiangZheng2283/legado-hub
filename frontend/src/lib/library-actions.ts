import { api } from "@/lib/api"

export function executeLibraryBookAction(bookId: string, action: string, isAdmin: boolean) {
  if (!isAdmin) {
    switch (action) {
      case "resume":
        return api.subscribe.updateSubscription(bookId, { status: "active" })
      case "pause":
        return api.subscribe.updateSubscription(bookId, { status: "paused" })
      case "archive":
        return api.subscribe.updateSubscription(bookId, { status: "archived" })
      default:
        throw new Error(`不支持的书库操作：${action || "空操作"}`)
    }
  }

  switch (action) {
    case "pause":
      return api.pauseLibraryBook(bookId)
    case "resume":
      return api.resumeLibraryBook(bookId)
    case "archive":
      return api.archiveLibraryBook(bookId)
    case "rebuild":
      return api.rebuildLibraryBook(bookId)
    default:
      throw new Error(`不支持的书库操作：${action || "空操作"}`)
  }
}

export function executeLibraryBookMaintenanceAction(bookId: string, action: string) {
  switch (action) {
    case "check-update":
      return api.checkLibraryBookUpdate(bookId)
    case "refresh-sources":
      return api.refreshLibraryBookSources(bookId, { force: true })
    case "repair":
      return api.repairLibraryBook(bookId, { reason: "manual" })
    case "rebuild":
      return api.rebuildLibraryBook(bookId)
    default:
      throw new Error(`不支持的维护操作：${action || "空操作"}`)
  }
}
