<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Keyboard, Loader2 } from 'lucide-vue-next'
import ConfirmDialog from '@/components/ui/confirm/ConfirmDialog.vue'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import FieldRow from './FieldRow.vue'
import { getSettingsAudit, importEnvSettings, regeneratePushKeys, type SettingValue, type SettingsAuditEntry } from '@/lib/api'
import { useSettingsForm } from '@/composables/useSettingsForm'
import { AUDIT_ACTION_TEXT, settingLabel } from '@/lib/settingsText'
import { useUiStore } from '@/stores/ui'

/**
 * 設定 › 進階: sign-in on this computer, how credentials are encrypted, the values the
 * server needs before it starts (read-only), and the change log. The only place that
 * mentions .env and the master key file.
 */
const ui = useUiStore()
const form = useSettingsForm()
const snapshot = form.snapshot

function display(value: SettingValue | undefined) {
  if (Array.isArray(value)) return value.length ? value.join('、') : '（空）'
  if (typeof value === 'boolean') return value ? '開' : '關'
  return value === '' || value === undefined ? '（空）' : String(value)
}

const BOOTSTRAP_TEXT: Record<string, string> = {
  HOST: '監聽位址', PORT: '連接埠', DATABASE_PATH: '資料庫位置', API_KEY: '存取金鑰',
  LOCAL_AUTO_LOGIN: '這台電腦免登入',
}

