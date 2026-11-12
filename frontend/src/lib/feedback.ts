/**
 * Where "回報問題" in the avatar menu leads. For now a new GitHub issue on the public repo;
 * if the people trying OmniKeep do not use GitHub, point FEEDBACK_BASE_URL at a shared
 * document instead (then the prefilled title and body are simply not used). No runtime
 * imports: the node tests load this file.
 */
export const FEEDBACK_BASE_URL = 'https://github.com/b40609/OmniKeep/issues/new'

const BODY = [
  '**發生什麼事**（存的連結失敗？摘要不對？搜尋找不到？卡在哪一步？）',
  '',
  '',
  '**預期會怎樣**',
  '',
  '',
  '> 這個頁面是公開的，請不要貼存取金鑰、私人收藏的內容或個人資料。',
  '',
].join('\n')

/** The address to open; the version is added so a report says which build it came from. */
export function feedbackUrl(version: string): string {
  if (!FEEDBACK_BASE_URL.includes('github.com')) return FEEDBACK_BASE_URL
  const params = new URLSearchParams({ title: '[回報] ', body: `${BODY}\n版本：OmniKeep ${version}` })
  return `${FEEDBACK_BASE_URL}?${params.toString()}`
}
