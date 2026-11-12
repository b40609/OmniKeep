<script setup lang="ts">
import { computed, onUnmounted, ref, watch, type Component } from 'vue'
import { toast } from 'vue-sonner'
import { Clock, Compass, ExternalLink, RotateCw, Star, ThumbsDown, ThumbsUp, X } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { getSwipeDeck, recordSwipe, type DeckItem, type SwipeAction } from '@/lib/api'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

/**
 * Radar swipe deck — the PWA twin of Telegram /deck (same four verbs).
 * Want / skip / star are taste labels; later only re-queues the card for tomorrow.
 * Touch / pen / mouse: drag right 想看, left 略過, up 收藏, down 稍後.
 * Keyboard: → ← ↑ ↓ (or L H S Z), O opens the source.
 */
const ui = useUiStore()
const items = useItemsStore()

type Direction = 'right' | 'left' | 'up' | 'down'

const ACTIONS: { action: SwipeAction; dir: Direction; icon: Component; label: string; done: string; key: string; keys: string[] }[] = [
  { action: 'swipe_down', dir: 'left', icon: ThumbsDown, label: '略過', done: '已略過', key: '←', keys: ['ArrowLeft', 'h', 'H'] },
  { action: 'snooze', dir: 'down', icon: Clock, label: '稍後', done: '明天再出現', key: '↓', keys: ['ArrowDown', 'z', 'Z'] },
  { action: 'swipe_star', dir: 'up', icon: Star, label: '加星', done: '已加星', key: '↑', keys: ['ArrowUp', 's', 'S'] },
  { action: 'swipe_up', dir: 'right', icon: ThumbsUp, label: '想看', done: '已記錄想看', key: '→', keys: ['ArrowRight', 'l', 'L'] },
]
const byDir = Object.fromEntries(ACTIONS.map((a) => [a.dir, a])) as Record<Direction, (typeof ACTIONS)[number]>
const FLY: Record<Direction, [number, number]> = { right: [1, 0], left: [-1, 0], up: [0, -1], down: [0, 1] }

const THRESHOLD = 96 // px of drag that commits an action
const HINT_FROM = 24 // px of drag before the action label starts to show

const cards = ref<DeckItem[]>([])
const loading = ref(false)
const busy = ref(false)
const lastResult = ref('')
// Ids decided in this sitting: never shown again even if a refill races the write.
const decided = new Set<string>()
let changed = false

const current = computed(() => cards.value[0] ?? null)
const hasNext = computed(() => cards.value.length > 1)
const sourceUrl = computed(() => {
  const url = current.value?.url ?? ''
  return /^https?:\/\//i.test(url) ? url : ''
})

const reduceMotion = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/* ---------------- Loading ---------------- */

async function loadDeck() {
  loading.value = true
  try {
    const res = await getSwipeDeck(50)
    cards.value = res.items.filter((c) => !decided.has(String(c.id)))
  } catch (e) {
    toast.error('無法載入逐則篩選', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    loading.value = false
  }
}

/* ---------------- Drag gesture ---------------- */

const dx = ref(0)
const dy = ref(0)
const dragging = ref(false)
let startX = 0
let startY = 0
let pointerId: number | null = null

function directionOf(x: number, y: number, min: number): Direction | null {
  const ax = Math.abs(x)
  const ay = Math.abs(y)
  if (Math.max(ax, ay) < min) return null
  return ax >= ay ? (x > 0 ? 'right' : 'left') : (y > 0 ? 'down' : 'up')
}

const hint = computed(() => {
  const dir = directionOf(dx.value, dy.value, HINT_FROM)
  if (!dir) return null
  const dist = Math.max(Math.abs(dx.value), Math.abs(dy.value))
  return { ...byDir[dir], opacity: Math.min(1, (dist - HINT_FROM) / (THRESHOLD - HINT_FROM)) }
})

const cardStyle = computed(() => ({
  transform: `translate(${dx.value}px, ${dy.value}px) rotate(${dx.value * 0.05}deg)`,
  transition: dragging.value || reduceMotion ? 'none' : 'transform 220ms cubic-bezier(0.22, 1, 0.36, 1)',
}))

function onPointerDown(e: PointerEvent) {
  if (busy.value || !current.value || e.button !== 0) return
  if ((e.target as HTMLElement).closest('a, button')) return
  pointerId = e.pointerId
  startX = e.clientX
  startY = e.clientY
  dragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value || e.pointerId !== pointerId) return
  dx.value = e.clientX - startX
  dy.value = e.clientY - startY
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value || e.pointerId !== pointerId) return
  dragging.value = false
  pointerId = null
  const dir = directionOf(dx.value, dy.value, THRESHOLD)
  if (dir) commit(dir)
  else resetDrag()
}

