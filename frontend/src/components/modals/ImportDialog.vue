<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  UploadCloud,
  FileCode,
  FileSpreadsheet,
  FileText,
  CheckCircle2,
  X,
  Loader2,
  Sparkles,
  Zap,
  RotateCcw,
  FolderInput,
  Download,
  Bookmark,
  Copy,
  FileArchive,
  Check,
} from 'lucide-vue-next'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import Badge from '@/components/ui/badge/Badge.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import * as api from '@/lib/api'
import { bookmarkletHref as bookmarkletHrefFor } from '@/lib/bookmarklet'
import { toast } from 'vue-sonner'

const ui = useUiStore()
const itemsStore = useItemsStore()

// The tab lives in the store, so the settings page can open this dialog on its export tab.
const activeTab = computed({ get: () => ui.importTab, set: (tab) => (ui.importTab = tab) })

const exportStarredOnly = ref(false)
const isExporting = ref(false)
const copiedBookmarklet = ref(false)

const bookmarkletHref = computed(() =>
  bookmarkletHrefFor(typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'),
)

async function copyBookmarkletCode() {
  await navigator.clipboard.writeText(bookmarkletHref.value)
  copiedBookmarklet.value = true
  toast.success('已複製書籤程式碼')
  setTimeout(() => (copiedBookmarklet.value = false), 2000)
}

async function handleExport(format: 'json' | 'markdown') {
  isExporting.value = true
  const t = toast.loading(`正在準備 ${format.toUpperCase()} 匯出檔…`)
  try {
    const { blob, filename } = await api.exportItems(format, exportStarredOnly.value)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(a.href)
    toast.success(`已開始下載 ${filename}`, { id: t })
  } catch (e) {
    toast.error('匯出失敗：' + (e as Error).message, { id: t })
  } finally {
    isExporting.value = false
  }
}

// File state
const isDragging = ref(false)
const selectedFile = ref<File | null>(null)
const fileContent = ref<string>('')
const estimatedItemsCount = ref<number | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

// Text paste state
const pastedContent = ref('')

// Config options
const enqueueAi = ref(false)
const selectedCategory = ref('Inbox')

// Execution & Result state
const isImporting = ref(false)
const importResult = ref<api.BookmarkImportResult | null>(null)

function resetState() {
  selectedFile.value = null
  fileContent.value = ''
  estimatedItemsCount.value = null
  pastedContent.value = ''
  importResult.value = null
  isImporting.value = false
  isDragging.value = false
  if (fileInput.value) fileInput.value.value = ''
}

function estimateCountFromText(text: string, filename: string): number {
  const lowerName = filename.toLowerCase()
  if (lowerName.endsWith('.json') || text.trim().startsWith('{') || text.trim().startsWith('[')) {
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) return parsed.length
      if (parsed.roots) {
        // Count Chrome URLs roughly
        const matches = text.match(/"type":\s*"url"/g)
        return matches ? matches.length : 0
      }
      for (const k of ['bookmarks', 'items', 'links', 'data']) {
        if (Array.isArray(parsed[k])) return parsed[k].length
      }
    } catch {
      /* ignore */
    }
  }
  if (lowerName.endsWith('.csv') || text.includes(',')) {
    const lines = text.trim().split('\n').filter((l) => l.trim())
    return Math.max(0, lines.length - 1)
  }
  // Netscape HTML
  const matches = text.match(/<a\s+href=/gi)
  return matches ? matches.length : 0
}

function processFile(file: File) {
  const validExts = ['.html', '.htm', '.json', '.csv']
  const lowerName = file.name.toLowerCase()
  const isValid = validExts.some((ext) => lowerName.endsWith(ext))

  if (!isValid) {
    toast.error('不支援這種檔案', {
      description: '請選 .html、.json 或 .csv 的書籤檔',
    })
    return
  }

  selectedFile.value = file
  importResult.value = null

  const reader = new FileReader()
  reader.onload = (e) => {
    const text = (e.target?.result as string) || ''
    fileContent.value = text
    estimatedItemsCount.value = estimateCountFromText(text, file.name)
  }
  reader.readAsText(file)
}

