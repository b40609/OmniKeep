import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const wall = await load('../src/lib/wall.ts')
const theme = await load('../src/lib/themeMode.ts')

test('a cover is used only when it is a real image address, not a favicon', () => {
  const cover = 'https://opengraph.githubassets.com/abc/owner/repo'
  assert.equal(wall.usableCover(cover), cover)
  assert.equal(wall.usableCover('  ' + cover + ' '), cover)
  for (const none of ['', null, undefined, '   ', 'data:image/png;base64,AAAA', '/static/cover.png', 'javascript:alert(1)', 'https://']) {
    assert.equal(wall.usableCover(none), '', String(none))
  }
  for (const icon of [
    'https://www.google.com/s2/favicons?domain=example.com&sz=64',
    'http://google.com/s2/favicons?domain=example.com',
    'https://t3.gstatic.com/faviconV2?client=SOCIAL&url=https://example.com',
    'https://icons.duckduckgo.com/ip3/example.com.ico',
    'https://example.com/favicon.ico',
    'https://example.com/assets/favicon-32x32.png?v=2',
  ]) assert.equal(wall.usableCover(icon), '', icon)
  // "favicon" in a query string or an article slug is not a favicon file.
  assert.notEqual(wall.usableCover('https://cdn.example.com/og.png?from=/favicon.ico'), '')
  assert.notEqual(wall.usableCover('https://example.com/posts/favicon-guide/cover.jpg'), '')
})

test('only the rate-limited repository cards are asked for again, and only twice', () => {
  const card = 'https://opengraph.githubassets.com/abc/owner/repo'
  assert.equal(wall.coverRetryDelay(card, 0), 4000)
  assert.equal(wall.coverRetryDelay(card, 1), 15000)
  assert.equal(wall.coverRetryDelay(card, 2), null)
  // An expired or blocked address will not come back: no retry.
  assert.equal(wall.coverRetryDelay('https://scontent.example.net/v/expired.jpg', 0), null)
  assert.equal(wall.coverRetryDelay('https://example.com/?u=https://opengraph.githubassets.com/x', 0), null)
})

test('a saved title splits into a name and what it is, at the colon that separates them', () => {
  const split = (title) => { const { name, detail } = wall.splitTitle(title); return [name, detail] }
  assert.deepEqual(split('polars_ta：基於 Polars 的高效能向量化量化指標庫'), ['polars_ta', '基於 Polars 的高效能向量化量化指標庫'])
  assert.deepEqual(split('Kronos: A Foundation Model for Financial Markets'), ['Kronos', 'A Foundation Model for Financial Markets'])
  assert.deepEqual(split('Taste Skill:讓 Agent 有設計品味'), ['Taste Skill', '讓 Agent 有設計品味'])
  assert.deepEqual(split('  Playwright ：  跨瀏覽器自動化框架  '), ['Playwright', '跨瀏覽器自動化框架'])
  assert.deepEqual(split('Claude Code 自動去 AI 感 UI 重構工具：unslop'), ['Claude Code 自動去 AI 感 UI 重構工具：unslop', ''])   // 28 characters before the colon
  // No colon, or nothing on one side of it: the whole title is the name.
  assert.deepEqual(split('ThreadsPulse 開源專案與 Meta 生態客戶端隱私攔截架構'), ['ThreadsPulse 開源專案與 Meta 生態客戶端隱私攔截架構', ''])
  assert.deepEqual(split('結論：'), ['結論：', ''])
  assert.deepEqual(split('：只有說明'), ['：只有說明', ''])
  assert.deepEqual(split(''), ['', ''])
  assert.deepEqual(split(null), ['', ''])
  // More than 24 characters in front of the colon is a sentence, not a name.
  const long = '這是一個非常非常長而且顯然不是名稱的句子開頭部分啊：後面才是說明'
  assert.deepEqual(split(long), [long, ''])
  assert.deepEqual(split('剛好二十四個字的名稱一二三四五六七八九十一二三四：說明')[1], '說明')
  // Colons that are not separators: addresses, times, ratios, code.
  assert.deepEqual(split('https://example.com/a 的讀後筆記'), ['https://example.com/a 的讀後筆記', ''])
  assert.deepEqual(split('http://localhost:8080 連不上怎麼辦'), ['http://localhost:8080 連不上怎麼辦', ''])
  assert.deepEqual(split('每天 10:30 的站立會議怎麼開'), ['每天 10:30 的站立會議怎麼開', ''])
  assert.deepEqual(split('把封面裁成 16：9 的三種做法'), ['把封面裁成 16：9 的三種做法', ''])
  assert.deepEqual(split('std::vector 的擴容策略'), ['std::vector 的擴容策略', ''])
  assert.deepEqual(split('Re:Zero 的敘事結構'), ['Re:Zero 的敘事結構', ''])
  // The first real separator wins, even after a colon that does not count.
  assert.deepEqual(split('10:30 站立會議：三個常見問題'), ['10:30 站立會議', '三個常見問題'])
  assert.deepEqual(split('看 https://a.b 的教學：重點整理'), ['看 https://a.b 的教學', '重點整理'])
  assert.deepEqual(split('A：B：C'), ['A', 'B：C'])
})

