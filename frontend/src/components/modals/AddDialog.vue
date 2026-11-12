<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { FileText, Loader2, Paperclip, X } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useMediaQuery } from '@vueuse/core'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Select from '@/components/ui/select/Select.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import * as api from '@/lib/api'
import type { Item } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useExperimentsStore } from '@/stores/experiments'
import { WATCH_CATEGORIES } from '@/lib/experiments'
import { IMPORT_EXTENSIONS, describePlan, explainFailure, isPastedLinks, planAdd, submitLabel } from '@/lib/addInput'

/**
 * 新增: the one panel for adding things. What is typed, pasted or dropped decides
 * what happens (lib/addInput.ts), and the line under the box says so before
 * anything is sent. A bookmark file goes on to the import dialog, which keeps
 * its own options and logic.
 */
const ui = useUiStore()
const itemsStore = useItemsStore()
const experiments = useExperimentsStore()

const AUTO = 'auto'

const area = ref<HTMLTextAreaElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
const text = ref('')
const file = shallowRef<File | null>(null)
const linksOnly = ref(false)
const asNote = ref(false)
const category = ref(AUTO)
const error = ref('')
const progress = ref('')
const submitting = ref(false)
const dragDepth = ref(0)
/** A phone cannot drag a file in, so the box does not suggest it there. */
const canDrag = useMediaQuery('(min-width: 640px)')

/** What the text is on its own, before either switch: it decides which switch is offered. */
const natural = computed(() => planAdd(text.value))
const plan = computed(() => planAdd(text.value, file.value, { linksOnly: linksOnly.value, asNote: asNote.value }))
const outcome = computed(() => describePlan(plan.value))
const busy = computed(() => submitting.value || ui.isIngesting)
const canSubmit = computed(() => !busy.value && plan.value.kind !== 'empty' && plan.value.kind !== 'unsupported')

const categoryOptions = computed(() => [
  { value: AUTO, label: 'AI 自動分類' },
  ...itemsStore.categories
    .filter((c) => experiments.flags.watch || !WATCH_CATEGORIES.includes(c.name))
    .map((c) => ({ value: c.name, label: c.name === 'Inbox' ? '收件匣' : c.name })),
])

// Opening keeps a draft that was not sent; text handed over (a paste on the page) is added to it.
watch(
  () => ui.showAddModal,
  (open) => {
    if (!open) return
    const handed = ui.addDraft.trim()
    ui.addDraft = ''
    if (handed) text.value = text.value.trim() ? `${text.value.trimEnd()}\n${handed}` : handed
    error.value = ''
    progress.value = ''
    dragDepth.value = 0
  },
)
// A switch belongs to the text it was set for.
watch(() => natural.value.kind, () => {
  linksOnly.value = false
  asNote.value = false
})

function close() {
  ui.showAddModal = false
}

/** Shown when the server kept the item without analysis because no AI is connected. */
const NOT_ANALYSED_HINT = '還沒有接上 AI，先存下原文。接上之後會自動補分析。'

function reason(e: unknown): string {
  return explainFailure((e as Error)?.message)
}

async function submit() {
  const current = plan.value
  if (!canSubmit.value || current.kind === 'empty' || current.kind === 'unsupported') return
  error.value = ''
  if (current.kind === 'file') {
    const chosen = file.value
    file.value = null
    close()
    ui.openImport('file', chosen)
    return
  }
  submitting.value = true
  ui.isIngesting = true
  try {
    if (current.kind === 'note') await saveNote(text.value.trim())
    else await saveLinks(current.urls)
  } finally {
    submitting.value = false
    ui.isIngesting = false
    progress.value = ''
    // Still open means it failed: the box was disabled while sending, so give it the caret back.
    if (ui.showAddModal) void nextTick(() => area.value?.focus())
  }
}

async function saveNote(content: string) {
  let item: Item | undefined
  try {
    const data = await api.ingest(content, { category: category.value === AUTO ? null : category.value, asNote: true })
    if (!data.success) throw new Error(data.detail || '')
    item = data.item
  } catch (e) {
    error.value = `筆記沒有存成功：${reason(e)}。內容還在，可以再試一次。`
    return
  }
  text.value = ''
  close()
  if (item?.analysis_status === 'pending') toast.success('筆記已儲存，尚未分析', { description: NOT_ANALYSED_HINT })
  else toast.success('筆記已儲存')
  await itemsStore.refreshAll()
  if (item) ui.activeItem = item
}

/** One address is read right away and opened; several are queued and read one after another. */
async function saveLinks(urls: string[]) {
  const queued = urls.length > 1
  const failed: { url: string; why: string }[] = []
  let saved = 0
  let item: Item | undefined
  for (const [index, url] of urls.entries()) {
    if (queued) progress.value = `正在送出第 ${index + 1} 個，共 ${urls.length} 個`
    try {
      const data = await api.ingest(url, { async: queued })
      if (!data.success) throw new Error(data.detail || '')
      saved++
      item = data.item
    } catch (e) {
      failed.push({ url, why: reason(e) })
    }
  }
  if (saved) void itemsStore.refreshAll()
  if (!failed.length) {
    text.value = ''
    close()
    if (queued) toast.success(`已排入 ${saved} 個連結`, { description: '讀完後會出現在收件匣。' })
    else if (item?.analysis_status === 'pending') toast.success('已收藏，尚未分析', { description: NOT_ANALYSED_HINT })
    else toast.success('已收藏', { description: item?.title_l1?.slice(0, 70) })
    if (item) ui.activeItem = item
    return
  }
  // Keep what did not go through. Text that was only addresses is cut down to the failed ones.
  if (natural.value.kind === 'links') text.value = failed.map((f) => f.url).join('\n')
  error.value = urls.length === 1
    ? `連結沒有收藏成功：${failed[0].why}。內容還在，可以再試一次。`
    : `${failed.length} 個連結沒有送出（另外 ${saved} 個已排入）：${failed[0].why}。沒送出的還在，可以再試一次。`
}

