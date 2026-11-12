import { toast } from 'vue-sonner'
import * as api from '@/lib/api'
import type { Item } from '@/lib/api'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

/**
 * Optimistic mutations with undo toasts.
 * UI updates instantly; the PATCH fires in the background; on failure the
 * optimistic state rolls back and the toast offers a retry.
 */
export function useMutations() {
  const itemsStore = useItemsStore()
  const ui = useUiStore()

  function rollbackLocal(item: Item, patch: Partial<Item>) {
    Object.assign(item, patch)
    syncPatch(item, patch)
  }

  /** Apply a patch to every copy of this item id (list row + reader pane). */
  function syncPatch(source: Item, patch: Partial<Item>) {
    const listCopy = itemsStore.items.find((i) => i.id === source.id)
    if (listCopy && listCopy !== source) Object.assign(listCopy, patch)
    if (ui.activeItem && ui.activeItem.id === source.id && ui.activeItem !== source) {
      Object.assign(ui.activeItem, patch)
    }
  }

  async function optimisticPatch(
    item: Item,
    patch: Partial<Pick<Item, 'is_read' | 'is_starred' | 'category_name'>>,
    opts: { undoMsg: string; doneMsg: string; undo?: () => void },
  ) {
    const prev = { is_read: item.is_read, is_starred: item.is_starred, category_name: item.category_name }
    Object.assign(item, patch)
    syncPatch(item, patch)
    try {
      await api.patchItem(item.id, patch)
      toast.success(opts.doneMsg, {
        action: opts.undo
          ? { label: '復原', onClick: opts.undo }
          : undefined,
      })
      itemsStore.loadStats()
    } catch (e) {
      rollbackLocal(item, prev)
      // The item may already have left the loaded list: on this rare path, list it again from the server.
      if (!itemsStore.items.some((i) => i.id === item.id)) void itemsStore.loadItems()
      toast.error('更新失敗，已還原', {
        description: (e as Error).message,
        action: { label: '重試', onClick: () => optimisticPatch(item, patch, opts) },
      })
    }
  }

  /** Fire-and-forget behavior tracking — never blocks or breaks UX. */
  function track(event_type: string, item?: Item, meta?: Record<string, unknown>) {
    api.logBehaviorEvent({ event_type, item_id: item ? String(item.id) : undefined, meta }).catch(() => {})
  }

  /**
   * An item that no longer fits the view (archived out of the inbox, unstarred in
   * the starred view) leaves the loaded list after a beat, in place; reloading
   * would throw away every page scrolled so far. Undo puts it back where it was.
   */
  function settleAfter(item: Item) {
    const at = itemsStore.items.findIndex((i) => i.id === item.id)
    setTimeout(() => itemsStore.reconcile(item), 600)
    return () => itemsStore.reconcile(item, at)
  }

  /** Star toggle — optimistic, undo restores previous value. */
  function toggleStar(item: Item) {
    const next = item.is_starred ? 0 : 1
    const restore = settleAfter(item)
    void optimisticPatch(item, { is_starred: next }, {
      undoMsg: '',
      doneMsg: next ? '已加星' : '已取消加星',
      undo: () => {
        void optimisticPatch(item, { is_starred: item.is_starred ? 0 : 1 }, { undoMsg: '', doneMsg: '已復原' })
        restore()
      },
    })
    track(next ? 'star' : 'unstar', item)
  }

  /** Archive/unarchive — optimistic; undo flips it back. */
  function toggleRead(item: Item) {
    const next = item.is_read ? 0 : 1
    const restore = settleAfter(item)
    void optimisticPatch(item, { is_read: next }, {
      undoMsg: '',
      doneMsg: next ? '已封存' : '已取消封存',
      undo: () => {
        void optimisticPatch(item, { is_read: item.is_read ? 0 : 1 }, { undoMsg: '', doneMsg: '已復原' })
        restore()
      },
    })
    track(next ? 'archive' : 'unarchive', item)
  }

  async function updateCategory(item: Item, category_name: string) {
    const prev = item.category_name
    await optimisticPatch(item, { category_name }, {
      undoMsg: '',
      doneMsg: `分類已改為「${category_name}」`,
      undo: () => void optimisticPatch(item, { category_name: prev }, { undoMsg: '', doneMsg: '已復原分類' }),
    })
    itemsStore.loadCategories()
  }

  /** Delete with 5s undo window — hides row instantly, restores on undo. */
  function removeItem(item: Item) {
    const idx = itemsStore.items.findIndex((i) => i.id === item.id)
    if (idx === -1) return
    const removed = itemsStore.items.splice(idx, 1)[0]
    if (ui.activeItem?.id === item.id) ui.activeItem = null

    let undone = false
    const undo = () => {
      undone = true
      itemsStore.items.splice(Math.min(idx, itemsStore.items.length), 0, removed)
    }
    toast('已刪除項目', {
      description: item.title_l1.slice(0, 60),
      duration: 5000,
      action: { label: '復原', onClick: undo },
      onDismiss: () => {
        if (undone) return
        api.deleteItem(item.id).catch(() => {
          // Restore row if the server rejects the delete.
          undo()
          toast.error('刪除失敗，已還原項目')
        })
        itemsStore.loadStats()
      },
    })
  }

  /** Quick ingest from the omnibox. */
  async function quickIngest(content: string, page: Pick<api.IngestOptions, 'pageTitle' | 'pageDescription'> = {}): Promise<boolean> {
    ui.isIngesting = true
    const t = toast.loading('正在收錄並整理摘要…')
    try {
      const data = await api.ingest(content, page)
      if (data.success) {
        toast.success('已成功收錄', {
          id: t,
          description: data.item?.title_l1?.slice(0, 70),
          action: data.item
            ? {
                label: '查看',
                onClick: () => {
                  ui.activeItem = data.item!
                  ui.detailTab = 'analysis'
                },
              }
            : undefined,
        })
        await itemsStore.refreshAll()
        if (data.item) ui.activeItem = data.item
        return true
      } else {
        toast.error('解析失敗', { id: t, description: data.detail || '未知錯誤' })
        return false
      }
    } catch (e) {
      toast.error('擷取失敗', { id: t, description: (e as Error).message })
      return false
    } finally {
      ui.isIngesting = false
    }
  }

  /** Show the offline HTML snapshot (link-rot protection) in SnapshotDialog's sandboxed frame. */
  async function openSnapshot(item: Item) {
    try {
      const t = toast.loading('正在載入離線快照...')
      try {
        const html = await api.fetchSnapshotHtml(item.id)
        ui.snapshotView = { title: item.title_l1, url: item.url, html }
      } finally {
        toast.dismiss(t)
      }
      track('open_snapshot', item)
    } catch (e) {
      toast.error('無法開啟離線快照', { description: (e as Error).message })
    }
  }

  return { toggleStar, toggleRead, updateCategory, removeItem, quickIngest, openSnapshot, track }
}
