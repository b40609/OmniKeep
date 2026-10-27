<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  ScanEye, Plus, Loader2, RefreshCw, ShieldCheck, Trash2, Power,
  ChevronDown, ChevronRight, CheckCircle2, XCircle, HardDriveDownload,
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import Button from '@/components/ui/button/Button.vue'
import * as api from '@/lib/api'
import type { WatchTarget, Proposal, BackupStatus, WatchPreset } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import { toast } from 'vue-sonner'

const ui = useUiStore()

const tab = ref<'targets' | 'proposals' | 'backup'>('targets')
const targets = ref<WatchTarget[]>([])
const proposals = ref<Proposal[]>([])
const backup = ref<BackupStatus | null>(null)
const loading = ref(false)
const scanningId = ref<string | null>(null)
const expandedId = ref<string | null>(null)
const correctingId = ref<string | null>(null)
const backingUp = ref(false)

// ── add-target form ──
const showAdd = ref(false)
const newName = ref('')
const newPath = ref('')
const newPreset = ref<WatchPreset>('balanced')
const customRead = ref<api.WatchToggleMap>({ filenames: true, readme: true, deps: true, code: false, git: false })
const customOut = ref<api.OutboundToggleMap>({ summary: true, docs: true, deps: true, code: false, git: false })

// ── score correction form ──
const corr = ref({ impact: 5, confidence: 5, effort: 5, reason: '' })
const expandedEvidence = ref<Record<string, boolean>>({})
function toggleEvidence(id: string) {
  expandedEvidence.value[id] = !expandedEvidence.value[id]
}

