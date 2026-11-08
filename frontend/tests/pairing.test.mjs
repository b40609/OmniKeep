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

const lib = await load('../src/lib/pairing.ts')

test('a pairing code is read however it was typed, and an API key is never taken for one', () => {
  assert.equal(lib.asPairingCode('abcd-efgh'), 'ABCDEFGH')
  assert.equal(lib.asPairingCode(' 2345 6789 '), '23456789')
  assert.equal(lib.asPairingCode('ABCD-EFG0'), '')        // 0 is not in the alphabet
  assert.equal(lib.asPairingCode('ABCDEFGHI'), '')        // nine letters
  assert.equal(lib.asPairingCode('sk-' + 'a'.repeat(40)), '')
})

test('the code shows in two halves and the QR link keeps it in the fragment', () => {
  assert.equal(lib.formatPairingCode('ABCDEFGH'), 'ABCD-EFGH')
  assert.equal(lib.pairingLink('https://pc.tail.ts.net/', 'ABCDEFGH'), 'https://pc.tail.ts.net/#pair=ABCDEFGH')
})

test('the alphabet matches the server', async () => {
  const py = await readFile(new URL('../../app/pairing.py', import.meta.url), 'utf8')
  const alphabet = py.match(/ALPHABET = "([^"]+)"/)[1]
  for (const ch of alphabet) assert.equal(lib.asPairingCode(ch.repeat(8)), ch.repeat(8))
  for (const ch of '01ILO') assert.equal(lib.asPairingCode(ch.repeat(8)), '')
})

test('a phone gets the Tailscale address first and never a loopback one', () => {
  const ts = ['https://pc.tail.ts.net']
  assert.deepEqual(lib.phoneAddresses(ts, { origin: 'http://127.0.0.1:5000', hostname: '127.0.0.1' }), ts)
  assert.deepEqual(lib.phoneAddresses(ts, { origin: 'http://localhost:5000', hostname: 'localhost' }), ts)
  assert.deepEqual(lib.phoneAddresses(ts, { origin: 'https://pc.tail.ts.net', hostname: 'pc.tail.ts.net' }), ts)
  assert.deepEqual(lib.phoneAddresses([], { origin: 'http://192.168.1.5:5000', hostname: '192.168.1.5' }),
    ['http://192.168.1.5:5000'])
})