test('covers fill the frame, except generated repository cards, which are shown whole', () => {
  assert.equal(wall.coverFit('https://opengraph.githubassets.com/abc/owner/repo'), 'pad')
  // An uploaded social preview can be any picture: it fills the frame like the rest.
  assert.equal(wall.coverFit('https://repository-images.githubusercontent.com/1/abc'), 'fill')
  assert.equal(wall.coverFit('https://i.ytimg.com/vi/abc/maxresdefault.jpg'), 'fill')
  assert.equal(wall.coverFit('https://example.com/?u=https://opengraph.githubassets.com/x'), 'fill')
})

test('a tall cover keeps its top in the 16:9 frame; a wide one is cut evenly at the sides', () => {
  assert.equal(wall.coverFocus(1080, 1350), 'top')     // a post screenshot
  assert.equal(wall.coverFocus(1000, 1000), 'top')
  assert.equal(wall.coverFocus(1200, 600), 'center')   // a 2:1 repository card
  assert.equal(wall.coverFocus(1280, 720), 'center')
  assert.equal(wall.coverFocus(1200, 800), 'center')   // 3:2 is close enough to the frame
  assert.equal(wall.coverFocus(0, 0), 'center')
})

test('an image that loads at icon size is treated as no cover', () => {
  assert.equal(wall.isIconSized(32, 32), true)
  assert.equal(wall.isIconSized(1, 1), true)
  assert.equal(wall.isIconSized(1200, 40), true)
  assert.equal(wall.isIconSized(64, 64), false)
  assert.equal(wall.isIconSized(1200, 630), false)
})

test('every item is one kind, and "project" means a github.com address', () => {
  const kind = (url, source_type = 'web') => wall.itemKind({ url, source_type })
  assert.equal(kind('https://github.com/owner/repo', 'github'), 'project')
  assert.equal(kind('https://github.com/owner/repo', 'web'), 'project')
  assert.equal(kind('https://www.github.com/owner/repo'), 'project')
  assert.equal(kind('https://owner.github.io/project/', 'github'), 'article')
  assert.equal(kind('https://gist.github.com/owner/abc'), 'article')
  assert.equal(kind('https://www.threads.net/@someone/post/abc', 'threads'), 'post')
  assert.equal(kind('https://www.threads.com/@someone/post/abc', 'web'), 'post')
  assert.equal(kind('https://www.facebook.com/groups/1/posts/2', 'web'), 'post')
  assert.equal(kind('https://x.com/someone/status/1'), 'post')
  assert.equal(kind('https://www.youtube.com/watch?v=abc', 'youtube'), 'video')
  assert.equal(kind('https://youtu.be/abc', 'web'), 'video')
  assert.equal(kind('https://m.youtube.com/shorts/abc'), 'video')
  assert.equal(kind('https://www.bilibili.com/video/BV1', 'bilibili'), 'video')
  assert.equal(kind('https://www.instagram.com/reel/abc/', 'reel'), 'video')
  assert.equal(kind('https://www.instagram.com/p/abc/', 'instagram'), 'post')
  assert.equal(kind('https://animations.dev/', 'web'), 'article')
  assert.equal(kind('https://example.com/feed/1', 'rss'), 'article')
  assert.equal(kind('note://abc', 'note'), 'article')
  assert.equal(kind('', 'github'), 'project')
  assert.equal(kind(null, null), 'article')
  // A look-alike host is not the site.
  assert.equal(kind('https://notgithub.com/owner/repo'), 'article')
  assert.equal(kind('https://fakeyoutube.com/watch'), 'article')
  assert.deepEqual(wall.KIND_TABS.map((tab) => tab.label), ['全部', '專案', '貼文', '影片', '文章'])
})

