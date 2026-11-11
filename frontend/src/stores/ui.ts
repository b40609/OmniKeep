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
  /** Bumped to ask the header to open and focus its search box (the mobile bottom bar does this). */
  const searchFocusRequests = ref(0)

  // Reader pane — deep reactive: the same item exists as separate objects in
  // the list and here, so mutations are synced into both copies by id.
  const activeItem = ref<Item | null>(null)
  /** Item the keyboard is on in the cover wall (J/K) without opening it; null until first used. */
  const cursorId = ref<number | null>(null)
  const detailTab = ref<ReaderTab>('analysis')
  const readerFontSize = useLocalStorage('omnikeep-reader-font', 16)
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
  const showDailyDeckModal = ref(false)
  const showBrainModal = ref(false)
  const showCommandPalette = ref(false)
  const showSettingsModal = ref(false)
  const settingsTab = ref('ai')
  /** Bumped after settings are saved, so the service-status banner re-checks. */
  const settingsVersion = ref(0)
  /** First-run guide shown while no AI provider is usable. */
  const showSetupWizard = ref(false)

  /** AI service card an agent's settings link asked to focus (`#settings=ai&card=agnes`). */
  const settingsCard = ref('')

  function openSettings(tab = 'ai', card = '') {
    settingsTab.value = tab
    settingsCard.value = card
    showSettingsModal.value = true
    sidebarMobileOpen.value = false
  }

  /** Saved page shown in SnapshotDialog; null while closed. */
  const snapshotView = ref<{ title: string; url: string; html: string } | null>(null)

  // Ingest
  const isIngesting = ref(false)

  return {
    sidebarOpen, sidebarMobileOpen, searchFocusRequests,
    activeItem, cursorId, detailTab, readerFontSize, readerLineHeight, readerWidth, focusMode,
    showNoteModal, showCategoryModal, showShortcutsModal, showRadarModal, showSessionModal, showWatchModal, showImportModal, showDeckModal, showPushModal,
    showDailyDeckModal, showBrainModal, showCommandPalette,
    showSettingsModal, settingsTab, settingsCard, settingsVersion, openSettings, showSetupWizard,
    watchTab, snapshotView,
    isIngesting,
  }
})
