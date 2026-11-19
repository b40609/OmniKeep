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

const { originLink } = await load('../src/lib/originLink.ts')

test('the main button says where it goes: GitHub, YouTube and X by name, anything else as the original page', () => {
  assert.equal(originLink('https://github.com/owner/repo').action, '在 GitHub 開啟')
  assert.equal(originLink('https://www.youtube.com/watch?v=abc').action, '在 YouTube 觀看')
  assert.equal(originLink('https://youtu.be/abc').action, '在 YouTube 觀看')
  assert.equal(originLink('https://m.youtube.com/watch?v=abc').action, '在 YouTube 觀看')
  assert.equal(originLink('https://x.com/someone/status/1').action, '在 X 查看')
  assert.equal(originLink('https://twitter.com/someone/status/1').action, '在 X 查看')
  assert.equal(originLink('https://blog.example.com/post').action, '開啟原網頁')
  // a host that only ends in a brand's letters is not that brand
  assert.equal(originLink('https://notgithub.com/a').brand, null)
  assert.equal(originLink('https://gist.github.com/a/b').brand, 'github')
})

test('the source line shows the host without www, opens the kept address, and asks the site for its icon', () => {
  const link = originLink('https://www.example.com/a/b?x=1#y')
  assert.equal(link.host, 'example.com')
  assert.equal(link.href, 'https://www.example.com/a/b?x=1#y')
  assert.equal(link.favicon, 'https://www.example.com/favicon.ico')
})

test('notes and non-web addresses have no page to go back to', () => {
  for (const url of ['note://123', '', null, undefined, 'not a url', 'javascript:alert(1)', 'ftp://example.com/f']) {
    assert.equal(originLink(url), null, String(url))
  }
})