/* ---------------- Files and drops ---------------- */

function takeFiles(list: FileList | null | undefined) {
  if (!list?.length) return
  file.value = list[0]
  error.value = ''
}
function onPicked(event: Event) {
  const target = event.target as HTMLInputElement
  takeFiles(target.files)
  target.value = ''
}
function onDrop(event: DragEvent) {
  dragDepth.value = 0
  const data = event.dataTransfer
  if (!data) return
  if (data.files?.length) return takeFiles(data.files)
  // A link or a selection dragged in from another window.
  const dropped = (data.getData('text/uri-list') || data.getData('text/plain')).trim()
  if (dropped) text.value = text.value.trim() ? `${text.value.trimEnd()}\n${dropped}` : dropped
}

/* ---------------- A link pasted on the page opens the panel with it ---------------- */

function onPaste(event: ClipboardEvent) {
  if (ui.showAddModal || ui.showSettingsModal) return
  const el = document.activeElement
  const tag = el?.tagName?.toLowerCase() ?? ''
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || (el instanceof HTMLElement && el.isContentEditable)) return
  if (document.querySelector?.('[data-state="open"]:is([role="dialog"], [role="alertdialog"])')) return
  const pasted = event.clipboardData?.getData('text/plain') ?? ''
  if (!isPastedLinks(pasted)) return
  event.preventDefault()
  ui.openAdd(pasted.trim())
}
onMounted(() => window.addEventListener('paste', onPaste))
onUnmounted(() => window.removeEventListener('paste', onPaste))

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault()
    void submit()
  }
}
</script>

<template>
  <Dialog :open="ui.showAddModal" @update:open="(v) => (ui.showAddModal = v)">
    <DialogContent
      :class="`add-panel max-w-xl gap-4 rounded-xl max-sm:max-w-[calc(100vw-24px)] max-sm:p-4 ${dragDepth > 0 ? 'add-panel--drop' : ''}`"
      :aria-busy="busy"
      @open-auto-focus="(e: Event) => { e.preventDefault(); area?.focus() }"
      @dragenter.prevent="dragDepth++"
      @dragover.prevent
      @dragleave.prevent="dragDepth = Math.max(0, dragDepth - 1)"
      @drop.prevent="onDrop"
    >
      <DialogTitle class="text-lg font-semibold leading-[26px] tracking-normal">新增</DialogTitle>
      <DialogDescription class="sr-only">貼上連結會收藏，其他文字存成筆記，書籤檔交給匯入。</DialogDescription>

      <form class="contents" @submit.prevent="submit">
        <!-- A chosen file stands in for the box; removing it brings the text back -->
        <div v-if="file" class="add-file">
          <FileText aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate">{{ file.name }}</span>
          <button type="button" class="icon-button" aria-label="移除檔案" title="移除檔案" @click="file = null"><X /></button>
        </div>
        <textarea
          v-else
          ref="area"
          v-model="text"
          rows="6"
          class="set-input add-panel__box"
          aria-label="要新增的內容"
          :aria-invalid="!!error"
          aria-describedby="add-outcome add-error"
          :placeholder="canDrag ? '貼上連結、寫筆記，或把檔案拖進來' : '貼上連結或寫筆記'"
          :disabled="busy"
          @input="error = ''"
          @keydown="onKeydown"
        />

        <!-- What sending will do, and the one thing about it that can be changed -->
        <div class="flex min-h-10 flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p id="add-outcome" class="text-sm" :class="plan.kind === 'unsupported' ? 'text-danger' : 'text-muted-foreground'" aria-live="polite">
            <template v-if="progress">{{ progress }}</template>
            <template v-else-if="outcome">{{ outcome }}</template>
            <template v-else>連結會收藏，其他文字存成筆記，書籤檔（.html、.json、.csv）會匯入。</template>
          </p>
          <label v-if="!file && natural.kind === 'note' && natural.urls.length" class="flex items-center gap-2 text-sm">
            只收藏連結
            <Switch :model-value="linksOnly" :disabled="busy" @update:model-value="linksOnly = $event" />
          </label>
          <label v-else-if="!file && natural.kind === 'links'" class="flex items-center gap-2 text-sm">
            存成筆記
            <Switch :model-value="asNote" :disabled="busy" @update:model-value="asNote = $event" />
          </label>
        </div>

        <div v-if="plan.kind === 'note'" class="flex items-center justify-between gap-4 text-sm">
          <span class="text-muted-foreground">分類</span>
          <Select v-model="category" :options="categoryOptions" :disabled="busy" aria-label="分類" small />
        </div>

        <p v-if="error" id="add-error" class="set-error" role="alert">{{ error }}</p>

        <div class="flex items-center gap-2">
          <input ref="picker" type="file" class="hidden" :accept="IMPORT_EXTENSIONS.join(',')" @change="onPicked" />
          <button type="button" class="set-button set-button--text -ml-2" :disabled="busy" @click="picker?.click()"><Paperclip aria-hidden="true" />選擇檔案</button>
          <button type="button" class="set-button set-button--text ml-auto" @click="close">取消</button>
          <button type="submit" class="set-button set-button--primary" :disabled="!canSubmit" title="Ctrl/Cmd+Enter">
            <Loader2 v-if="busy" class="animate-spin" aria-hidden="true" />
            {{ submitLabel(plan) }}
          </button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
</template>