/* Import from .env */
const importing = ref(false)
const importable = computed(() => (snapshot.value?.env_importable ?? []).map((k) => settingLabel(k, form.byKey.value.get(k)?.label)))
async function importEnv() {
  importing.value = true
  try {
    const result = await importEnvSettings()
    form.apply(result)
    ui.settingsVersion++
    if (auditLoaded.value) void loadAudit()
    toast.success(`已匯入 ${result.imported?.length ?? 0} 項設定`, { description: '之後可以把 .env 裡對應的行刪掉。' })
  } catch (e) {
    toast.error('匯入失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    importing.value = false
  }
}

/* Push key pair */
const regenerating = ref(false)
const confirmingPush = ref(false)
const pushWarning = computed(() => {
  const devices = snapshot.value?.push.subscriptions ?? 0
  return devices
    ? `目前開啟通知的 ${devices} 台裝置都會收不到通知，要在每台裝置重新開啟。`
    : '目前沒有裝置開啟通知，不會影響任何裝置。'
})
async function regeneratePush() {
  regenerating.value = true
  try {
    const result = await regeneratePushKeys()
    form.apply(result)
    ui.settingsVersion++
    confirmingPush.value = false
    if (auditLoaded.value) void loadAudit()
    toast.success('已產生新的推播金鑰', {
      description: result.removed_subscriptions ? `已移除 ${result.removed_subscriptions} 台舊裝置，請在各裝置重新開啟通知。` : undefined,
    })
  } catch (e) {
    toast.error('無法產生推播金鑰', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    regenerating.value = false
  }
}

/* Change log */
const audit = ref<SettingsAuditEntry[]>([])
const auditMore = ref(false)
const auditLoading = ref(false)
const auditError = ref('')
const auditLoaded = ref(false)

async function loadAudit(more = false) {
  auditLoading.value = true
  auditError.value = ''
  try {
    const before = more ? audit.value[audit.value.length - 1]?.id : undefined
    const page = await getSettingsAudit(before)
    audit.value = more ? [...audit.value, ...page.entries] : page.entries
    auditMore.value = page.has_more
    auditLoaded.value = true
  } catch (e) {
    auditError.value = e instanceof Error ? e.message : String(e)
  } finally {
    auditLoading.value = false
  }
}

function auditTime(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

onMounted(loadAudit)
</script>

<template>
  <template v-if="snapshot">
    <!-- A server from before this switch existed lists it under 啟動設定 instead -->
    <SettingBlock v-if="form.byKey.value.has('LOCAL_AUTO_LOGIN')" id="login" title="登入">
      <FieldRow field-key="LOCAL_AUTO_LOGIN" auto />
    </SettingBlock>

    <SettingBlock id="encryption" title="金鑰加密" description="在設定裡輸入的金鑰會先加密才存進資料庫，備份檔裡只有加密後的內容。">
      <SettingRow
        name="主金鑰"
        :help="snapshot.secret_key.source === 'env'
          ? '解密用的主金鑰來自環境變數 OMNIKEEP_SECRET_KEY。'
          : '解密用的主金鑰存在下面這個檔案，不會進入備份。搬到新電腦時要一起帶過去；遺失的話，重新輸入各個金鑰即可。'"
        stacked
      >
        <p v-if="snapshot.secret_key.path" class="set-mono set-text">
          {{ snapshot.secret_key.path }}<template v-if="!snapshot.secret_key.exists">（第一次儲存金鑰時建立）</template>
        </p>
      </SettingRow>
      <SettingRow name="搬到新電腦" help="先停止舊電腦上的服務，再把資料庫和主金鑰檔複製到新電腦的同一個資料夾。主金鑰檔放在別處時，用 OMNIKEEP_SECRET_KEY_FILE 指到它。" />
      <SettingRow name="更換主金鑰" help="所有金鑰會改用新的主金鑰重新加密，不必停止服務。舊的主金鑰另存成同資料夾的 .bak 檔，還原更換前的備份時會用到。" stacked>
        <p class="set-text">在伺服器的專案資料夾執行 <code>python scripts/rotate_secret_key.py</code></p>
      </SettingRow>
    </SettingBlock>

    <SettingBlock id="bootstrap" title="啟動設定" description="服務啟動、開資料庫之前就要用到，所以留在 .env，這裡只能看。">
      <SettingRow v-for="row in snapshot.bootstrap" :key="row.key" :name="BOOTSTRAP_TEXT[row.key] ?? row.key" :help="row.key">
        <span class="set-mono max-w-[26rem] text-right text-muted-foreground max-sm:max-w-[45vw]">{{ display(row.value) }}</span>
      </SettingRow>
    </SettingBlock>

    <SettingBlock id="env" title="從 .env 匯入">
      <SettingRow
        :name="importable.length ? `有 ${importable.length} 項設定還寫在 .env` : '沒有需要匯入的設定'"
        :help="importable.length ? `${importable.join('、')}。匯入後改在這裡管理，之後可以把 .env 裡對應的行刪掉。` : '所有可以在這裡管理的設定都已經在這裡。'"
      >
        <button v-if="importable.length" type="button" class="set-button" :disabled="importing" @click="importEnv">
          <Loader2 v-if="importing" class="animate-spin" aria-hidden="true" />
          匯入
        </button>
      </SettingRow>
    </SettingBlock>

    <SettingBlock id="push-keys" title="推播金鑰" description="伺服器用來簽發通知的一組金鑰，啟動時自動產生。">
      <SettingRow
        :name="snapshot.push.undecryptable ? '無法解密' : snapshot.push.ready ? '已就緒' : '還沒有推播金鑰'"
        :help="snapshot.push.undecryptable
          ? '主金鑰和當初加密時不同，通知暫停中。把原本的主金鑰檔放回去就會恢復；找不回來的話重新產生一組，各裝置再重新開啟通知。'
          : snapshot.push.ready
            ? `${snapshot.push.source === 'env' ? '來自 .env' : '自動產生，加密存放'}。目前 ${snapshot.push.subscriptions} 台裝置開啟通知。`
            : '伺服器下次啟動時會自動產生，也可以現在產生。'"
      >
        <button v-if="!snapshot.push.ready" type="button" class="set-button" :disabled="regenerating" @click="confirmingPush = true">
          {{ snapshot.push.undecryptable ? '重新產生' : '產生' }}
        </button>
      </SettingRow>
    </SettingBlock>

    <SettingBlock id="audit" title="變更紀錄" description="哪個設定在什麼時候被修改、清除或匯入。只記名稱和動作，不記任何值。">
      <p v-if="auditError" class="set-error py-3">無法讀取變更紀錄：{{ auditError }}</p>
      <p v-else-if="auditLoaded && !audit.length" class="set-text py-3">還沒有任何變更。</p>
      <p v-else-if="auditLoading && !audit.length" class="set-text py-3">讀取中…</p>
      <table v-if="audit.length" class="set-table">
        <thead>
          <tr>
            <th scope="col">時間</th>
            <th scope="col">設定</th>
            <th scope="col">動作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in audit" :key="entry.id">
            <td>{{ auditTime(entry.created_at) }}</td>
            <td>{{ settingLabel(entry.key, entry.label) }}</td>
            <td class="whitespace-nowrap">{{ AUDIT_ACTION_TEXT[entry.action] ?? entry.action }}</td>
          </tr>
        </tbody>
      </table>
      <template v-if="auditMore" #foot>
        <button type="button" class="set-button" :disabled="auditLoading" @click="loadAudit(true)">
          <Loader2 v-if="auditLoading" class="animate-spin" aria-hidden="true" />
          載入更早的紀錄
        </button>
      </template>
    </SettingBlock>

    <SettingBlock id="shortcuts" title="鍵盤快捷鍵">
      <SettingRow name="查看所有快捷鍵" help="在收藏清單按 ? 也能開啟。">
        <button type="button" class="set-button" @click="ui.showShortcutsModal = true"><Keyboard aria-hidden="true" />查看</button>
      </SettingRow>
    </SettingBlock>

    <ConfirmDialog
      :open="confirmingPush"
      title="產生新的推播金鑰？"
      :description="pushWarning"
      confirm-label="產生推播金鑰"
      :busy="regenerating"
      @update:open="confirmingPush = $event"
      @confirm="regeneratePush"
    />
  </template>
</template>
