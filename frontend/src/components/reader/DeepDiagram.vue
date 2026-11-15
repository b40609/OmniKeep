<script setup lang="ts">
/* The architecture diagram the user's own coding agent drew with Archify (app/deep_diagram.py).
   Without one: a prompt to copy into the agent. With one: the page in a sandboxed frame, scripts on
   but a unique origin and no network, so it cannot reach OmniKeep's key or API. */
import { ref, watch, onBeforeUnmount } from 'vue'
import { toast } from 'vue-sonner'
import { Bot, Copy, Maximize2, RefreshCw, Trash2, X } from 'lucide-vue-next'
import { deleteDiagram, fetchDiagramHtml, getDiagramStatus, type DiagramStatus } from '@/lib/api'

const props = defineProps<{ itemId: number | string }>()

const status = ref<DiagramStatus | null>(null)
const html = ref('')
const loading = ref(false)
const full = ref(false)
const showPrompt = ref(false)

async function load() {
  const id = props.itemId
  loading.value = true
  try {
    const s = await getDiagramStatus(id)
    if (id !== props.itemId) return
    status.value = s
    html.value = s.has_diagram ? await fetchDiagramHtml(id) : ''
  } catch {
    status.value = null
  } finally {
    loading.value = false
  }
}
watch(() => props.itemId, () => { full.value = false; showPrompt.value = false; html.value = ''; void load() }, { immediate: true })

async function copyPrompt() {
  if (!status.value) return
  try {
    await navigator.clipboard.writeText(status.value.prompt)
    toast.success('已複製，貼給你的 Claude Code 或 Codex', { description: '畫好會自動存回這裡，按「重新檢查」就看得到。' })
  } catch {
    showPrompt.value = true
    toast.error('沒辦法自動複製，指令已展開在下方')
  }
}

async function remove() {
  if (!window.confirm('刪掉 agent 畫的架構圖？刪了要再請 agent 重畫。')) return
  try {
    await deleteDiagram(props.itemId)
    toast.success('已刪除')
    void load()
  } catch (e) {
    toast.error('刪除失敗', { description: e instanceof Error ? e.message : String(e) })
  }
}

function onKey(ev: KeyboardEvent) { if (ev.key === 'Escape') full.value = false }
watch(full, (on) => { if (on) window.addEventListener('keydown', onKey); else window.removeEventListener('keydown', onKey) })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <section v-if="status" class="border-t border-hairline pt-6" aria-label="agent 架構圖">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 class="flex items-center gap-2 text-base font-semibold text-foreground">
        <Bot class="size-4 text-muted-foreground" />
        agent 架構圖
      </h2>
      <div class="flex items-center gap-1.5">
        <button
          type="button"
          class="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent disabled:opacity-50"
          :disabled="loading"
          title="agent 畫好之後按這裡"
          @click="load"
        >
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          重新檢查
        </button>
        <template v-if="status.has_diagram">
          <button type="button" class="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent" @click="full = true">
            <Maximize2 class="size-3.5" />
            全螢幕
          </button>
          <button type="button" class="inline-flex min-h-9 cursor-pointer items-center rounded-lg border border-border px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent" aria-label="刪除 agent 架構圖" title="刪除" @click="remove">
            <Trash2 class="size-3.5" />
          </button>
        </template>
      </div>
    </div>

    <template v-if="status.has_diagram && html">
      <iframe
        class="block h-[34rem] w-full rounded-xl border border-border bg-card"
        title="agent 畫的架構圖"
        sandbox="allow-scripts allow-downloads"
        referrerpolicy="no-referrer"
        :srcdoc="html"
      />
      <p class="mt-2 text-xs text-subtle-foreground">
        由你的 agent 用 Archify 讀過程式碼後畫的，每個元件都對照過程式碼。要重畫就
        <button type="button" class="cursor-pointer underline underline-offset-2 hover:text-foreground" @click="copyPrompt">複製指令</button>
        再交給 agent 一次。
      </p>
    </template>

    <div v-else class="rounded-xl border border-border bg-muted/30 p-4">
      <p class="text-sm text-foreground">讓你的 Claude Code、Codex 或 Antigravity 讀過整份程式碼再畫一張</p>
      <p class="mt-1 text-xs text-muted-foreground">
        用開源的 Archify：每個元件都對照到程式碼的檔案與行號，可以搜尋、看上下游、匯出圖片。agent 畫完會自動存回這則收藏。
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="inline-flex min-h-10 cursor-pointer items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          @click="copyPrompt"
        >
          <Copy class="size-3.5" />
          複製給 agent 的指令
        </button>
        <button type="button" class="min-h-10 cursor-pointer px-2 text-xs text-muted-foreground underline-offset-2 hover:underline" @click="showPrompt = !showPrompt">
          {{ showPrompt ? '收起指令' : '看指令內容' }}
        </button>
      </div>
      <pre v-if="showPrompt" class="mt-3 max-h-72 overflow-auto rounded-lg border border-border bg-card p-3 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">{{ status.prompt }}</pre>
    </div>

    <Teleport to="body">
      <div v-if="full && html" class="fixed inset-0 z-50 flex flex-col bg-background" role="dialog" aria-label="agent 架構圖（全螢幕）">
        <div class="flex items-center justify-between border-b border-hairline px-4 py-2">
          <span class="text-sm text-muted-foreground">agent 架構圖</span>
          <button type="button" class="inline-flex min-h-9 cursor-pointer items-center gap-1 rounded-lg px-2.5 text-sm text-muted-foreground hover:bg-accent" aria-label="關閉全螢幕" @click="full = false">
            <X class="size-4" />
            關閉
          </button>
        </div>
        <iframe class="block w-full flex-1" title="agent 畫的架構圖（全螢幕）" sandbox="allow-scripts allow-downloads" referrerpolicy="no-referrer" :srcdoc="html" />
      </div>
    </Teleport>
  </section>
</template>