function onFileSelected(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    processFile(target.files[0])
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    processFile(e.dataTransfer.files[0])
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const canSubmit = computed(() => {
  if (isImporting.value) return false
  if (activeTab.value === 'file') {
    return !!selectedFile.value && !!fileContent.value.trim()
  } else {
    return !!pastedContent.value.trim()
  }
})

async function runImport() {
  const content = activeTab.value === 'file' ? fileContent.value : pastedContent.value
  const filename = activeTab.value === 'file' ? selectedFile.value?.name || 'bookmarks.html' : 'pasted_bookmarks.html'

  if (!content.trim()) return

  isImporting.value = true
  const toastId = toast.loading('正在解析並匯入書籤…')

  try {
    const res = await api.importBookmarks(content, {
      filename,
      enqueue_ai: enqueueAi.value,
      default_category: selectedCategory.value,
    })

    importResult.value = res
    toast.success(
      `匯入完成，共 ${res.imported_count || res.queued_count} 則`,
      { id: toastId }
    )
    await itemsStore.refreshAll()
  } catch (err) {
    toast.error('書籤匯入失敗', {
      id: toastId,
      description: err instanceof Error ? err.message : '請確認書籤檔內容完整',
    })
  } finally {
    isImporting.value = false
  }
}

function closeDialog() {
  ui.showImportModal = false
  resetState()
}
</script>

<template>
  <Dialog :open="ui.showImportModal" @update:open="(v) => (ui.showImportModal = v)">
    <DialogContent class="flex max-h-[90vh] max-w-2xl flex-col gap-0 p-0 overflow-hidden">
      <!-- Header -->
      <div class="flex shrink-0 items-center justify-between border-b border-border p-5 pb-4">
        <div class="flex items-center gap-2.5">
          <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <FolderInput class="size-4.5" />
          </div>
          <DialogHeader>
            <DialogTitle>匯入書籤</DialogTitle>
            <DialogDescription>
              支援 Chrome、Edge、Safari、Arc、Firefox、Pocket、Raindrop 匯出的書籤檔。
            </DialogDescription>
          </DialogHeader>
        </div>
      </div>

      <!-- Mode Tabs (File drag vs Text paste) -->
      <div class="flex shrink-0 items-center gap-1 border-b border-border px-5 text-sm" role="tablist">
        <button
          role="tab"
          :aria-selected="activeTab === 'file'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'file' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'file'"
        >
          上傳檔案
          <span v-if="activeTab === 'file'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
        <button
          role="tab"
          :aria-selected="activeTab === 'text'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'text' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'text'"
        >
          貼上內容
          <span v-if="activeTab === 'text'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
        <button
          role="tab"
          :aria-selected="activeTab === 'bookmarklet'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'bookmarklet' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'bookmarklet'"
        >
          書籤列按鈕
          <span v-if="activeTab === 'bookmarklet'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
        <button
          role="tab"
          :aria-selected="activeTab === 'export'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'export' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'export'"
        >
          匯出收藏
          <span v-if="activeTab === 'export'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
      </div>

      <!-- Main Body -->
      <div class="min-h-0 flex-1 overflow-y-auto p-5 space-y-4">
        <!-- 1. Result summary card (if finished) -->
        <div v-if="importResult" class="rounded-xl border border-primary/30 bg-primary-soft/10 p-4 animate-in fade-in">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <CheckCircle2 class="size-5 text-success" />
              <span class="text-sm font-bold text-foreground">匯入完成</span>
            </div>
            <Button size="sm" variant="ghost" class="h-7 text-sm" @click="resetState">
              <RotateCcw class="size-3" /> 匯入其他檔案
            </Button>
          </div>

          <div class="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div class="rounded-lg bg-background/70 p-2.5">
              <div class="text-sm text-muted-foreground">讀到的書籤</div>
              <div class="text-base font-bold font-mono text-foreground">{{ importResult.total_parsed }}</div>
            </div>
            <div class="rounded-lg bg-success-soft/20 p-2.5">
              <div class="text-sm text-success">已匯入</div>
              <div class="text-base font-bold font-mono text-success">{{ importResult.imported_count }}</div>
            </div>
            <div class="rounded-lg bg-primary-soft/20 p-2.5">
              <div class="text-sm text-primary-soft-foreground">等待 AI 分析</div>
              <div class="text-base font-bold font-mono text-primary-soft-foreground">{{ importResult.queued_count }}</div>
            </div>
            <div class="rounded-lg bg-muted p-2.5">
              <div class="text-sm text-muted-foreground">略過</div>
              <div class="text-base font-bold font-mono text-muted-foreground">{{ importResult.skipped_count }}</div>
            </div>
          </div>

          <p v-if="importResult.skipped_count > 0" class="mt-2 text-sm text-muted-foreground">
            略過的是內部網路位址（例如 127.0.0.1）或不是網頁的連結。
          </p>
        </div>

        <!-- 2. Input Zone: File Drag or Text Paste -->
        <div v-if="!importResult">
          <!-- File Dropzone -->
          <div v-if="activeTab === 'file'">
            <!-- When file not chosen -->
            <div
              v-if="!selectedFile"
              class="relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition-all cursor-pointer"
              :class="isDragging
                ? 'border-primary bg-primary-soft/15 ring-4 ring-primary/20 scale-[0.99]'
                : 'border-border/70 bg-white/40 hover:border-primary/50 hover:bg-white/60 dark:bg-white/[0.03] dark:hover:bg-white/[0.06]'"
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
              @drop.prevent="handleDrop"
              @click="fileInput?.click()"
            >
              <input
                ref="fileInput"
                type="file"
                class="hidden"
                accept=".html,.htm,.json,.csv"
                @change="onFileSelected"
              >
              <div class="mb-3 flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-inner">
                <UploadCloud class="size-6" />
              </div>
              <p class="text-sm font-semibold text-foreground">
                把書籤檔拖到這裡，或按一下選擇檔案
              </p>
              <p class="mt-1 text-sm text-subtle-foreground max-w-sm">
                瀏覽器匯出的 bookmarks.html、Raindrop 或 Chrome 的 JSON、CSV 都可以。
              </p>
              <div class="mt-4 flex flex-wrap items-center justify-center gap-1.5 font-mono text-2xs">
                <Badge variant="outline" class="bg-background/80">.html (Netscape)</Badge>
                <Badge variant="outline" class="bg-background/80">.json (Chrome/Raindrop)</Badge>
                <Badge variant="outline" class="bg-background/80">.csv</Badge>
              </div>
            </div>

            <!-- When file chosen -->
            <div v-else class="rounded-xl border border-border/60 bg-white/50 p-4 dark:bg-white/[0.05]">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-3 min-w-0">
                  <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary-soft-foreground">
                    <FileCode v-if="selectedFile.name.endsWith('.html') || selectedFile.name.endsWith('.htm')" class="size-5" />
                    <FileSpreadsheet v-else-if="selectedFile.name.endsWith('.csv')" class="size-5" />
                    <FileText v-else class="size-5" />
                  </div>
                  <div class="min-w-0">
                    <div class="truncate text-sm font-semibold text-foreground">{{ selectedFile.name }}</div>
                    <div class="flex items-center gap-2 font-mono text-2xs text-subtle-foreground">
                      <span>{{ formatBytes(selectedFile.size) }}</span>
                      <span v-if="estimatedItemsCount !== null" class="text-primary-soft-foreground">
                        約 {{ estimatedItemsCount }} 個書籤
                      </span>
                    </div>
                  </div>
                </div>
                <button
                  class="rounded-md p-1.5 text-subtle-foreground transition-colors hover:bg-danger-soft hover:text-danger"
                  title="清除檔案"
                  aria-label="清除檔案"
                  @click="resetState"
                >
                  <X class="size-4" />
                </button>
              </div>
            </div>
          </div>

          <!-- Text Paste Area -->
          <div v-else class="space-y-2">
            <textarea
              v-model="pastedContent"
              rows="7"
              placeholder="貼上書籤檔的 HTML、JSON 或 CSV 內容"
              class="w-full resize-none rounded-xl border border-border bg-input p-3 font-mono text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
            />
            <p class="text-sm text-muted-foreground">
              會自動判斷格式，讀出網址、標題、時間與標籤。
            </p>
          </div>

          <!-- Ingestion Options -->
          <div class="mt-4 space-y-3 rounded-xl border border-border/50 bg-background-subtle/50 p-3.5 text-sm">
            <div class="font-semibold text-foreground">匯入方式</div>

            <!-- Mode Selection Cards -->
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label
                class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors"
                :class="!enqueueAi
                  ? 'border-primary bg-primary-soft/15 ring-1 ring-primary/30'
                  : 'border-border/60 bg-background/50 hover:bg-accent/40'"
              >
                <input v-model="enqueueAi" type="radio" :value="false" class="mt-0.5">
                <div>
                  <div class="flex items-center gap-1 font-semibold text-foreground">
                    <Zap class="size-3 text-warning" />
                    <span>只匯入，不分析（建議）</span>
                  </div>
                  <div class="text-sm text-muted-foreground leading-tight mt-0.5">
                    不使用 AI；保留原本的資料夾當標籤，並套用你設的自動規則。
                  </div>
                </div>
              </label>

              <label
                class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors"
                :class="enqueueAi
                  ? 'border-primary bg-primary-soft/15 ring-1 ring-primary/30'
                  : 'border-border/60 bg-background/50 hover:bg-accent/40'"
              >
                <input v-model="enqueueAi" type="radio" :value="true" class="mt-0.5">
                <div>
                  <div class="flex items-center gap-1 font-semibold text-foreground">
                    <Sparkles class="size-3 text-primary" />
                    <span>匯入後交給 AI 分析</span>
                  </div>
                  <div class="text-sm text-muted-foreground leading-tight mt-0.5">
                    匯入後會在背景取得全文並整理摘要，可繼續瀏覽其他收藏。
                  </div>
                </div>
              </label>
            </div>

            <!-- Target Category -->
            <div class="flex items-center justify-between pt-1">
              <span class="text-muted-foreground text-sm">放進哪個分類</span>
              <select
                v-model="selectedCategory"
                class="h-7 rounded-md border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none"
              >
                <option value="Inbox" class="bg-popover text-foreground">收件匣</option>
                <option v-for="c in itemsStore.categories" :key="c.id" :value="c.name" class="bg-popover text-foreground">
                  {{ c.name }}
                </option>
              </select>
            </div>
          </div>
        </div>
        <!-- ── Bookmarklet Tab ── -->
        <div v-if="activeTab === 'bookmarklet'" class="space-y-4 py-2">
          <div class="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm space-y-3">
            <div class="flex items-center gap-2 font-semibold text-foreground">
              <Bookmark class="size-4 text-primary" />
              <span>書籤列按鈕（不用安裝擴充功能）</span>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              把下面的按鈕拖到瀏覽器的書籤列（Chrome、Edge、Safari、Firefox 都可以）。
              之後看到想留的文章、貼文或影片，按一下書籤就會把那一頁送到 OmniKeep 收錄。
            </p>
            <div class="flex flex-wrap items-center gap-3 pt-1">
              <a
                :href="bookmarkletHref"
                class="inline-flex items-center gap-1.5 rounded-lg border border-primary bg-primary px-3.5 py-2 font-mono text-sm font-bold text-primary-foreground shadow-sm hover:opacity-90 active:scale-95 cursor-grab active:cursor-grabbing select-none"
                title="拖到瀏覽器的書籤列"
                @click.prevent="toast.info('把這個按鈕拖到瀏覽器的書籤列')"
              >
                <Bookmark class="size-4" /><span>存入 OmniKeep</span>
              </a>
              <Button size="sm" variant="outline" class="h-8 gap-1.5 text-sm" @click="copyBookmarkletCode">
                <Check v-if="copiedBookmarklet" class="size-3 text-success" />
                <Copy v-else class="size-3" />
                <span>{{ copiedBookmarklet ? '已複製' : '複製程式碼' }}</span>
              </Button>
            </div>
          </div>
        </div>

        <!-- ── Export Tab ── -->
        <div v-if="activeTab === 'export'" class="space-y-4 py-2">
          <div class="rounded-xl border border-border bg-card p-4 text-sm space-y-3">
            <div class="flex items-center gap-2 font-semibold text-foreground">
              <Download class="size-4 text-primary" />
              <span>匯出收藏</span>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              收藏與筆記可以隨時整份匯出：標準 JSON，或每則一個 Markdown 檔的壓縮檔（可放進 Obsidian、Logseq、Notion）。
            </p>

            <div class="flex items-center gap-2 pt-1 pb-2">
              <input
                id="export-starred"
                v-model="exportStarredOnly"
                type="checkbox"
                class="size-3.5 rounded border-border accent-primary cursor-pointer"
              />
              <label for="export-starred" class="text-sm text-foreground cursor-pointer select-none">
                只匯出加星的收藏
              </label>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              <button
                :disabled="isExporting"
                class="flex flex-col items-start gap-1 rounded-xl border border-border p-3 text-left transition hover:border-primary hover:bg-accent active:scale-98 disabled:opacity-50 cursor-pointer"
                @click="handleExport('json')"
              >
                <div class="flex items-center gap-1.5 font-semibold text-foreground">
                  <FileCode class="size-4 text-primary" />
                  <span>完整 JSON</span>
                </div>
                <span class="text-sm text-muted-foreground">包含所有欄位、摘要、分析與原文</span>
              </button>

              <button
                :disabled="isExporting"
                class="flex flex-col items-start gap-1 rounded-xl border border-border p-3 text-left transition hover:border-primary hover:bg-accent active:scale-98 disabled:opacity-50 cursor-pointer"
                @click="handleExport('markdown')"
              >
                <div class="flex items-center gap-1.5 font-semibold text-foreground">
                  <FileArchive class="size-4 text-violet-500" />
                  <span>Markdown 壓縮檔（.zip）</span>
                </div>
                <span class="text-sm text-muted-foreground">每則一個 .md 檔，含標籤與連結</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer Buttons -->
      <div class="flex shrink-0 items-center justify-end gap-2 border-t border-border p-4 bg-background/40">
        <Button variant="ghost" size="sm" @click="closeDialog">
          {{ importResult ? '關閉' : '取消' }}
        </Button>
        <Button
          v-if="!importResult && (activeTab === 'file' || activeTab === 'text')"
          size="sm"
          :disabled="!canSubmit || isImporting"
          @click="runImport"
        >
          <Loader2 v-if="isImporting" class="size-3.5 animate-spin" />
          {{ isImporting ? '匯入中…' : '開始匯入' }}
        </Button>
        <Button
          v-else
          size="sm"
          @click="closeDialog"
        >
          完成
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
