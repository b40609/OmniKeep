<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'

/** Slim reading progress bar; sticks to the top of the reader scroll area. */
const progress = ref(0)
let container: HTMLElement | null = null

function update() {
  if (!container) return
  const max = container.scrollHeight - container.clientHeight
  progress.value = max > 0 ? Math.min(100, (container.scrollTop / max) * 100) : 0
}

onMounted(() => {
  container = document.querySelector('[data-reader-scroll]')
  container?.addEventListener('scroll', update, { passive: true })
  update()
})
onBeforeUnmount(() => container?.removeEventListener('scroll', update))
</script>

<template>
  <div class="sticky top-0 z-10 h-0.5 w-full" aria-hidden="true">
    <div
      class="h-full origin-left bg-primary transition-transform duration-100 ease-out"
      :style="{ transform: `scaleX(${progress / 100})` }"
    />
  </div>
  <div
    class="sr-only"
    role="progressbar"
    :aria-valuenow="Math.round(progress)"
    aria-label="閱讀進度"
  />
</template>