const PRESETS: { id: WatchPreset; label: string; desc: string }[] = [
  { id: 'open', label: '🔓 全開放', desc: '全部可讀、可外送（機密仍自動遮蔽）' },
  { id: 'balanced', label: '⚖️ 平衡', desc: '文件＋依賴可讀可送，程式碼不出門' },
  { id: 'strict', label: '🔒 嚴謹', desc: '只讀檔名與 README，僅送話題摘要' },
  { id: 'custom', label: '⚙️ 自訂', desc: '逐項勾選下面兩軸' },
]
const READ_LABELS: Record<keyof api.WatchToggleMap, string> = {
  filenames: '檔名與結構', readme: 'README 文件', deps: '依賴清單', code: '原始碼', git: '提交歷史',
}
const OUT_LABELS: Record<keyof api.OutboundToggleMap, string> = {
  summary: '話題摘要', docs: '文件內容', deps: '依賴清單', code: '程式碼片段', git: '提交歷史',
}
const TYPE_META: Record<string, { label: string; cls: string }> = {
  risk: { label: '🚨 風險', cls: 'bg-red-500/10 text-red-600 dark:text-red-400' },
  borrow: { label: '💡 借鑑', cls: 'bg-blue-500/10 text-blue-600 dark:text-blue-400' },
  upgrade: { label: '⬆️ 升級', cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  synergy: { label: '🔗 協同', cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400' },
  monitor: { label: '👁️ 追蹤', cls: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400' },
}

const pendingCount = computed(() => proposals.value.filter((p) => p.status === 'pending').length)

async function refresh() {
  loading.value = true
  try {
    const [t, p, b] = await Promise.all([
      api.getWatchTargets(),
      api.getProposals(),
      api.getBackupStatus().catch(() => null),
    ])
    targets.value = t
    proposals.value = p
    backup.value = b
  } catch (e) {
    toast.error('載入監看資料失敗', { description: String(e) })
  } finally {
    loading.value = false
  }
}

watch(() => ui.showWatchModal, (open) => { if (open) refresh() })

async function addTarget() {
  if (!newName.value.trim() || !newPath.value.trim()) {
    toast.error('請填寫名稱與資料夾路徑')
    return
  }
  try {
    await api.createWatchTarget({
      name: newName.value.trim(),
      path: newPath.value.trim(),
      preset: newPreset.value,
      ...(newPreset.value === 'custom' ? { read_scope: customRead.value, outbound_consent: customOut.value } : {}),
    })
    toast.success(`已加入監看：${newName.value.trim()}`)
    newName.value = ''
    newPath.value = ''
    showAdd.value = false
    refresh()
  } catch (e) {
    toast.error('加入失敗', { description: String(e) })
  }
}

async function scan(t: WatchTarget) {
  scanningId.value = t.id
  try {
    await api.scanWatchTarget(t.id)
    toast.success(`掃描已排程：${t.name}`, { description: '風險檢查立即完成，指紋更新約需數秒' })
    setTimeout(refresh, 2500)
    setTimeout(refresh, 9000)
  } catch (e) {
    toast.error('掃描失敗', { description: String(e) })
  } finally {
    scanningId.value = null
  }
}

async function setPreset(t: WatchTarget, preset: WatchPreset) {
  try {
    const updated = await api.updateWatchTarget(t.id, { preset })
    Object.assign(t, updated)
  } catch (e) {
    toast.error('更新失敗', { description: String(e) })
  }
}

async function toggleRead(t: WatchTarget, key: keyof api.WatchToggleMap) {
  const next = { ...t.read_scope, [key]: !t.read_scope[key] }
  const updated = await api.updateWatchTarget(t.id, { preset: 'custom', read_scope: next })
  Object.assign(t, updated)
}

async function toggleOut(t: WatchTarget, key: keyof api.OutboundToggleMap) {
  const next = { ...t.outbound_consent, [key]: !t.outbound_consent[key] }
  const updated = await api.updateWatchTarget(t.id, { preset: 'custom', outbound_consent: next })
  Object.assign(t, updated)
}

async function toggleActive(t: WatchTarget) {
  const updated = await api.updateWatchTarget(t.id, { is_active: !t.is_active })
  Object.assign(t, updated)
}

async function removeTarget(t: WatchTarget) {
  await api.deleteWatchTarget(t.id)
  targets.value = targets.value.filter((x) => x.id !== t.id)
  toast.success(`已移除 ${t.name}`)
}

function openCorrection(p: Proposal) {
  correctingId.value = correctingId.value === p.id ? null : p.id
  corr.value = { impact: p.impact, confidence: p.confidence, effort: p.effort, reason: '' }
}

async function decide(p: Proposal, status: 'approved' | 'dismissed') {
  const corrections = correctingId.value === p.id
    ? { user_impact: corr.value.impact, user_confidence: corr.value.confidence, user_effort: corr.value.effort, reason: corr.value.reason }
    : {}
  try {
    await api.decideProposal(p.id, { status, ...corrections })
    p.status = status
    toast.success(status === 'approved' ? '已核准提案' : '已忽略提案', {
      description: correctingId.value === p.id ? '分數修正已記錄，將用於校準模型' : undefined,
    })
    correctingId.value = null
  } catch (e) {
    toast.error('操作失敗', { description: String(e) })
  }
}

async function backupNow() {
  backingUp.value = true
  try {
    await api.runBackupNow()
    toast.success('備份已排程')
    setTimeout(refresh, 3000)
  } catch (e) {
    toast.error('備份失敗', { description: String(e) })
  } finally {
    backingUp.value = false
  }
}

function fmtTime(s?: string | null) {
  return s ? new Date(s).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '尚未掃描'
}
function fmtSize(n?: number) {
  if (!n) return ''
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1024).toFixed(0)} KB`
}
</script>

<template>
  <Dialog :open="ui.showWatchModal" @update:open="(v: boolean) => (ui.showWatchModal = v)">
    <DialogContent class="max-h-[85vh] w-[min(94vw,720px)] overflow-y-auto sm:max-w-[720px]">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <ScanEye class="size-4.5" /> 監看中心 — 本地提案引擎
        </DialogTitle>
        <DialogDescription>
          監看你的專案資料夾，產生風險與優化提案。送雲端分析前一律自動遮蔽機密。
        </DialogDescription>
      </DialogHeader>

      <!-- Tabs -->
      <div class="mb-3 flex items-center gap-1 rounded-full bg-black/[0.04] p-1 dark:bg-white/[0.06]">
        <button v-for="t in (['targets','proposals','backup'] as const)" :key="t"
          class="flex-1 rounded-full px-3 py-1.5 text-sm font-medium transition-all"
          :class="tab === t ? 'bg-white shadow-sm dark:bg-white/[0.14]' : 'text-muted-foreground'"
          @click="tab = t">
          {{ t === 'targets' ? '監看目標' : t === 'proposals' ? `提案${pendingCount ? ` · ${pendingCount} 待決` : ''}` : '備份' }}
        </button>
      </div>

      <Loader2 v-if="loading" class="mx-auto size-5 animate-spin text-muted-foreground" />

      <!-- ── Targets ── -->
      <div v-else-if="tab === 'targets'" class="space-y-3">
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted-foreground">權限兩軸：<b>讀取</b>=本機可看什麼 · <b>外送</b>=可送雲端 AI 分析什麼</p>
          <Button size="sm" variant="secondary" @click="showAdd = !showAdd">
            <Plus class="size-3.5" /> {{ showAdd ? '收起' : '新增目標' }}
          </Button>
        </div>

        <!-- Add form -->
        <div v-if="showAdd" class="rounded-xl border border-black/[0.06] bg-black/[0.02] p-3 space-y-2.5 dark:border-white/[0.08] dark:bg-white/[0.03]">
          <div class="grid grid-cols-[1fr_2fr] gap-2">
            <input v-model="newName" placeholder="名稱（如 MyProject）"
              class="rounded-lg border border-black/10 bg-white/80 px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-black/10 dark:border-white/10 dark:bg-white/5" />
            <input v-model="newPath" placeholder="資料夾完整路徑（如 C:\Projects\MyProject）"
              class="rounded-lg border border-black/10 bg-white/80 px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-black/10 dark:border-white/10 dark:bg-white/5" />
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="p in PRESETS" :key="p.id" :title="p.desc"
              class="rounded-full px-3 py-1 text-xs font-medium transition-all"
              :class="newPreset === p.id ? 'bg-foreground text-background' : 'bg-black/[0.05] text-muted-foreground dark:bg-white/[0.08]'"
              @click="newPreset = p.id">
              {{ p.label }}
            </button>
          </div>
          <p class="text-[11px] text-muted-foreground">{{ PRESETS.find((p) => p.id === newPreset)?.desc }}</p>
          <div v-if="newPreset === 'custom'" class="grid gap-2 sm:grid-cols-2">
            <div class="space-y-1 rounded-lg bg-white/60 p-2 text-xs dark:bg-white/[0.04]">
              <p class="font-semibold">讀取軸</p>
              <label v-for="(label, key) in READ_LABELS" :key="key" class="flex cursor-pointer items-center justify-between gap-2">
                {{ label }}
                <input type="checkbox" v-model="(customRead as any)[key]" class="accent-foreground" />
              </label>
            </div>
            <div class="space-y-1 rounded-lg bg-white/60 p-2 text-xs dark:bg-white/[0.04]">
              <p class="font-semibold">外送軸（送雲端 AI）</p>
              <label v-for="(label, key) in OUT_LABELS" :key="key" class="flex cursor-pointer items-center justify-between gap-2">
                {{ label }}
                <input type="checkbox" v-model="(customOut as any)[key]" class="accent-foreground" />
              </label>
            </div>
          </div>
          <Button size="sm" class="w-full" @click="addTarget">開始監看</Button>
        </div>

        <!-- Target cards -->
        <p v-if="!targets.length" class="py-6 text-center text-sm text-muted-foreground">
          尚無監看目標。請選擇要監看的本機專案資料夾；完成掃描後才會依取得的內容產生建議。
        </p>
        <div v-for="t in targets" :key="t.id"
          class="rounded-xl border border-black/[0.06] bg-white/70 p-3 dark:border-white/[0.08] dark:bg-white/[0.03]">
          <div class="flex items-center gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-sm font-semibold">{{ t.name }}</span>
                <Badge variant="secondary" class="shrink-0 text-[10px]">{{ PRESETS.find((p) => p.id === t.preset)?.label ?? t.preset }}</Badge>
                <Badge v-if="!t.is_active" variant="secondary" class="shrink-0 text-[10px] opacity-60">停用中</Badge>
              </div>
              <p class="truncate text-[11px] text-muted-foreground" :title="t.path">{{ t.path }}</p>
            </div>
            <Button size="sm" variant="secondary" :disabled="scanningId === t.id || !t.is_active" @click="scan(t)">
              <Loader2 v-if="scanningId === t.id" class="size-3.5 animate-spin" />
              <RefreshCw v-else class="size-3.5" /> 掃描
            </Button>
            <Button size="icon" variant="ghost" class="size-8" :title="expandedId === t.id ? '收起權限' : '權限設定'"
              @click="expandedId = expandedId === t.id ? null : t.id">
              <component :is="expandedId === t.id ? ChevronDown : ChevronRight" class="size-4" />
            </Button>
            <Button size="icon" variant="ghost" class="size-8" :title="t.is_active ? '停用' : '啟用'" @click="toggleActive(t)">
              <Power class="size-4" :class="t.is_active ? 'text-emerald-500' : 'text-muted-foreground'" />
            </Button>
            <Button size="icon" variant="ghost" class="size-8 text-red-500/70" title="刪除" @click="removeTarget(t)">
              <Trash2 class="size-4" />
            </Button>
          </div>
          <p class="mt-1 text-[11px] text-muted-foreground">上次掃描：{{ fmtTime(t.last_scan_at) }}</p>

          <!-- Permission editor -->
          <div v-if="expandedId === t.id" class="mt-2.5 space-y-2 border-t border-black/[0.05] pt-2.5 dark:border-white/[0.06]">
            <div class="flex flex-wrap gap-1.5">
              <button v-for="p in PRESETS.slice(0, 3)" :key="p.id" :title="p.desc"
                class="rounded-full px-2.5 py-0.5 text-[11px] transition-all"
                :class="t.preset === p.id ? 'bg-foreground text-background' : 'bg-black/[0.05] text-muted-foreground dark:bg-white/[0.08]'"
                @click="setPreset(t, p.id)">
                {{ p.label }}
              </button>
              <span class="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <ShieldCheck class="size-3" /> 機密一律遮蔽
              </span>
            </div>
            <div class="grid gap-2 sm:grid-cols-2">
              <div class="space-y-1 rounded-lg bg-black/[0.03] p-2 dark:bg-white/[0.04]">
                <p class="text-[11px] font-semibold">讀取（本機）</p>
                <button v-for="(label, key) in READ_LABELS" :key="key"
                  class="flex w-full items-center justify-between rounded-md px-1.5 py-0.5 text-xs"
                  :class="t.read_scope[key] ? 'text-foreground' : 'text-muted-foreground/60'"
                  @click="toggleRead(t, key)">
                  {{ label }}
                  <span class="ml-2 h-4 w-7 rounded-full p-0.5 transition-colors"
                    :class="t.read_scope[key] ? 'bg-emerald-500/80' : 'bg-black/15 dark:bg-white/15'">
                    <span class="block size-3 rounded-full bg-white transition-transform"
                      :class="t.read_scope[key] ? 'translate-x-3' : ''" />
                  </span>
                </button>
              </div>
              <div class="space-y-1 rounded-lg bg-black/[0.03] p-2 dark:bg-white/[0.04]">
                <p class="text-[11px] font-semibold">外送（雲端 AI）</p>
                <button v-for="(label, key) in OUT_LABELS" :key="key"
                  class="flex w-full items-center justify-between rounded-md px-1.5 py-0.5 text-xs"
                  :class="t.outbound_consent[key] ? 'text-foreground' : 'text-muted-foreground/60'"
                  @click="toggleOut(t, key)">
                  {{ label }}
                  <span class="ml-2 h-4 w-7 rounded-full p-0.5 transition-colors"
                    :class="t.outbound_consent[key] ? 'bg-emerald-500/80' : 'bg-black/15 dark:bg-white/15'">
                    <span class="block size-3 rounded-full bg-white transition-transform"
                      :class="t.outbound_consent[key] ? 'translate-x-3' : ''" />
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Proposals ── -->
      <div v-else-if="tab === 'proposals'" class="space-y-2.5">
        <p v-if="!proposals.length" class="py-6 text-center text-sm text-muted-foreground">
          還沒有提案。掃描監看目標後，這裡會出現風險與優化建議卡。
        </p>
        <div v-for="p in proposals" :key="p.id"
          class="rounded-xl border border-black/[0.06] bg-white/70 p-3 dark:border-white/[0.08] dark:bg-white/[0.03]">
          <div class="flex items-start gap-2">
            <span class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
              :class="TYPE_META[p.proposal_type]?.cls ?? TYPE_META.monitor.cls">
              {{ TYPE_META[p.proposal_type]?.label ?? p.proposal_type }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold leading-snug">{{ p.title_l1 || '（無標題）' }}</p>
              <p class="mt-0.5 text-xs text-muted-foreground">{{ p.summary_l1 }}</p>
              <p class="mt-1.5 text-[11px] text-muted-foreground">
                🎯 影響 {{ p.impact }} · 🔍 信心 {{ p.confidence }} · 🏗️ 成本 {{ p.effort }}
                <template v-if="p.user_impact != null"> · 已修正 {{ p.user_impact }}/{{ p.user_confidence }}/{{ p.user_effort }}</template>
              </p>
              <div v-if="p.deep_analysis" class="mt-2">
                <button type="button" @click="toggleEvidence(p.id)" class="text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400">
                  {{ expandedEvidence[p.id] ? '▲ 收起模組雙邊證據鏈' : '▼ 查看模組雙邊證據鏈' }}
                </button>
                <div v-if="expandedEvidence[p.id]" class="mt-1.5 whitespace-pre-wrap rounded-lg bg-black/[0.04] p-2.5 font-mono text-[11px] leading-relaxed dark:bg-white/[0.05]">
                  {{ p.deep_analysis }}
                </div>
              </div>
            </div>
          </div>
          <div v-if="p.status === 'pending'" class="mt-2 flex items-center gap-1.5">
            <Button size="sm" @click="decide(p, 'approved')"><CheckCircle2 class="size-3.5" /> 核准</Button>
            <Button size="sm" variant="secondary" @click="decide(p, 'dismissed')"><XCircle class="size-3.5" /> 忽略</Button>
            <Button size="sm" variant="ghost" @click="openCorrection(p)">
              {{ correctingId === p.id ? '取消修正' : '修正分數' }}
            </Button>
          </div>
          <Badge v-else variant="secondary" class="mt-2 text-[10px]"
            :class="p.status === 'approved' ? 'text-emerald-600' : 'opacity-60'">
            {{ p.status === 'approved' ? '✓ 已核准' : '已忽略' }} · {{ fmtTime(p.created_at) }}
          </Badge>

          <div v-if="correctingId === p.id && p.status === 'pending'"
            class="mt-2 space-y-2 rounded-lg bg-black/[0.03] p-2.5 dark:bg-white/[0.04]">
            <div class="grid grid-cols-3 gap-2">
              <label class="text-[11px]">🎯 影響
                <input type="number" min="0" max="10" step="0.5" v-model.number="corr.impact"
                  class="mt-0.5 w-full rounded-md border border-black/10 bg-white/80 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/10" />
              </label>
              <label class="text-[11px]">🔍 信心
                <input type="number" min="0" max="10" step="0.5" v-model.number="corr.confidence"
                  class="mt-0.5 w-full rounded-md border border-black/10 bg-white/80 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/10" />
              </label>
              <label class="text-[11px]">🏗️ 成本
                <input type="number" min="0" max="10" step="0.5" v-model.number="corr.effort"
                  class="mt-0.5 w-full rounded-md border border-black/10 bg-white/80 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/10" />
              </label>
            </div>
            <input v-model="corr.reason" placeholder="修正原因（選填，如：影響沒那麼大）"
              class="w-full rounded-md border border-black/10 bg-white/80 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/10" />
            <p class="text-[10px] text-muted-foreground">修正會與 AI 原始分數一併保存，用於校準未來的本地評分模型。</p>
          </div>
        </div>
      </div>

      <!-- ── Backup ── -->
      <div v-else class="space-y-3">
        <div class="rounded-xl border border-black/[0.06] bg-white/70 p-3 dark:border-white/[0.08] dark:bg-white/[0.03]">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <HardDriveDownload class="size-4 text-muted-foreground" />
              <div>
                <p class="text-sm font-semibold">資料庫自動每日備份</p>
                <p class="text-[11px] text-muted-foreground">
                  {{ backup?.sink === 'off' ? '已停用' : `每天 ${String(backup?.backup_hour ?? 4).padStart(2, '0')}:00 後自動執行 · 保留 ${backup?.keep ?? 14} 份` }}
                </p>
              </div>
            </div>
            <Badge variant="secondary" class="uppercase">{{ backup?.sink ?? 'local' }}</Badge>
          </div>
          <p class="mt-2 text-[11px] text-muted-foreground">位置：{{ backup?.backup_dir }}</p>
          <p class="mt-1 text-[11px] text-muted-foreground">
            想備到雲端？在 <code>.env</code> 設 <code>BACKUP_SINK=rclone</code>（支援 40+ 雲端）或 <code>git</code>（附版本歷史）。
          </p>
          <Button size="sm" class="mt-2" :disabled="backingUp || backup?.sink === 'off'" @click="backupNow">
            <Loader2 v-if="backingUp" class="size-3.5 animate-spin" />
            <HardDriveDownload v-else class="size-3.5" /> 立即備份
          </Button>
        </div>
        <div v-if="backup?.runs?.length" class="space-y-1">
          <p class="text-xs font-semibold text-muted-foreground">最近執行</p>
          <div v-for="r in backup.runs.slice(0, 8)" :key="r.id"
            class="flex items-center justify-between rounded-lg bg-black/[0.03] px-2.5 py-1.5 text-xs dark:bg-white/[0.04]">
            <span class="inline-flex items-center gap-1.5">
              <CheckCircle2 v-if="r.status === 'ok'" class="size-3.5 text-emerald-500" />
              <XCircle v-else class="size-3.5 text-red-500" />
              {{ fmtTime(r.created_at) }}
            </span>
            <span class="text-muted-foreground">{{ fmtSize(r.size_bytes) || r.error?.slice(0, 40) }}</span>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
