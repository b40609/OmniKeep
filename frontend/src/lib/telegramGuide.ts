/**
 * How to connect Telegram, said once: the first-run guide and 設定 › 收錄管道 show the same
 * three steps. No runtime imports: the node tests load this file on its own.
 */

/** The full walk-through (docs/telegram_bot.md), readable in a browser. */
export const TELEGRAM_DOC_URL = 'https://github.com/b40609/OmniKeep/blob/main/docs/telegram_bot.md'

export const TELEGRAM_STEPS: { title: string; body: string }[] = [
  {
    title: '建立機器人',
    body: '在 Telegram 找 @BotFather，傳 /newbot，照它的提示取名稱和使用者名稱（使用者名稱要以 bot 結尾）。完成後它會給你一串權杖。',
  },
  {
    title: '貼上權杖',
    body: '把權杖貼到「機器人權杖」並儲存。權杖會加密後存在這台伺服器，之後不會再顯示。',
  },
  {
    title: '配對你的帳號',
    body: '按「產生配對連結」，用你的 Telegram 開啟連結並按「開始」。機器人回覆「已綁定」就完成了，之後把連結傳給它就會收進來。',
  },
]

/** What a token looks like, for the box's placeholder (the example in Telegram's own documentation). */
export const TELEGRAM_TOKEN_EXAMPLE = '110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'

/**
 * What looks wrong with a pasted token, or '' when it has the usual shape (digits, a colon,
 * then letters, digits, - and _). Only a hint: the server is what accepts or refuses it.
 */
export function tokenProblem(text: string): string {
  const token = text.trim()
  if (!token) return ''
  if (/\s/.test(token)) return '權杖中間不會有空白或換行，請重新複製一次。'
  if (!/^\d+:[A-Za-z0-9_-]{20,}$/.test(token)) return '權杖通常是「一串數字、冒號，再接一長串英數字」。請確認複製的是 BotFather 給的整串權杖。'
  return ''
}
