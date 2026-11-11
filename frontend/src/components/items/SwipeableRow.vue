<script setup lang="ts">
import { ref, computed } from 'vue'
import { Star, Archive } from 'lucide-vue-next'
import type { Item } from '@/lib/api'
import { useMutations } from '@/composables/useMutations'

/**
 * Mobile swipe actions: swipe right → star (amber), swipe left → archive
 * (green). Springs back on release; triggers past a distance threshold.
 */
const props = defineProps<{ item: Item }>()
const { toggleStar, toggleRead } = useMutations()

const dx = ref(0)
const dragging = ref(false)

let startX = 0
let startY = 0
let horizontal: boolean | null = null
let hasVibrated = false

const THRESHOLD = 88 // px to trigger
const MAX = 132 // px clamp

const starVisible = computed(() => dx.value > 12)
const archiveVisible = computed(() => dx.value < -12)

function triggerHaptic() {
  if (typeof window !== 'undefined' && typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    try {
      navigator.vibrate(12)
    } catch {}
  }
}

function onTouchStart(e: TouchEvent) {
  onTouchCancel()
  if (e.touches.length !== 1) return
  if ((e.target as HTMLElement).closest('button, a, input, select, [role="menuitem"]')) return
  startX = e.touches[0].clientX
  startY = e.touches[0].clientY
  horizontal = null
  dragging.value = true
  hasVibrated = false
}

function onTouchMove(e: TouchEvent) {
  if (!dragging.value) return
  if (e.touches.length !== 1) return onTouchCancel()
  const t = e.touches[0]
  const mx = t.clientX - startX
  const my = t.clientY - startY
  if (horizontal === null) {
    if (Math.abs(mx) < 8 && Math.abs(my) < 8) return
    horizontal = Math.abs(mx) > Math.abs(my)
  }
  if (!horizontal) return
  e.preventDefault()
  const newDx = Math.max(-MAX, Math.min(MAX, mx * 0.85))
  dx.value = newDx
  if (Math.abs(newDx) >= THRESHOLD && !hasVibrated) {
    triggerHaptic()
    hasVibrated = true
  } else if (Math.abs(newDx) < THRESHOLD) {
    hasVibrated = false
  }
}

function onTouchEnd() {
  if (!dragging.value) return
  dragging.value = false
  if (dx.value >= THRESHOLD) toggleStar(props.item)
  else if (dx.value <= -THRESHOLD) toggleRead(props.item)
  dx.value = 0
  hasVibrated = false
}

function onTouchCancel() {
  dragging.value = false
  horizontal = null
  dx.value = 0
  hasVibrated = false
}
</script>

<template>
  <div class="relative overflow-hidden select-none">
    <!-- Action hints behind the row -->
    <div
      class="absolute inset-y-0 left-0 flex w-36 items-center justify-start gap-2.5 bg-warning/15 pl-5 text-warning transition-all duration-200"
      :class="[
        starVisible ? 'opacity-100' : 'opacity-0',
        dx >= THRESHOLD ? 'bg-warning/25 text-amber-500 font-bold' : '',
      ]"
      aria-hidden="true"
    >
      <Star
        class="size-5 transition-transform duration-200"
        :class="dx >= THRESHOLD ? 'fill-warning scale-125' : 'scale-100'"
      />
      <span class="text-xs font-semibold">{{ dx >= THRESHOLD ? '放開加星' : '加星' }}</span>
    </div>
    <div
      class="absolute inset-y-0 right-0 flex w-36 items-center justify-end gap-2.5 bg-success/15 pr-5 text-success transition-all duration-200"
      :class="[
        archiveVisible ? 'opacity-100' : 'opacity-0',
        dx <= -THRESHOLD ? 'bg-success/25 text-emerald-500 font-bold' : '',
      ]"
      aria-hidden="true"
    >
      <span class="text-xs font-semibold">{{ dx <= -THRESHOLD ? '放開封存' : '封存' }}</span>
      <Archive
        class="size-5 transition-transform duration-200"
        :class="dx <= -THRESHOLD ? 'scale-125' : 'scale-100'"
      />
    </div>

    <!-- The row, translated by touch with spring curve -->
    <div
      class="swipe-content"
      :style="{
        transform: `translateX(${dx}px)`,
        transition: dragging ? 'none' : 'transform 260ms cubic-bezier(0.22, 1, 0.36, 1)',
      }"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
      @touchcancel="onTouchCancel"
    >
      <slot />
    </div>
  </div>
</template>
