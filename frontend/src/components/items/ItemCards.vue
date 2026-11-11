<script setup lang="ts">
import { computed } from 'vue'
import { Star } from 'lucide-vue-next'
import ItemActions from './ItemActions.vue'
import ItemCover from './ItemCover.vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime } from '@/lib/format'
import { itemKind, splitTitle } from '@/lib/wall'
import { useUiStore } from '@/stores/ui'

/** One cell of the cover wall: cover, name, what it is (when the title says), one line of meta. */
const props = defineProps<{ item: Item }>()
const ui = useUiStore()

const title = computed(() => splitTitle(props.item.title_l1))
// The ring marks the open item, or where J/K currently is while nothing is open.
const selected = computed(() => (ui.activeItem ? ui.activeItem.id === props.item.id : ui.cursorId === props.item.id))

function open() {
  ui.cursorId = props.item.id
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="cover-card cover-host"
    :class="{ 'is-read': !!item.is_read, 'is-cursor': selected }"
    :data-item-id="item.id"
  >
    <ItemCover :item="item" variant="card" />
    <h3 class="cover-card__title">
      <button type="button" class="cover-card__open" :aria-pressed="ui.activeItem?.id === item.id" @click="open">
        <span class="title-clamp">
          <span v-if="!item.is_read" class="unread-dot" aria-hidden="true" /><span v-if="!item.is_read" class="sr-only">未封存：</span>{{ title.name }}
        </span>
      </button>
    </h3>
    <p v-if="title.detail" class="cover-card__detail">{{ title.detail }}</p>
    <div class="item-meta cover-card__meta">
      <KindIcon :kind="itemKind(item)" />
      <span class="item-meta__clip" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
      <span class="item-meta__sep" aria-hidden="true" />
      <time>{{ formatRelativeTime(item.created_at) }}</time>
      <!-- Starred shows at rest; the buttons take its place on hover, focus and touch screens -->
      <Star v-if="item.is_starred" class="cover-card__flag fill-current" role="img" aria-label="已加星" />
      <ItemActions :item="item" compact class="cover-card__acts" />
    </div>
  </article>
</template>