function resetDrag() {
  dragging.value = false
  pointerId = null
  dx.value = 0
  dy.value = 0
}

/* ---------------- Decisions ---------------- */

async function commit(dir: Direction) {
  const card = current.value
  if (!card || busy.value) return
  const spec = byDir[dir]
  busy.value = true
  dx.value = FLY[dir][0] * 640
  dy.value = FLY[dir][1] * 640
  const flyOut = reduceMotion ? Promise.resolve() : new Promise((r) => setTimeout(r, 220))
  try {
    await Promise.all([recordSwipe(card.id, spec.action), flyOut])
    decided.add(String(card.id))
    changed = true
    cards.value = cards.value.filter((c) => c.id !== card.id)
    lastResult.value = spec.done
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    if (/unknown item/i.test(message)) {
      cards.value = cards.value.filter((c) => c.id !== card.id)
      toast.error('這則收藏已被刪除，跳到下一則')
    } else {
      toast.error('記錄失敗，這則已放回', { description: message })
    }
  } finally {
    resetDrag()
    busy.value = false
  }
  if (cards.value.length === 0) await loadDeck()
}

function openSource() {
  if (sourceUrl.value) window.open(sourceUrl.value, '_blank', 'noopener')
}

function onKeydown(e: KeyboardEvent) {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const spec = ACTIONS.find((a) => a.keys.includes(e.key))
  if (spec) {
    e.preventDefault()
    commit(spec.dir)
  } else if (e.key === 'o' || e.key === 'O') {
    e.preventDefault()
    openSource()
  }
}

