<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { coverRetryDelay, isIconSized, itemKind, sourceName, usableCover } from '@/lib/wall'

/**
 * An item's cover in a 16:9 frame. `card` and `thumb` fall back to the kind icon
 * (plus the source name on a card) when there is no usable image; `hero` renders
 * nothing at all, so the reader simply has no cover.
 */
const props = defineProps<{ item: Item; variant?: 'card' | 'thumb' | 'hero' }>()

const src = computed(() => usableCover(props.item.cover_image))
const failed = ref(false)
const attempt = ref(0)
let retryTimer: ReturnType<typeof setTimeout> | undefined

watch(src, () => {
  clearTimeout(retryTimer)
  failed.value = false
  attempt.value = 0
})
onBeforeUnmount(() => clearTimeout(retryTimer))

const showImage = computed(() => !!src.value && !failed.value)

/** Show the fallback at once; a rate-limited host gets asked again after a pause. */
function onError() {
  failed.value = true
  const delay = coverRetryDelay(src.value, attempt.value)
  if (delay == null) return
  retryTimer = setTimeout(() => {
    attempt.value++
    failed.value = false
  }, delay + Math.random() * 2_000)
}

/** A favicon or tracking pixel that slipped through loads fine but is not a cover. */
function checkSize(event: Event) {
  const image = event.target as HTMLImageElement
  if (isIconSized(image.naturalWidth, image.naturalHeight)) failed.value = true
}
</script>

<template>
  <div
    v-if="showImage || variant !== 'hero'"
    class="item-cover"
    :class="{ 'item-cover--thumb': variant === 'thumb', 'item-cover--hero': variant === 'hero' }"
  >
    <img
      v-if="showImage"
      :key="attempt"
      :src="src"
      alt=""
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      draggable="false"
      @load="checkSize"
      @error="onError"
    />
    <div v-else class="item-cover__fallback" aria-hidden="true">
      <KindIcon :kind="itemKind(item)" />
      <span v-if="variant !== 'thumb'">{{ sourceName(item) }}</span>
    </div>
  </div>
</template>
