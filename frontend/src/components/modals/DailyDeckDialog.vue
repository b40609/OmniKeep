<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import {
  Sparkles, Star, ThumbsUp, ThumbsDown, Clock, CheckCircle2,
  ExternalLink, Compass, History, BookOpen, Loader2
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import Badge from '@/components/ui/badge/Badge.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { getDailyDeck, submitSwipeAction, type DeckCard } from '@/lib/api'

const ui = useUiStore()
const itemsStore = useItemsStore()

const loading = ref(false)
const deckCards = ref<DeckCard[]>([])
const currentIndex = ref(0)
const actionInProgress = ref(false)
const summaryStats = ref({ kept: 0, starred: 0, skipped: 0, snoozed: 0 })
const completed = ref(false)

// ── Touch Gesture State (iOS / iPhone Experience) ───────────
let touchStartX = 0
let touchStartY = 0
const touchDeltaX = ref(0)
const touchDeltaY = ref(0)
const isSwiping = ref(false)
const flyOutDirection = ref<'left' | 'right' | 'up' | 'down' | null>(null)

const currentCard = computed(() => {
  if (currentIndex.value >= 0 && currentIndex.value < deckCards.value.length) {
    return deckCards.value[currentIndex.value]
  }
  return null
})

const progressPercent = computed(() => {
  if (!deckCards.value.length) return 0
  return Math.round((currentIndex.value / deckCards.value.length) * 100)
})

const swipeIntent = computed(() => {
  const dx = touchDeltaX.value
  const dy = touchDeltaY.value
  const absX = Math.abs(dx)
  const absY = Math.abs(dy)
  if (absX < 30 && absY < 30) return null

  if (absX > absY) {
    return dx > 0 ? 'star' : 'skip'
  } else {
    return dy < 0 ? 'keep' : 'snooze'
  }
})

const cardTransformStyle = computed(() => {
  if (flyOutDirection.value === 'right') {
    return {
      transform: 'translate3d(120vw, 0, 0) rotate(25deg)',
      transition: 'transform 0.28s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.25s',
      opacity: 0,
    }
  }
  if (flyOutDirection.value === 'left') {
    return {
      transform: 'translate3d(-120vw, 0, 0) rotate(-25deg)',
      transition: 'transform 0.28s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.25s',
      opacity: 0,
    }
  }
  if (flyOutDirection.value === 'up') {
    return {
      transform: 'translate3d(0, -90vh, 0)',
      transition: 'transform 0.28s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.25s',
      opacity: 0,
    }
  }
  if (flyOutDirection.value === 'down') {
    return {
      transform: 'translate3d(0, 90vh, 0)',
      transition: 'transform 0.28s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.25s',
      opacity: 0,
    }
  }
  if (isSwiping.value) {
    const rot = Math.min(20, Math.max(-20, touchDeltaX.value * 0.08))
    return {
      transform: `translate3d(${touchDeltaX.value}px, ${touchDeltaY.value * 0.7}px, 0) rotate(${rot}deg)`,
      transition: 'none',
      userSelect: 'none' as const,
    }
  }
  return {
    transform: 'translate3d(0, 0, 0) rotate(0deg)',
    transition: 'transform 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
  }
})

function triggerHaptic() {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    try {
      navigator.vibrate(15)
    } catch {}
  }
}

function onTouchStart(e: TouchEvent) {
  if (actionInProgress.value || completed.value || !currentCard.value) return
  const t = e.touches[0]
  touchStartX = t.clientX
  touchStartY = t.clientY
  touchDeltaX.value = 0
  touchDeltaY.value = 0
  isSwiping.value = true
}

function onTouchMove(e: TouchEvent) {
  if (!isSwiping.value || actionInProgress.value) return
  const t = e.touches[0]
  const dx = t.clientX - touchStartX
  const dy = t.clientY - touchStartY
  touchDeltaX.value = dx
  touchDeltaY.value = dy

  // Prevent vertical page jitter when swiping horizontally
  if (Math.abs(dx) > 15 && e.cancelable) {
    e.preventDefault()
  }
}

async function onTouchEnd() {
  if (!isSwiping.value || actionInProgress.value) return
  isSwiping.value = false
  const dx = touchDeltaX.value
  const dy = touchDeltaY.value
  const absX = Math.abs(dx)
  const absY = Math.abs(dy)
  const THRESHOLD = 65

  if (absX > absY && absX > THRESHOLD) {
    triggerHaptic()
    if (dx > 0) {
      flyOutDirection.value = 'right'
      await completeSwipe('swipe_star')
    } else {
      flyOutDirection.value = 'left'
      await completeSwipe('swipe_down')
    }
  } else if (absY >= absX && absY > THRESHOLD) {
    triggerHaptic()
    if (dy < 0) {
      flyOutDirection.value = 'up'
      await completeSwipe('swipe_up')
    } else {
      flyOutDirection.value = 'down'
      await completeSwipe('snooze')
    }
  } else {
    touchDeltaX.value = 0
    touchDeltaY.value = 0
  }
}

