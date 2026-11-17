<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

/**
 * The outline beside a full-page article: every section of the reading column (its h2s, the analysis's
 * own headings and its folded parts), the one being read lit, a click scrolls there (and opens a folded part).
 */
const props = defineProps<{ root: HTMLElement | null; version: unknown }>()

interface Entry { el: HTMLElement; text: string; sub: boolean }
const entries = ref<Entry[]>([])
const active = ref(0)
let scroller: HTMLElement | null = null
let mo: MutationObserver | null = null
let queued = 0

function label(el: HTMLElement): string {
  const t = (el.textContent || '').replace(/#\s*$/, '').trim()
  return t.split(/[：:]/)[0].trim().slice(0, 28)
}

function collect() {
  const root = props.root
  if (!root) { entries.value = []; return }
  const found: Entry[] = []
  root.querySelectorAll<HTMLElement>(':scope > section h2, :scope > section .prose-reader > details > summary').forEach((el) => {
    if (el.closest('nav') || el.getClientRects().length === 0) return // e.g. old mermaid parts the CSS hides
    const sub = !!el.closest('.prose-reader')
    const text = label(el)
    if (text) found.push({ el, text, sub })
  })
  entries.value = found
  onScroll()
}

function onScroll() {
  if (!scroller || !entries.value.length) return
  const top = scroller.getBoundingClientRect().top + 96
  let k = 0
  entries.value.forEach((e, i) => { if (e.el.getBoundingClientRect().top <= top) k = i })
  // at the very end the last section counts as read even if its heading never reaches the top
  if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4) k = entries.value.length - 1
  active.value = k
}

function go(e: Entry) {
  const d = e.el.closest('details')
  if (d && !d.open) d.open = true
  e.el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function bind() {
  scroller?.removeEventListener('scroll', onScroll)
  mo?.disconnect()
  scroller = props.root?.closest<HTMLElement>('[data-reader-scroll]') || null
  scroller?.addEventListener('scroll', onScroll, { passive: true })
  if (props.root) {
    // the analysis renders after the item loads, and sections come and go with it
    mo = new MutationObserver(() => { if (!queued) queued = requestAnimationFrame(() => { queued = 0; collect() }) })
    mo.observe(props.root, { childList: true, subtree: true })
  }
  collect()
}

onMounted(bind)
watch(() => [props.root, props.version], async () => { await nextTick(); bind() })
onBeforeUnmount(() => { scroller?.removeEventListener('scroll', onScroll); mo?.disconnect(); cancelAnimationFrame(queued) })
</script>

<template>
  <nav v-if="entries.length >= 2" class="reader-outline" aria-label="本篇目錄">
    <p class="reader-outline__title">本篇目錄</p>
    <button
      v-for="(e, i) in entries"
      :key="i"
      type="button"
      class="reader-outline__item"
      :class="{ 'is-sub': e.sub, 'is-on': i === active }"
      :aria-current="i === active ? 'location' : undefined"
      @click="go(e)"
    >{{ e.text }}</button>
  </nav>
</template>
