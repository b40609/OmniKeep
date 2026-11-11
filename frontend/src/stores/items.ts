import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import * as api from '@/lib/api'
import type { Item, Category, Stats } from '@/lib/api'
import { arrangeItems, type KindFilter } from '@/lib/wall'

export type TriageView = 'inbox' | 'starred' | 'archived' | 'all' | 'radar'
export type ViewMode = 'list' | 'cards'
export type SearchMode = 'keyword' | 'semantic'
export type SortOrder = 'newest' | 'oldest'

/** The API returns one page; the list never asks for the next one. */
export const PAGE_SIZE = 50

export const useItemsStore = defineStore('items', () => {
  const items = ref<Item[]>([])
  const categories = ref<Category[]>([])
  const stats = ref<Stats>({ inbox: 0, starred: 0, archived: 0, radar: 0, total: 0 })
  const loading = ref(false)
  const error = ref<string | null>(null)
  let requestId = 0

  // Filters
  const triageView = ref<TriageView>('inbox')
  const currentCategory = ref('全部')
  const searchQuery = ref('')
  const searchMode = ref<SearchMode>('keyword')
  // The cover wall is the default; a view picked on this browser is remembered.
  const viewMode = useLocalStorage<ViewMode>('omnikeep-view', 'cards')
  // Kind tabs and sort order work on the loaded page only: the API has no parameter for either.
  const kindFilter = ref<KindFilter>('all')
  const sortOrder = ref<SortOrder>('newest')
  /** Search results arrive ranked by relevance, so they are neither re-sorted nor split by date. */
  const ranked = computed(() => !!searchQuery.value.trim())
  /** What the list and the wall show, and what J/K move through. */
  const visibleItems = computed(() =>
    arrangeItems(items.value, kindFilter.value, !ranked.value && sortOrder.value === 'oldest' ? 'oldest' : 'server'),
  )

  async function loadItems() {
    const request = ++requestId
    const category = currentCategory.value
    const view = triageView.value
    loading.value = true
    error.value = null
    try {
      const q = searchQuery.value.trim()
      let result: Item[]
      if (q && searchMode.value === 'semantic') {
        const results = await api.searchSemantic(q, 30)
        result = results.filter((item) => {
          if (category !== '全部' && item.category_name !== category) {
            return false
          }
          if (view === 'inbox' && (item.is_read || (item.origin === 'radar' && !item.is_starred))) return false
          if (view === 'radar' && (item.origin !== 'radar' || item.is_read || item.is_starred)) return false
          if (view === 'archived' && !item.is_read) return false
          if (view === 'starred' && !item.is_starred) return false
          return true
        })
      } else {
        result = await api.getItems({
          category: category !== '全部' ? category : undefined,
          q: q || undefined,
          read: view === 'inbox' || view === 'radar' ? 'false' : view === 'archived' ? 'true' : undefined,
          starred: view === 'starred' ? 'true' : undefined,
          origin: view === 'radar' ? 'radar' : view === 'inbox' ? 'curated' : undefined,
        })
      }
      if (request === requestId) items.value = result
    } catch {
      if (request === requestId) error.value = '無法載入收藏，請確認連線後重試。'
    } finally {
      if (request === requestId) loading.value = false
    }
  }

  function toggleSearchMode() {
    searchMode.value = searchMode.value === 'keyword' ? 'semantic' : 'keyword'
    if (searchQuery.value.trim()) {
      void loadItems()
    }
  }

  async function loadStats() {
    try {
      stats.value = await api.getStats()
    } catch {
      /* stats are non-critical */
    }
  }

  async function loadCategories() {
    try {
      categories.value = await api.getCategories()
    } catch {
      /* keep stale categories */
    }
  }

  function refreshAll() {
    return Promise.all([loadStats(), loadCategories(), loadItems()])
  }

  return {
    items, categories, stats, loading, error,
    triageView, currentCategory, searchQuery, searchMode, viewMode,
    kindFilter, sortOrder, ranked, visibleItems,
    toggleSearchMode,
    loadItems, loadStats, loadCategories, refreshAll,
  }
})