async function completeSwipe(action: 'swipe_up' | 'swipe_down' | 'swipe_star' | 'snooze') {
  await new Promise((r) => setTimeout(r, 200))
  flyOutDirection.value = null
  touchDeltaX.value = 0
  touchDeltaY.value = 0
  await handleAction(action)
}

async function fetchDeck() {
  loading.value = true
  completed.value = false
  currentIndex.value = 0
  summaryStats.value = { kept: 0, starred: 0, skipped: 0, snoozed: 0 }
  try {
    const res = await getDailyDeck(10)
    deckCards.value = res.items || []
  } catch (err) {
    console.error('Failed to load daily review deck', err)
    deckCards.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => ui.showDailyDeckModal,
  (open) => {
    if (open) {
      void fetchDeck()
    }
  }
)

async function handleAction(action: 'swipe_up' | 'swipe_down' | 'swipe_star' | 'snooze') {
  if (!currentCard.value || actionInProgress.value) return
  actionInProgress.value = true
  const item = currentCard.value
  const itemId = String(item.id)

  try {
    await submitSwipeAction(itemId, action)
    if (action === 'swipe_up') summaryStats.value.kept++
    else if (action === 'swipe_star') summaryStats.value.starred++
    else if (action === 'swipe_down') summaryStats.value.skipped++
    else if (action === 'snooze') summaryStats.value.snoozed++

    // Move to next
    if (currentIndex.value + 1 < deckCards.value.length) {
      currentIndex.value++
    } else {
      completed.value = true
      void itemsStore.refreshAll()
    }
  } catch (err) {
    console.error('Failed to record swipe action', err)
  } finally {
    actionInProgress.value = false
  }
}

function openReader(card: DeckCard) {
  ui.activeItem = card
  ui.detailTab = 'analysis'
  ui.showDailyDeckModal = false
}

function handleKeydown(e: KeyboardEvent) {
  if (!ui.showDailyDeckModal || completed.value || !currentCard.value) return
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return

  if (e.key === 's' || e.key === 'S') {
    e.preventDefault()
    void handleAction('snooze')
  } else if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowDown') {
    e.preventDefault()
    void handleAction('swipe_down')
  } else if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowUp') {
    e.preventDefault()
    void handleAction('swipe_up')
  } else if (e.key === 'l' || e.key === 'L' || e.key === 'ArrowRight') {
    e.preventDefault()
    void handleAction('swipe_star')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Dialog :open="ui.showDailyDeckModal" @update:open="(v) => (ui.showDailyDeckModal = v)">
    <DialogContent class="max-w-2xl overflow-hidden p-0 sm:rounded-2xl max-h-[92dvh] flex flex-col">
      <!-- Header with Progress & iOS Drag Handle -->
      <div class="border-b border-border bg-card/60 px-5 py-3.5 backdrop-blur-md shrink-0">
        <!-- iOS Drag pill (mobile indicator) -->
        <div class="mx-auto mb-2 h-1 w-10 rounded-full bg-muted-foreground/30 sm:hidden" />

        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <div class="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Sparkles class="size-4" />
            </div>
            <div>
              <DialogTitle class="text-lg font-semibold text-foreground">
                每日回顧
              </DialogTitle>
              <DialogDescription class="text-sm text-muted-foreground">
                還沒讀的收藏，加上值得再看一次的舊收藏。
              </DialogDescription>
            </div>
          </div>

          <div v-if="deckCards.length && !completed" class="flex items-center gap-2">
            <span class="text-sm font-mono font-semibold text-primary">
              {{ currentIndex + 1 }} / {{ deckCards.length }}
            </span>
          </div>
        </div>

        <!-- Progress bar -->
        <div v-if="deckCards.length && !completed" class="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            class="h-full bg-primary transition-all duration-300 ease-out"
            :style="{ width: `${progressPercent}%` }"
          />
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <Loader2 class="size-8 animate-spin text-primary" />
        <p class="mt-3 text-sm font-medium">正在準備今天的回顧…</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="!deckCards.length" class="flex flex-col items-center justify-center px-6 py-16 text-center">
        <CheckCircle2 class="size-10 text-green-500" />
        <h3 class="mt-3 text-sm font-semibold text-foreground">今天沒有要回顧的收藏</h3>
        <p class="mt-1 text-sm text-muted-foreground">有新的未讀收藏後再回來看。</p>
        <Button class="mt-4" size="sm" @click="ui.showDailyDeckModal = false">關閉</Button>
      </div>

      <!-- Completed State -->
      <div v-else-if="completed" class="px-6 py-10 text-center overflow-y-auto">
        <div class="mx-auto flex size-12 items-center justify-center rounded-2xl bg-green-500/10 text-green-500">
          <CheckCircle2 class="size-6" />
        </div>
        <h3 class="mt-4 text-base font-bold text-foreground">今天的回顧完成了</h3>
        <p class="mt-1 text-sm text-muted-foreground">你的選擇已記錄，之後的推薦會依此調整。</p>

        <!-- Stats summary chips -->
        <div class="mt-6 flex flex-wrap justify-center gap-2 text-sm">
          <span class="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 px-3 py-1.5 font-medium text-primary">
            <Star class="size-4" />加星：{{ summaryStats.starred }}
          </span>
          <span class="inline-flex items-center gap-1.5 rounded-lg bg-green-500/10 px-3 py-1.5 font-medium text-green-600 dark:text-green-400">
            <ThumbsUp class="size-4" />保留：{{ summaryStats.kept }}
          </span>
          <span class="inline-flex items-center gap-1.5 rounded-lg bg-muted px-3 py-1.5 font-medium text-muted-foreground">
            <Clock class="size-4" />稍後再看：{{ summaryStats.snoozed }}
          </span>
          <span class="inline-flex items-center gap-1.5 rounded-lg bg-red-500/10 px-3 py-1.5 font-medium text-red-600 dark:text-red-400">
            <ThumbsDown class="size-4" />略過：{{ summaryStats.skipped }}
          </span>
        </div>

        <div class="mt-8">
          <Button size="sm" @click="ui.showDailyDeckModal = false">回到收藏</Button>
        </div>
      </div>

      <!-- Active Card View with Touch Swipe Handlers -->
      <div
        v-else-if="currentCard"
        class="relative flex flex-1 flex-col overflow-y-auto p-5 sm:p-6 touch-pan-y"
        :style="cardTransformStyle"
        @touchstart.passive="onTouchStart"
        @touchmove="onTouchMove"
        @touchend="onTouchEnd"
      >
        <!-- Floating Swipe Intent Indicator (Appears when dragging on iPhone) -->
        <div
          v-if="swipeIntent"
          class="pointer-events-none absolute inset-x-6 top-8 z-20 flex justify-center transition-all duration-150 animate-in fade-in-50 zoom-in-95"
        >
          <div
            v-if="swipeIntent === 'star'"
            class="flex items-center gap-1.5 rounded-2xl border-2 border-amber-500 bg-amber-500/25 px-4 py-2 font-bold text-amber-500 backdrop-blur-md shadow-lg"
          >
            <Star class="size-5 fill-amber-500" />
            <span class="text-sm">加星（右滑）</span>
          </div>
          <div
            v-else-if="swipeIntent === 'skip'"
            class="flex items-center gap-1.5 rounded-2xl border-2 border-red-500 bg-red-500/25 px-4 py-2 font-bold text-red-500 backdrop-blur-md shadow-lg"
          >
            <ThumbsDown class="size-5" />
            <span class="text-sm">略過（左滑）</span>
          </div>
          <div
            v-else-if="swipeIntent === 'keep'"
            class="flex items-center gap-1.5 rounded-2xl border-2 border-green-500 bg-green-500/25 px-4 py-2 font-bold text-green-500 backdrop-blur-md shadow-lg"
          >
            <ThumbsUp class="size-5" />
            <span class="text-sm">保留（上滑）</span>
          </div>
          <div
            v-else-if="swipeIntent === 'snooze'"
            class="flex items-center gap-1.5 rounded-2xl border-2 border-muted-foreground bg-muted/90 px-4 py-2 font-bold text-foreground backdrop-blur-md shadow-lg"
          >
            <Clock class="size-5" />
            <span class="text-sm">稍後再看（下滑）</span>
          </div>
        </div>

        <!-- Top tags & Badges -->
        <div class="flex flex-wrap items-center gap-1.5">
          <Badge v-if="currentCard.is_resurfaced" variant="secondary" class="bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <History class="mr-1 size-3" />
            {{ currentCard.resurfaced_reason || '再看一次' }}
          </Badge>

          <Badge v-else-if="currentCard.is_exploration" variant="secondary" class="bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
            <Compass class="mr-1 size-3" />
            探索（平常少看的主題）
          </Badge>

          <Badge v-else variant="secondary" class="bg-primary/10 text-primary">
            <Sparkles class="mr-1 size-3" />
            還沒讀
          </Badge>

          <Badge variant="outline" class="text-xs">
            {{ currentCard.category_name || '收件匣' }}
          </Badge>

          <span class="ml-auto text-2xs text-muted-foreground font-mono">
            {{ (currentCard.created_at || '').substring(0, 10) }}
          </span>
        </div>

        <!-- Title & URL -->
        <h2 class="mt-3 text-base sm:text-lg font-bold leading-snug text-foreground line-clamp-2">
          {{ currentCard.title_l1 }}
        </h2>

        <div class="mt-1 flex items-center gap-1 text-2xs text-muted-foreground">
          <span class="truncate max-w-sm">{{ currentCard.author || currentCard.url }}</span>
          <a
            v-if="currentCard.url"
            :href="currentCard.url"
            target="_blank"
            rel="noopener noreferrer"
            class="text-subtle-foreground hover:text-foreground inline-flex items-center"
            title="開啟原始連結"
            @click.stop
          >
            <ExternalLink class="size-3" />
          </a>
        </div>

        <!-- Summary -->
        <div class="mt-3 rounded-xl border border-hairline bg-muted/40 p-3.5 text-sm leading-relaxed text-foreground/90">
          <p class="line-clamp-4">
            {{ currentCard.summary_l1 || '（沒有摘要）' }}
          </p>
        </div>

        <!-- Reasons (if any) -->
        <div v-if="currentCard.reasons && currentCard.reasons.length" class="mt-2.5 flex flex-wrap gap-1">
          <span
            v-for="r in currentCard.reasons"
            :key="r"
            class="rounded-md bg-accent px-2 py-0.5 text-3xs font-medium text-muted-foreground"
          >
            {{ r }}
          </span>
        </div>

        <!-- Tech Tags -->
        <div v-if="currentCard.tech_tags && currentCard.tech_tags.length" class="mt-2.5 flex flex-wrap gap-1">
          <span
            v-for="tag in currentCard.tech_tags"
            :key="tag"
            class="rounded bg-muted px-1.5 py-0.5 text-2xs text-subtle-foreground font-mono"
          >
            #{{ tag }}
          </span>
        </div>

        <!-- Open Reader Link -->
        <div class="mt-3 flex justify-end">
          <button
            class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline cursor-pointer"
            @click="openReader(currentCard)"
          >
            <BookOpen class="size-3.5" />
            開啟完整內容
          </button>
        </div>

        <!-- Action Bar (4-button decision for desktop / touch fallback) -->
        <div class="mt-auto pt-4 grid grid-cols-4 gap-2 border-t border-border">
          <!-- Snooze -->
          <button
            class="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card p-2 sm:p-2.5 transition active:scale-95 hover:bg-accent cursor-pointer group"
            :disabled="actionInProgress"
            @click="handleAction('snooze')"
          >
            <Clock class="size-4 text-muted-foreground group-hover:text-foreground transition-colors" />
            <span class="text-sm font-semibold text-foreground">稍後</span>
            <kbd class="hidden sm:inline-block font-mono text-3xs text-muted-foreground">S</kbd>
          </button>

          <!-- Swipe Down: Pass -->
          <button
            class="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card p-2 sm:p-2.5 transition active:scale-95 hover:bg-red-500/10 hover:border-red-500/30 cursor-pointer group"
            :disabled="actionInProgress"
            @click="handleAction('swipe_down')"
          >
            <ThumbsDown class="size-4 text-muted-foreground group-hover:text-red-500 transition-colors" />
            <span class="text-sm font-semibold text-foreground group-hover:text-red-500">略過</span>
            <kbd class="hidden sm:inline-block font-mono text-3xs text-muted-foreground">J / ↓</kbd>
          </button>

          <!-- Swipe Up: Keep -->
          <button
            class="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card p-2 sm:p-2.5 transition active:scale-95 hover:bg-green-500/10 hover:border-green-500/30 cursor-pointer group"
            :disabled="actionInProgress"
            @click="handleAction('swipe_up')"
          >
            <ThumbsUp class="size-4 text-muted-foreground group-hover:text-green-500 transition-colors" />
            <span class="text-sm font-semibold text-foreground group-hover:text-green-500">保留</span>
            <kbd class="hidden sm:inline-block font-mono text-3xs text-muted-foreground">K / ↑</kbd>
          </button>

          <!-- Swipe Star: Star -->
          <button
            class="flex flex-col items-center justify-center gap-1 rounded-xl border border-primary/30 bg-primary/5 p-2 sm:p-2.5 transition active:scale-95 hover:bg-primary/15 cursor-pointer group"
            :disabled="actionInProgress"
            @click="handleAction('swipe_star')"
          >
            <Star class="size-4 text-amber-500 fill-amber-500 transition-transform group-hover:scale-110" />
            <span class="text-sm font-semibold text-primary">加星</span>
            <kbd class="hidden sm:inline-block font-mono text-3xs text-primary/70">L / →</kbd>
          </button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
