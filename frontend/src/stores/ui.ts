import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import type { Item } from '@/lib/api'

export type ReaderTab = 'analysis' | 'reader'
export type WatchTab = 'targets' | 'proposals' | 'backup'

export const useUiStore = defineStore('ui', () => {
  // Navigation & Layout
  const sidebarOpen = useLocalStorage('omnikeep-sidebar', true)
  const sidebarMobileOpen = ref(false)

  // Reader pane — deep reactive: the same item exists as separate objects in
  // the list and here, so mutations are synced into both copies by id.
  const activeItem = ref<Item | null>(null)
  const detailTab = ref<ReaderTab>('analysis')
  const readerFontSize = useLocalStorage('omnikeep-reader-font', 15)
  const readerLineHeight = useLocalStorage('omnikeep-reader-lineh', 1.8)
  const readerWidth = useLocalStorage('omnikeep-reader-width', 720)
  const focusMode = ref(false)

  // Modals
  const showNoteModal = ref(false)
  const showCategoryModal = ref(false)
  const showShortcutsModal = ref(false)
  const showRadarModal = ref(false)
  const showSessionModal = ref(false)
  const showWatchModal = ref(false)
  const watchTab = ref<WatchTab>('targets')
  const showImportModal = ref(false)
  const showDeckModal = ref(false)
  const showPushModal = ref(false)
  const showSettingsModal = ref(false)
  const settingsTab = ref('ai')
  /** Bumped after settings are saved, so the service-status banner re-checks. */
  const settingsVersion = ref(0)

  function openSettings(tab = 'ai') {
    settingsTab.value = tab
    showSettingsModal.value = true
    sidebarMobileOpen.value = false
  }

  // Ingest
  const isIngesting = ref(false)

  return {
    sidebarOpen, sidebarMobileOpen,
    activeItem, detailTab, readerFontSize, readerLineHeight, readerWidth, focusMode,
    showNoteModal, showCategoryModal, showShortcutsModal, showRadarModal, showSessionModal, showWatchModal, showImportModal, showDeckModal, showPushModal,
    showSettingsModal, settingsTab, settingsVersion, openSettings,
    watchTab,
    isIngesting,
  }
})
