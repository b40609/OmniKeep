<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { coverFit, coverFocus, coverRetryDelay, isIconSized, itemKind, sourceName, usableCover } from '@/lib/wall'

/**
 * An item's cover, filling a 16:9 frame edge to edge. `card` and `thumb` fall back
 * to the kind icon (plus the source name on a card) when there is no usable image;
 * `hero` renders nothing at all, so the reader simply has no cover.
 */
const props = defineProps<{ item: Item; variant?: 'card' | 'thumb' | 'hero' }>()

const src = computed(() => usableCover(props.item.cover_image))
const failed = ref(false)
const attempt = ref(0)
/** Tall images keep their top edge in view; known only once the image has loaded. */
const focus = ref<'top' | 'center'>('center')
let retryTimer: ReturnType<typeof setTimeout> | undefined

watch(src, () => {
  clearTimeout(retryTimer)
  failed.value = false
  attempt.value = 0
  focus.value = 'center'
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

function onLoad(event: Event) {
  const image = event.target as HTMLImageElement
  // A favicon or tracking pixel that slipped through loads fine but is not a cover.
  if (isIconSized(image.naturalWidth, image.naturalHeight)) failed.value = true
  else focus.value = coverFocus(image.naturalWidth, image.naturalHeight)
}
</script>

<template>
  <div
    v-if="showImage || variant !== 'hero'"
    class="item-cover"
    :class="{
      'item-cover--thumb': variant === 'thumb',
      'item-cover--hero': variant === 'hero',
      'item-cover--image': showImage,
      'item-cover--pad': showImage && coverFit(src) === 'pad',
    }"
  >
    <img
      v-if="showImage"
      :key="attempt"
      :src="src"
      :class="{ 'item-cover__top': focus === 'top' }"
      alt=""
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      draggable="false"
      @load="onLoad"
      @error="onError"
    />
    <div v-else class="item-cover__fallback" aria-hidden="true">
      <KindIcon :kind="itemKind(item)" />
      <span v-if="variant !== 'thumb'">{{ sourceName(item) }}</span>
    </div>
  </div>
</template>