test('the text fallback names the source the way a person would', () => {
  const name = (url, source_type = 'web') => wall.sourceName({ url, source_type })
  assert.equal(name('https://www.facebook.com/groups/1/posts/2'), 'Facebook 貼文')
  assert.equal(name('https://github.com/owner/repo', 'github'), 'GitHub 專案')
  assert.equal(name('https://www.youtube.com/watch?v=abc', 'youtube'), 'YouTube 影片')
  assert.equal(name('https://www.threads.net/@a/post/b', 'threads'), 'Threads 貼文')
  assert.equal(name('https://www.animations.dev/learn'), 'animations.dev')
  assert.equal(name('note://abc', 'note'), '筆記')
  assert.equal(name('', 'web'), '筆記')
})

const item = (id, created_at, url = 'https://example.com/' + id, source_type = 'web') => ({ id, created_at, url, source_type })

test('the wall filters by kind and reorders without touching the loaded list', () => {
  const loaded = [
    item(1, '2026-11-11 08:00:00', 'https://github.com/a/b', 'github'),
    item(2, '2026-11-10 08:00:00', 'https://youtu.be/x', 'youtube'),
    item(3, '2026-11-09 08:00:00'),
    item(4, '2026-11-09 08:00:00', 'https://github.com/c/d', 'github'),
  ]
  const ids = (list) => list.map((entry) => entry.id)
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'all', 'server')), [1, 2, 3, 4])
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'project', 'server')), [1, 4])
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'video', 'server')), [2])
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'post', 'server')), [])
  // Oldest first; items saved at the same moment keep their order.
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'all', 'oldest')), [3, 4, 2, 1])
  assert.deepEqual(ids(wall.arrangeItems(loaded, 'project', 'oldest')), [4, 1])
  assert.deepEqual(ids(loaded), [1, 2, 3, 4])
  assert.notEqual(wall.arrangeItems(loaded, 'all', 'server'), loaded)
})

test('server timestamps without a zone are read as UTC', () => {
  assert.equal(wall.parseServerTime('2026-11-11 08:00:00').toISOString(), '2026-11-11T08:00:00.000Z')
  assert.equal(wall.parseServerTime('2026-11-11T08:00:00').toISOString(), '2026-11-11T08:00:00.000Z')
  assert.equal(wall.parseServerTime('2026-11-11T08:00:00Z').toISOString(), '2026-11-11T08:00:00.000Z')
  assert.equal(wall.parseServerTime('2026-11-11T16:00:00+08:00').toISOString(), '2026-11-11T08:00:00.000Z')
  assert.equal(wall.parseServerTime(''), null)
  assert.equal(wall.parseServerTime('不是時間'), null)
})

test('date sections: today, yesterday, a section per day for a week, then per month', () => {
  // Local-time constructors on both sides, so the result does not depend on the machine's zone.
  const now = new Date(2026, 10, 11, 15, 0, 0)
  const at = (y, m, d, h = 12) => new Date(y, m - 1, d, h, 0, 0).toISOString()
  const section = (...args) => wall.daySection(at(...args), now)
  assert.deepEqual(section(2026, 11, 11, 0), { key: 'd0', label: '今天' })
  assert.deepEqual(section(2026, 11, 11, 14), { key: 'd0', label: '今天' })
  assert.deepEqual(section(2026, 11, 10, 23), { key: 'd1', label: '昨天' })
  assert.deepEqual(section(2026, 11, 9), { key: 'd2', label: '2 天前' })
  assert.deepEqual(section(2026, 11, 5), { key: 'd6', label: '6 天前' })
  assert.deepEqual(section(2026, 11, 4), { key: 'm2026-11', label: '2026 年 11 月' })
  assert.deepEqual(section(2026, 10, 20), { key: 'm2026-10', label: '2026 年 10 月' })
  assert.deepEqual(section(2025, 12, 31), { key: 'm2025-12', label: '2025 年 12 月' })
  // A clock that is slightly ahead does not invent a "tomorrow".
  assert.deepEqual(section(2026, 11, 12, 1), { key: 'd0', label: '今天' })
  assert.deepEqual(wall.daySection('', now), { key: 'unknown', label: '更早' })
})

