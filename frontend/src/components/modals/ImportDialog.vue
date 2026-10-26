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
import { toast } from 'vue-sonner'

const ui = useUiStore()
const itemsStore = useItemsStore()

type ImportTab = 'file' | 'text'
const activeTab = ref<ImportTab>('file')

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
    toast.error('檔案格式不支援', {
      description: '請選擇 Netscape HTML (.html)、Chrome/Raindrop JSON (.json) 或 CSV (.csv) 格式書籤',
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
      `匯入完成！成功納庫 ${res.imported_count || res.queued_count} 筆條目`,
      { id: toastId }
    )
    await itemsStore.refreshAll()
  } catch (err) {
    toast.error('書籤匯入失敗', {
      id: toastId,
      description: err instanceof Error ? err.message : '請檢查書籤格式是否完整',
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
            <DialogTitle class="flex items-center gap-2">
              書籤與外部檔案匯入
              <span class="rounded border border-primary/30 bg-primary-soft px-1.5 py-px font-mono text-2xs text-primary-soft-foreground">BOOKMARK IMPORT</span>
            </DialogTitle>
            <DialogDescription>
              支援 Chrome / Edge / Safari / Arc / Firefox / Pocket / Raindrop 匯出之書籤
            </DialogDescription>
          </DialogHeader>
        </div>
      </div>

      <!-- Mode Tabs (File drag vs Text paste) -->
      <div class="flex shrink-0 items-center gap-1 border-b border-border px-5 text-xs" role="tablist">
        <button
          role="tab"
          :aria-selected="activeTab === 'file'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'file' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'file'"
        >
          檔案拖曳上傳 (.html / .json / .csv)
          <span v-if="activeTab === 'file'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
        <button
          role="tab"
          :aria-selected="activeTab === 'text'"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="activeTab === 'text' ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'text'"
        >
          直接貼上內容
          <span v-if="activeTab === 'text'" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
      </div>

      <!-- Main Body -->
      <div class="min-h-0 flex-1 overflow-y-auto p-5 space-y-4">
        <!-- 1. Result summary card (if finished) -->
        <div v-if="importResult" class="rounded-xl border border-primary/30 bg-primary-soft/10 p-4 animate-in fade-in">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <CheckCircle2 class="size-5 text-success" />
              <span class="text-sm font-bold text-foreground">書籤匯入作業完成</span>
            </div>
            <Button size="sm" variant="ghost" class="h-7 text-2xs" @click="resetState">
              <RotateCcw class="size-3" /> 匯入其他檔案
            </Button>
          </div>

          <div class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div class="rounded-lg bg-background/70 p-2.5">
              <div class="text-2xs text-muted-foreground">解析總條目</div>
              <div class="text-base font-bold font-mono text-foreground">{{ importResult.total_parsed }}</div>
            </div>
            <div class="rounded-lg bg-success-soft/20 p-2.5">
              <div class="text-2xs text-success">已成功納庫</div>
              <div class="text-base font-bold font-mono text-success">{{ importResult.imported_count }}</div>
            </div>
            <div class="rounded-lg bg-primary-soft/20 p-2.5">
              <div class="text-2xs text-primary-soft-foreground">排入 AI 佇列</div>
              <div class="text-base font-bold font-mono text-primary-soft-foreground">{{ importResult.queued_count }}</div>
            </div>
            <div class="rounded-lg bg-muted p-2.5">
              <div class="text-2xs text-muted-foreground">跳過/不安全</div>
              <div class="text-base font-bold font-mono text-muted-foreground">{{ importResult.skipped_count }}</div>
            </div>
          </div>

          <p v-if="importResult.skipped_count > 0" class="mt-2 text-2xs text-muted-foreground">
            說明：基於 SSRF 防禦原則，已自動過濾內網/私有 IP（如 127.0.0.1、非公開網段）或無效協定。
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
                拖曳書籤檔案至此，或點擊選擇檔案
              </p>
              <p class="mt-1 text-2xs text-subtle-foreground max-w-sm">
                支援各大瀏覽器匯出之 bookmarks.html (Netscape 規範)、Raindrop/Chrome JSON 或 CSV 匯出檔
              </p>
              <div class="mt-4 flex flex-wrap items-center justify-center gap-1.5 font-mono text-2xs">
                <Badge variant="outline" class="bg-background/80">.html (Netscape)</Badge>
                <Badge variant="outline" class="bg-background/80">.json (Chrome/Raindrop)</Badge>
                <Badge variant="outline" class="bg-background/80">.csv (通用)</Badge>
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
                    <div class="truncate text-xs font-semibold text-foreground">{{ selectedFile.name }}</div>
                    <div class="flex items-center gap-2 font-mono text-2xs text-subtle-foreground">
                      <span>{{ formatBytes(selectedFile.size) }}</span>
                      <span v-if="estimatedItemsCount !== null" class="text-primary-soft-foreground">
                        • 預估約 {{ estimatedItemsCount }} 筆書籤
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
              placeholder="貼上 Netscape HTML（包含 <A HREF=...>）、JSON 陣列或 CSV 內容…"
              class="w-full resize-none rounded-xl border border-border bg-input p-3 font-mono text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
            />
            <p class="text-2xs text-muted-foreground">
              系統將自動偵測標頭格式並提取 URL、標題、時間與標籤屬性。
            </p>
          </div>

          <!-- Ingestion Options -->
          <div class="mt-4 space-y-3 rounded-xl border border-border/50 bg-background-subtle/50 p-3.5 text-xs">
            <div class="font-semibold text-foreground">匯入配置與策略</div>

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
                    <span>秒速快速入庫 (推薦)</span>
                  </div>
                  <div class="text-2xs text-muted-foreground leading-tight mt-0.5">
                    0 LLM 成本消耗；保留階層資料夾標籤，並即時套用「硬規則引擎」完成分流。
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
                    <span>排入 AI 深度解析佇列</span>
                  </div>
                  <div class="text-2xs text-muted-foreground leading-tight mt-0.5">
                    寫入 SQLite 佇列，由後台 Worker 異步抓取全文、產生 L1/L2 摘要與向量嵌入。
                  </div>
                </div>
              </label>
            </div>

            <!-- Target Category -->
            <div class="flex items-center justify-between pt-1">
              <span class="text-subtle-foreground text-2xs">預設收納分類</span>
              <select
                v-model="selectedCategory"
                class="h-7 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none"
              >
                <option value="Inbox">Inbox (預設收件匣)</option>
                <option v-for="c in itemsStore.categories" :key="c.id" :value="c.name">
                  {{ c.name }}
                </option>
              </select>
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
          v-if="!importResult"
          size="sm"
          :disabled="!canSubmit || isImporting"
          @click="runImport"
        >
          <Loader2 v-if="isImporting" class="size-3.5 animate-spin" />
          {{ isImporting ? '匯入處理中…' : '開始匯入' }}
        </Button>
        <Button
          v-else
          size="sm"
          @click="closeDialog"
        >
          查看書籤庫
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
