import { onMounted, onUnmounted } from 'vue'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'
import { useExperimentsStore } from '@/stores/experiments'
import { blockedShortcut } from '@/lib/experiments'
import { useMutations } from './useMutations'
import { useSignal } from './useSignal'

type AppHeaderExposed = { focusQuickInput: () => void; focusSearchInput: () => void }

/** Global keyboard shortcuts — parity with the legacy single-file UI and enhanced with Cmd+K. */
export function useKeyboard(header: () => AppHeaderExposed | null, enabled: () => boolean = () => true) {
  const items = useItemsStore()
  const ui = useUiStore()
  const radar = useRadarStore()
  const experiments = useExperimentsStore()
  const { toggleStar, toggleRead } = useMutations()

  function isAnyModalOpen() {
    return (
      ui.showNoteModal ||
      ui.showCategoryModal ||
      ui.showShortcutsModal ||
      ui.showRadarModal ||
      ui.showWatchModal ||
      ui.showImportModal ||
      ui.showDeckModal ||
      ui.showDailyDeckModal ||
      ui.showBrainModal ||
      ui.showCommandPalette ||
      !!ui.snapshotView
    )
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (!enabled() || e.defaultPrevented || e.isComposing) return

    // Global Command Palette shortcut (Cmd+K / Ctrl+K) works anywhere
    if (!e.altKey && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault()
      ui.showCommandPalette = !ui.showCommandPalette
      return
    }

    const el = document.activeElement
    const tag = el?.tagName?.toLowerCase() ?? ''
    const typing =
      tag === 'input' || tag === 'textarea' || tag === 'select' ||
      (el instanceof HTMLElement && el.isContentEditable)

    if (typing) {
      if (e.key === 'Escape') (el as HTMLElement).blur()
      return
    }

    // Modal-level Esc handling; close active modal when open
    if (isAnyModalOpen()) {
      if (e.key === 'Escape') {
        ui.showNoteModal = false
        ui.showCategoryModal = false
        ui.showShortcutsModal = false
        ui.showRadarModal = false
        ui.showWatchModal = false
        ui.showImportModal = false
        ui.showDeckModal = false
        ui.showDailyDeckModal = false
        ui.showBrainModal = false
        ui.showCommandPalette = false
        ui.snapshotView = null
      }
      return
    }

    // The settings page covers the workspace: only Esc means anything there, and it
    // belongs to whatever is open on top of the page (a menu, a confirmation) first.
    if (ui.showSettingsModal) {
      if (e.key === 'Escape' && !document.querySelector('[data-state="open"]:is([role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"])')) {
        ui.settingsCloseRequests++
      }
      return
    }

    // Preserve browser shortcuts, except our custom accelerator (Cmd+B toggle sidebar)
    if (e.ctrlKey || e.metaKey || e.altKey) {
      if (!e.altKey && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        ui.sidebarOpen = !ui.sidebarOpen
      }
      return
    }
    if ((e.key === 'Enter' || e.key === ' ') && el?.closest('button, a')) return
    if (el?.closest('[role="tab"], [role="menuitem"]')) return

    // Shortcuts of an experimental feature that is switched off do nothing.
    if (blockedShortcut(e.key, experiments.flags)) return

    switch (e.key) {
      case '?':
        e.preventDefault()
        ui.showShortcutsModal = !ui.showShortcutsModal
        return
      case 'b':
      case 'B':
        e.preventDefault()
        ui.showBrainModal = !ui.showBrainModal
        return
      case 'D':
        // Shift+D: daily review (curated unread + resurfaced); plain d reviews the radar's finds one by one
        e.preventDefault()
        ui.showDailyDeckModal = !ui.showDailyDeckModal
        return
      case 'r':
      case 'R':
        e.preventDefault()
        ui.showRadarModal = !ui.showRadarModal
        if (ui.showRadarModal) radar.ensureLoaded()
        return
      case 'i':
      case 'I':
        e.preventDefault()
        ui.showImportModal = !ui.showImportModal
        return
      case 'd':
        e.preventDefault()
        ui.showDeckModal = true
        return

      case '+':
      case '=':
        if (ui.activeItem) {
          e.preventDefault()
          useSignal().tuneItem({ item: ui.activeItem, action: 'boost' })
        }
        return
      case '-':
      case '_':
        if (ui.activeItem) {
          e.preventDefault()
          useSignal().tuneItem({ item: ui.activeItem, action: 'dampen' })
        }
        return
      case 'Escape':
        if (ui.sidebarMobileOpen) {
          ui.sidebarMobileOpen = false
        } else if (ui.focusMode) {
          ui.focusMode = false
        } else if (ui.activeItem) {
          ui.activeItem = null
        }
        return
      case '/':
        e.preventDefault()
        header()?.focusSearchInput()
        return
      case 'n':
        e.preventDefault()
        header()?.focusQuickInput()
        return
      case 'N':
        e.preventDefault()
        ui.showNoteModal = true
        return
    }

    // The list and the cover wall show the same filtered, ordered items; J/K walk those.
    const list = items.visibleItems
    if (list.length === 0) return
    const anchorId = ui.activeItem?.id ?? ui.cursorId
    const currentIndex = anchorId == null ? -1 : list.findIndex((i) => i.id === anchorId)
    // In the cover wall J/K move a cursor and Enter opens it. The list, and either
    // view once the reader is open, opens each item as it moves (master–detail).
    const browsing = items.viewMode === 'cards' && !ui.activeItem
    const moveTo = (index: number) => {
      ui.cursorId = list[index].id
      if (!browsing) ui.activeItem = list[index]
    }
    const target = ui.activeItem ?? (browsing && currentIndex >= 0 ? list[currentIndex] : null)

    if (e.key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault()
      moveTo(Math.min(list.length - 1, currentIndex + 1))
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault()
      moveTo(Math.max(0, currentIndex - 1))
    } else if (e.key === 'e' || e.key === 'E') {
      if (target) {
        e.preventDefault()
        toggleRead(target)
      }
    } else if (e.key === 's' || e.key === 'S') {
      if (target) {
        e.preventDefault()
        toggleStar(target)
      }
    } else if (e.key === 'Enter') {
      if (!ui.activeItem) {
        ui.activeItem = list[Math.max(0, currentIndex)]
        ui.detailTab = 'analysis'
      }
    }
  }

  onMounted(() => window.addEventListener('keydown', handleKeyDown))
  onUnmounted(() => window.removeEventListener('keydown', handleKeyDown))
}