watch(
  () => ui.showDeckModal,
  (open) => {
    if (open) {
      decided.clear()
      changed = false
      lastResult.value = ''
      resetDrag()
      window.addEventListener('keydown', onKeydown)
      loadDeck()
    } else {
      window.removeEventListener('keydown', onKeydown)
      // Swipes mark items read/starred; bring the main list and counters up to date.
      if (changed) items.refreshAll()
    }
  },
)
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Dialog :open="ui.showDeckModal" @update:open="(v) => (ui.showDeckModal = v)">
    <DialogContent
      :show-close="false"
      class="flex max-h-[100dvh] max-w-md flex-col gap-4 max-sm:h-[100dvh] max-sm:max-w-none max-sm:rounded-none max-sm:border-0 max-sm:pt-[max(1.5rem,env(safe-area-inset-top))] max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]"
    >
      <DialogHeader>
        <div class="flex items-center gap-2">
          <DialogTitle class="flex items-center gap-2">
            逐則篩選
            <span v-if="cards.length" class="rounded-md bg-muted px-1.5 py-0.5 font-mono text-2xs text-muted-foreground">剩 {{ cards.length }} 則</span>
          </DialogTitle>
          <!-- Full-screen on phones leaves no backdrop to tap, so closing needs a real button. -->
          <button
            class="ml-auto rounded-full bg-muted p-1.5 text-muted-foreground transition-all hover:bg-accent hover:text-foreground active:scale-90"
            aria-label="關閉"
            @click="ui.showDeckModal = false"
          >
            <X class="size-3.5" />
          </button>
        </div>
        <DialogDescription class="text-sm">
          想看、略過、加星會用來調整之後的推薦；選稍後的明天再出現，不列入。
        </DialogDescription>
      </DialogHeader>

      <!-- Card stack -->
      <div class="relative min-h-[22rem] flex-1">
        <div v-if="loading && !current" class="absolute inset-0 animate-pulse rounded-2xl border border-border bg-muted/40" />

        <div
          v-else-if="!current"
          class="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border p-6 text-center"
        >
          <p class="text-sm font-medium">探索找到的內容都看完了</p>
          <p class="text-sm text-muted-foreground">探索找到新內容後會出現在這裡。選了稍後的明天再出現。</p>
          <Button variant="secondary" size="sm" :disabled="loading" @click="loadDeck">
            <RotateCw class="size-3.5" /> 重新整理
          </Button>
        </div>

        <template v-else>
          <!-- Next card peeking out behind -->
          <div
            v-if="hasNext"
            class="absolute inset-0 translate-y-2 scale-[0.96] rounded-2xl border border-border bg-card opacity-60"
            aria-hidden="true"
          />

          <article
            :key="current.id"
            class="absolute inset-0 flex touch-none flex-col gap-3 overflow-hidden rounded-2xl border border-border bg-card p-5 text-card-foreground shadow-xl select-none"
            :class="busy ? 'cursor-default' : dragging ? 'cursor-grabbing' : 'cursor-grab'"
            :style="cardStyle"
            aria-roledescription="卡片"
            :aria-label="current.title_l1"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="resetDrag"
          >
            <div class="flex flex-wrap items-center gap-1.5 text-2xs">
              <span class="rounded-md bg-muted px-1.5 py-0.5 font-semibold uppercase text-muted-foreground">{{ current.source_type }}</span>
              <span v-if="current.category_name" class="rounded-md bg-primary-soft px-1.5 py-0.5 font-semibold text-primary-soft-foreground">{{ current.category_name }}</span>
              <span v-if="current.is_exploration" class="inline-flex items-center gap-1 rounded-md bg-info-soft px-1.5 py-0.5 font-semibold text-info"><Compass class="size-3" />探索</span>
            </div>

            <h3 class="line-clamp-3 text-lg leading-snug font-semibold tracking-tight">
              <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener" class="hover:text-primary hover:underline">{{ current.title_l1 }}</a>
              <template v-else>{{ current.title_l1 }}</template>
            </h3>

            <p class="line-clamp-6 text-sm leading-relaxed text-muted-foreground">{{ current.summary_l1 }}</p>

            <div v-if="current.reasons?.length" class="space-y-0.5 text-sm">
              <p class="font-semibold text-foreground">為什麼給你看：</p>
              <p v-for="r in current.reasons.slice(0, 3)" :key="r" class="text-muted-foreground">· {{ r }}</p>
            </div>

            <div v-if="current.tech_tags?.length" class="mt-auto flex flex-wrap gap-1.5">
              <span
                v-for="tag in current.tech_tags.slice(0, 4)"
                :key="tag"
                class="rounded-md border border-border/40 bg-muted/30 px-2 py-0.5 text-3xs text-muted-foreground/80"
              >#{{ tag }}</span>
            </div>

            <!-- Action preview while dragging -->
            <div
              v-if="hint"
              class="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl bg-background/70"
              :style="{ opacity: hint.opacity }"
              aria-hidden="true"
            >
              <span class="inline-flex items-center gap-2 rounded-xl border-2 border-foreground/70 px-4 py-2 text-2xl font-bold"><component :is="hint.icon" class="size-6" />{{ hint.label }}</span>
            </div>
          </article>
        </template>
      </div>

      <!-- Buttons: laid out to match swipe directions -->
      <div class="grid grid-cols-4 gap-2">
        <Button
          v-for="a in ACTIONS"
          :key="a.action"
          variant="secondary"
          class="h-auto flex-col gap-0.5 py-2"
          :disabled="!current || busy"
          :aria-label="`${a.label}（${a.key}）`"
          @click="commit(a.dir)"
        >
          <component :is="a.icon" class="size-5" />
          <span class="text-sm">{{ a.label }}</span>
          <kbd class="font-mono text-3xs text-subtle-foreground max-sm:hidden">{{ a.key }}</kbd>
        </Button>
      </div>

      <div class="flex items-center justify-between gap-2 text-2xs text-muted-foreground">
        <span aria-live="polite">{{ lastResult }}</span>
        <span class="flex items-center gap-2 max-sm:hidden">
          <button v-if="sourceUrl" class="inline-flex items-center gap-1 hover:text-foreground" @click="openSource">
            <ExternalLink class="size-3" /> 原文 <kbd class="font-mono">O</kbd>
          </button>
          <span>拖曳或方向鍵操作</span>
        </span>
      </div>
    </DialogContent>
  </Dialog>
</template>