test('sections keep the list order, count every item once, and stay few for a long backlog', () => {
  const now = new Date(2026, 10, 11, 15, 0, 0)
  const at = (daysAgo) => new Date(2026, 10, 11 - daysAgo, 9, 0, 0).toISOString()
  const loaded = [0, 0, 1, 1, 1, 2, 9, 30, 31, 400].map((daysAgo, index) => item(index, at(daysAgo)))
  const sections = wall.groupByDay(loaded, now)
  assert.deepEqual(sections.map((s) => [s.label, s.items.length]), [
    ['今天', 2], ['昨天', 3], ['2 天前', 1], ['2026 年 11 月', 1], ['2026 年 10 月', 2], ['2025 年 10 月', 1],
  ])
  assert.deepEqual(sections.flatMap((s) => s.items.map((entry) => entry.id)), loaded.map((entry) => entry.id))
  // Oldest-first input gives the same sections in the opposite order.
  assert.deepEqual(wall.groupByDay(loaded.slice().reverse(), now).map((s) => s.label), sections.map((s) => s.label).reverse())
  // Two years of daily saves is still a short list of headings.
  const backlog = Array.from({ length: 730 }, (_, index) => item(index, at(index)))
  assert.ok(wall.groupByDay(backlog, now).length <= 7 + 25)
  assert.deepEqual(wall.groupByDay([], now), [])
})

test('the neutral theme is the default, and a theme someone picked is kept', () => {
  assert.equal(theme.startingTheme(null, null), 'neutral')
  // The old key was written with its default, so a stored "dark" was never necessarily a choice.
  assert.equal(theme.startingTheme(null, 'dark'), 'neutral')
  assert.equal(theme.startingTheme(null, 'oled'), 'oled')
  assert.equal(theme.startingTheme(null, 'light'), 'light')
  assert.equal(theme.startingTheme(null, 'system'), 'system')
  assert.equal(theme.startingTheme(null, 'garbage'), 'neutral')
  // Once the new key exists it wins, including an explicit return to the older dark theme.
  assert.equal(theme.startingTheme('dark', 'light'), 'dark')
  assert.equal(theme.startingTheme('neutral', 'oled'), 'neutral')
  assert.equal(theme.startingTheme('garbage', 'light'), 'light')
})

test('every dark theme carries the dark class; only the neutral one carries neutral', () => {
  assert.deepEqual(theme.themeClasses('neutral', false), { dark: true, oled: false, neutral: true })
  assert.deepEqual(theme.themeClasses('dark', false), { dark: true, oled: false, neutral: false })
  assert.deepEqual(theme.themeClasses('oled', false), { dark: true, oled: true, neutral: false })
  assert.deepEqual(theme.themeClasses('light', true), { dark: false, oled: false, neutral: false })
  assert.deepEqual(theme.themeClasses('system', true), { dark: true, oled: false, neutral: false })
  assert.deepEqual(theme.themeClasses('system', false), { dark: false, oled: false, neutral: false })
  assert.equal(theme.themeColor('neutral', false), '#0f0f0f')
  assert.equal(theme.themeColor('oled', false), '#000000')
  assert.equal(theme.themeColor('system', false), '#f4f5f7')
})

test('an item kept without analysis is told apart, and its summary shown without the tag', () => {
  assert.equal(wall.isNotAnalysed({ analysis_status: 'pending', origin: 'manual' }), true)
  assert.equal(wall.isNotAnalysed({ analysis_status: 'pending', origin: 'radar' }), false) // a radar stub waits for the radar
  assert.equal(wall.isNotAnalysed({ analysis_status: 'done' }), false)
  assert.equal(wall.isNotAnalysed({}), false)
  assert.equal(wall.plainSummary(wall.NOT_ANALYSED_TAG + '原文開頭'), '原文開頭')
  assert.equal(wall.plainSummary('一般摘要'), '一般摘要')
  assert.equal(wall.plainSummary(null), '')
})

test('the first-paint script in index.html follows the same rules as startingTheme', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1]
  for (const [saved, legacy, systemDark] of [
    [null, null, false], [null, 'dark', true], [null, 'oled', false], [null, 'light', true],
    [null, 'system', true], [null, 'system', false], ['dark', 'light', false], ['neutral', 'oled', false], ['bogus', null, true],
  ]) {
    const classes = new Set()
    const env = {
      localStorage: { getItem: (key) => ({ 'omnikeep-theme-v2': saved, 'omnikeep-theme': legacy })[key] ?? null },
      matchMedia: () => ({ matches: systemDark }),
      document: { documentElement: { classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) }, setAttribute() {} } },
    }
    new Function(...Object.keys(env), script)(...Object.values(env))
    const expected = theme.themeClasses(theme.startingTheme(saved, legacy), systemDark)
    assert.deepEqual(
      { dark: classes.has('dark'), oled: classes.has('oled'), neutral: classes.has('neutral') },
      expected,
      `saved=${saved} legacy=${legacy} systemDark=${systemDark}`,
    )
  }
})
