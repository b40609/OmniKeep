import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import * as api from '@/lib/api'
import type { Item, Category, Stats } from '@/lib/api'
import { arrangeItems, type KindFilter } from '@/lib/wall'

export type TriageView = 'inbox' | 'starred' | 'archived' | 'all' | 'radar'
export type ViewMode = 'list' | 'cards'
export type SearchMode = 'keyword' | 'semantic'
export type SortOrder = 'newest' | 'oldest'

/** Items asked for at a time. A multiple of every column count the wall uses, so pages end on full rows. */
export const PAGE_SIZE = 60

export const useItemsStore = defineStore('items', () => {
  /** What is loaded so far; scrolling asks for the next page. */
  const items = ref<Item[]>([])
  /** How many items the current view, filters and search hold in all; null until known. */
  const total = ref<number | null>(null)
  const categories = ref<Category[]>([])
  const stats = ref<Stats>({ inbox: 0, starred: 0, archived: 0, radar: 0, total: 0 })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const loadingMore = ref(false)
  const moreError = ref<string | null>(null)
  /** False once a page came back short, when the server gave no total to go by. */
  const lastPageFull = ref(false)
  let requestId = 0

  // Filters
  const triageView = ref<TriageView>('inbox')
  const currentCategory = ref('全部')
  const searchQuery = ref('')
  const searchMode = ref<SearchMode>('keyword')
  // The cover wall is the default; a view picked on this browser is remembered.
  const viewMode = useLocalStorage<ViewMode>('omnikeep-view', 'cards')
  // Both are applied by the server, over everything saved, not just the pages loaded.
  const kindFilter = ref<KindFilter>('all')
  const sortOrder = ref<SortOrder>('newest')
  /** Search results arrive ranked by relevance, so they are neither re-sorted nor split by date. */
  const ranked = computed(() => !!searchQuery.value.trim())
  /** Semantic search has no pages and no server-side kind filter: one result set, narrowed here. */
  const semantic = computed(() => ranked.value && searchMode.value === 'semantic')
  /** What the list and the wall show, and what J/K move through. */
  const visibleItems = computed(() => (semantic.value ? arrangeItems(items.value, kindFilter.value, 'server') : items.value))
  const hasMore = computed(() => {
    if (semantic.value) return false
    return total.value != null ? items.value.length < total.value : lastPageFull.value
  })

  function pageFilters(offset: number): api.ItemFilters {
    const view = triageView.value
    return {
      category: currentCategory.value !== '全部' ? currentCategory.value : undefined,
      q: searchQuery.value.trim() || undefined,
      read: view === 'inbox' || view === 'radar' ? 'false' : view === 'archived' ? 'true' : undefined,
      starred: view === 'starred' ? 'true' : undefined,
      origin: view === 'radar' ? 'radar' : view === 'inbox' ? 'curated' : undefined,
      kind: kindFilter.value === 'all' ? undefined : kindFilter.value,
      sort: sortOrder.value,
      limit: PAGE_SIZE,
      offset,
    }
  }

  /** Does this item still belong in the view being shown? (The kind and search filters do not change by editing.) */
  function belongs(item: Item): boolean {
    const view = triageView.value
    if (view === 'inbox') return !item.is_read && (item.origin !== 'radar' || !!item.is_starred)
    if (view === 'radar') return item.origin === 'radar' && !item.is_read && !item.is_starred
    if (view === 'archived') return !!item.is_read
    if (view === 'starred') return !!item.is_starred
    return true
  }

  /** Load the first page for the current view, filters and search. */
  async function loadItems() {
    const request = ++requestId
    const category = currentCategory.value
    const view = triageView.value
    loading.value = true
    loadingMore.value = false
    error.value = null
    moreError.value = null
    try {
      const q = searchQuery.value.trim()
      let result: Item[]
      let count: number | null
      if (q && searchMode.value === 'semantic') {
        const results = await api.searchSemantic(q, 30)
        result = results.filter((item) => (category === '全部' || item.category_name === category) && (view === 'all' || belongs(item)))
        count = null
      } else {
        const page = await api.getItemsPage(pageFilters(0))
        result = page.items
        count = page.total
      }
      if (request !== requestId) return
      items.value = result
      total.value = count
      lastPageFull.value = result.length >= PAGE_SIZE
    } catch {
      if (request === requestId) error.value = '無法載入收藏，請確認連線後重試。'
    } finally {
      if (request === requestId) loading.value = false
    }
  }

  /** Append the next page. Safe to call as often as the scroll position asks. */
  async function loadMore() {
    if (loading.value || loadingMore.value || !hasMore.value) return
    const request = requestId
    loadingMore.value = true
    moreError.value = null
    try {
      const page = await api.getItemsPage(pageFilters(items.value.length))
      if (request !== requestId) return
      // Something saved or archived meanwhile shifts the pages by one: never list an item twice.
      const loaded = new Set(items.value.map((item) => item.id))
      items.value.push(...page.items.filter((item) => !loaded.has(item.id)))
      if (page.total != null) total.value = page.total
      lastPageFull.value = page.items.length >= PAGE_SIZE
      // A short page is the end, whatever the count said a moment ago.
      if (!lastPageFull.value && total.value != null) total.value = items.value.length
    } catch {
      if (request === requestId) moreError.value = '後面的收藏載入失敗。'
    } finally {
      if (request === requestId) loadingMore.value = false
    }
  }

  /**
   * After an item is archived, starred or put back: drop it from the loaded list if
   * the view no longer holds it, or return it to `at` when an undo makes it belong
   * again. Keeps the scroll position, which reloading from the first page would not.
   */
  function reconcile(item: Item, at?: number) {
    const index = items.value.findIndex((i) => i.id === item.id)
    if (belongs(item)) {
      if (index !== -1 || at == null) return
      items.value.splice(Math.min(Math.max(at, 0), items.value.length), 0, item)
      if (total.value != null) total.value++
    } else if (index !== -1) {
      items.value.splice(index, 1)
      if (total.value != null) total.value = Math.max(0, total.value - 1)
    }
  }

  // A kind tab or a sort order is a different list on the server: start again from its first page.
  watch([kindFilter, sortOrder], () => {
    if (!semantic.value) void loadItems()
  })

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
    items, total, categories, stats, loading, error, loadingMore, moreError, hasMore,
    triageView, currentCategory, searchQuery, searchMode, viewMode,
    kindFilter, sortOrder, ranked, visibleItems,
    toggleSearchMode,
    loadItems, loadMore, reconcile, loadStats, loadCategories, refreshAll,
  }
})
