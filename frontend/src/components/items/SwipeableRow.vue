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

const THRESHOLD = 88 // px to trigger
const MAX = 132 // px clamp

const starVisible = computed(() => dx.value > 12)
const archiveVisible = computed(() => dx.value < -12)

function onTouchStart(e: TouchEvent) {
  if (e.touches.length !== 1) return
  startX = e.touches[0].clientX
  startY = e.touches[0].clientY
  horizontal = null
  dragging.value = true
}
function onTouchMove(e: TouchEvent) {
  if (!dragging.value) return
  const t = e.touches[0]
  const mx = t.clientX - startX
  const my = t.clientY - startY
  if (horizontal === null) {
    if (Math.abs(mx) < 8 && Math.abs(my) < 8) return
    horizontal = Math.abs(mx) > Math.abs(my)
  }
  if (!horizontal) return
  e.preventDefault()
  dx.value = Math.max(-MAX, Math.min(MAX, mx * 0.85))
}
function onTouchEnd() {
  if (!dragging.value) return
  dragging.value = false
  if (dx.value >= THRESHOLD) toggleStar(props.item)
  else if (dx.value <= -THRESHOLD) toggleRead(props.item)
  dx.value = 0
}
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- Action hints behind the row -->
    <div
      class="absolute inset-y-0 left-0 flex w-32 items-center justify-start gap-2 bg-warning/15 pl-5 text-warning transition-opacity duration-150"
      :class="starVisible ? 'opacity-100' : 'opacity-0'"
      aria-hidden="true"
    >
      <Star class="size-5" :class="dx >= THRESHOLD ? 'fill-warning' : ''" />
      <span class="text-xs font-semibold">星標</span>
    </div>
    <div
      class="absolute inset-y-0 right-0 flex w-32 items-center justify-end gap-2 bg-success/15 pr-5 text-success transition-opacity duration-150"
      :class="archiveVisible ? 'opacity-100' : 'opacity-0'"
      aria-hidden="true"
    >
      <span class="text-xs font-semibold">封存</span>
      <Archive class="size-5" />
    </div>

    <!-- The row, translated by touch -->
    <div
      :style="{ transform: `translateX(${dx}px)`, transition: dragging ? 'none' : 'transform 260ms cubic-bezier(0.22, 1, 0.36, 1)' }"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
      @touchcancel="onTouchEnd"
    >
      <slot />
    </div>
  </div>
</template>
