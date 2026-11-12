/**
 * Names and one-line descriptions of the settings, in the words of DESIGN.md.
 * The server describes each setting too (app/app_settings.py); its text is the
 * fallback for a setting this file does not know.
 */

export interface SettingText {
  label: string
  help?: string
}

export const SETTING_TEXT: Record<string, SettingText> = {
  ANALYSIS_DEPTH: { label: '分析深度', help: '摘要和剖析要寫多細。只影響之後的新收藏，分析過的不會重跑。' },
  USER_BACKGROUND: { label: '使用者背景', help: '你的身分、專長和手上的專案。工程與工具類的收藏會多一段結合背景的建議；留空就不加。' },
  LOCAL_HARDWARE: { label: '本機硬體', help: '這台電腦的處理器、顯示卡和記憶體。分析 AI 模型時會評估能不能在這台跑；留空則只列出需求。' },

  TELEGRAM_BOT_TOKEN: { label: '機器人權杖', help: '在 Telegram 向 @BotFather 建立機器人後取得。儲存後機器人立即重新連線。' },
  TELEGRAM_ALLOWED_USER_IDS: { label: '已綁定的帳號', help: '只有這些 Telegram 帳號能把連結傳給機器人。用配對連結新增；移除後立即失去存取權。' },
  LINE_CHANNEL_SECRET: { label: '頻道密鑰', help: 'LINE 後台的 Channel secret。' },
  LINE_CHANNEL_ACCESS_TOKEN: { label: '頻道存取權杖', help: 'LINE 後台的 Channel access token。' },
  LINE_ALLOWED_USER_IDS: { label: '允許的 LINE 帳號', help: '只有這些 LINE User ID 能把連結傳進來。' },
  GITHUB_TOKEN: { label: 'GitHub 權杖', help: '探索讀取 GitHub 來源時使用，可以提高 API 額度。不需要任何寫入權限。' },

  BRAIN_PROVIDER: { label: '回答來源', help: '提問時先用哪一種模型。' },
  BRAIN_BASE_URL: { label: 'Ollama 位址', help: '例如 http://127.0.0.1:11434' },
  BRAIN_MODEL: { label: '本機模型', help: '要先在 Ollama 下載好。' },
  BRAIN_MAX_CITATIONS: { label: '引用上限', help: '一次回答最多引用幾則收藏。' },
  BRAIN_NUM_CTX: { label: '上下文長度', help: '本機模型一次能讀的 token 數。太小會截掉引用的內容，越大越吃顯示卡記憶體。' },

  BACKUP_SINK: { label: '備份方式', help: '備份檔除了留在這台電腦，還要不要送到別處。' },
  BACKUP_HOUR: { label: '每日備份時間', help: '幾點開始備份，0 到 23。' },
  BACKUP_KEEP: { label: '保留份數', help: '這台電腦上留最近幾份備份。' },
  BACKUP_RCLONE_REMOTE: { label: 'rclone 遠端', help: '例如 gdrive:OmniKeep。備份方式選 rclone 時使用。' },
  BACKUP_GIT_REPO_DIR: { label: 'git 資料夾', help: '私人 repo 在這台電腦上的路徑。備份方式選 git 時使用。' },

  VAPID_SUBJECT: { label: '推播聯絡資訊', help: 'mailto: 開頭的信箱，或 https 網址；推播服務用它聯絡你。留空則用專案網址。' },
  VAPID_PUBLIC_KEY: { label: '推播公鑰' },
  VAPID_PRIVATE_KEY: { label: '推播私鑰' },

  LOCAL_AUTO_LOGIN: { label: '這台電腦免登入', help: '在執行 OmniKeep 的這台電腦上開啟時，不用輸入存取金鑰。手機和其他裝置一律要輸入存取金鑰或配對碼。' },

  EXPERIMENT_RADAR: { label: '實驗功能：探索' },
  EXPERIMENT_WATCH: { label: '實驗功能：專案監看' },
  EXPERIMENT_DAILY_REVIEW: { label: '實驗功能：每日回顧' },
}

/** AI task lists, by slot id (the server's own labels use older names). */
export const SLOT_TEXT: Record<string, SettingText> = {
  analysis: { label: '分析', help: '收藏的摘要、分類與剖析。' },
  brain: { label: '提問', help: '用收藏的內容回答問題。清單用完後改用「分析」的清單。' },
  radar: { label: '探索', help: '探索的相關性評分與精選。清單用完或是空的，就用「分析」的清單。' },
  embeddings: { label: '語意搜尋', help: '把收藏轉成向量，供語意搜尋使用。換模型後，既有收藏要重建向量才找得到。' },
  video: { label: '影片', help: '直接看影片內容來分析。空的時候改用字幕或語音轉錄的文字。' },
}

export const AUDIT_ACTION_TEXT: Record<string, string> = {
  set: '修改', clear: '清除', reset: '重設', import: '從 .env 匯入', pair: 'Telegram 配對',
  generate: '自動產生', regenerate: '重新產生', rotate: '更換主金鑰', sync: '由 AI 連線同步', delete: '刪除',
}

/** Name of a setting in lists (change log, warnings); `fallback` is what the server calls it. */
export function settingLabel(key: string, fallback = ''): string {
  if (SETTING_TEXT[key]) return SETTING_TEXT[key].label
  if (key === '_secret_key') return '主金鑰'
  if (key.startsWith('ai_connection:')) return `AI 連線 #${key.split(':', 2)[1]}`
  if (key.startsWith('ai_slot:')) return `AI 用途：${SLOT_TEXT[key.split(':', 2)[1]]?.label ?? key.split(':', 2)[1]}`
  return fallback || key
}
