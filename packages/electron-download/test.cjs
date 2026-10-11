const { test, before, after } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const net = require('node:net')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const { createHash } = require('node:crypto')
const { createRequire } = require('node:module')
const https = require('node:https')
const { execFileSync } = require('node:child_process')
const compat = require('./index.cjs')
let server, directory, origin, checksum = 'correct', hits = [], active = new Set()
const contents = Buffer.from('actual disposable artifact bytes')
const sha = createHash('sha256').update(contents).digest('hex')
before(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haos-download-'))
  server = http.createServer((req, res) => {
    hits.push(req.url)
    if (req.url === '/stall') return
    if (req.url === '/partial') { res.writeHead(200); res.write('partial'); return }
    if (req.url === '/redirect') { res.writeHead(302, { location: '/bytes' }); res.end(); return }
    if (req.url === '/failed') { res.writeHead(503); res.end(); return }
    if (req.url.endsWith('SHASUMS256.txt')) { res.end(`${checksum === 'correct' ? sha : '0'.repeat(64)} *fixture.zip\n`); return }
    res.end(contents)
  })
  server.on('connection', socket => { active.add(socket); socket.on('close', () => active.delete(socket)) })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  origin = `http://127.0.0.1:${server.address().port}`
})
after(async () => {
  for (const socket of active) socket.destroy()
  await new Promise(resolve => server.close(resolve))
  await fs.rm(directory, { recursive: true, force: true })
})

test('builder resolves the pinned official v5 downloader, with no old dependency tree', () => {
  const builder = createRequire(require.resolve('app-builder-lib'))
  assert.equal(builder('@electron/get'), require('@electron/get'))
  const lock = require('../../package-lock.json')
  for (const name of ['got', 'global-agent', 'http-cache-semantics', 'sprintf-js']) {
    assert.equal(Object.keys(lock.packages).some(p => p.endsWith(`/node_modules/${name}`)), false, name)
  }
})
test('reject unsupported options and unbounded deadlines', () => {
  for (const option of [{ https: { rejectUnauthorized: false } }, { timeout: {} }, { timeout: { request: 600001 } }, { timeout: { request: 0 } }, { timeout: { request: 2, connect: 1 } }, { agent: { https: {} } }]) {
    assert.throws(() => compat.translate(option), TypeError)
  }
})
test('caller abort is retained', () => {
  const controller = new AbortController(); controller.abort()
  assert.equal(compat.translate({ signal: controller.signal }).signal.aborted, true)
})
test('real bytes and redirect are downloaded with progress', async () => {
  const target = path.join(directory, 'bytes'); let progress
  await new compat.BuildDownloader().download(`${origin}/redirect`, target, { quiet: true, getProgressCallback: value => { progress = value } })
  assert.deepEqual(await fs.readFile(target), contents)
  assert.equal(progress.transferred, contents.length)
  assert.equal(progress.percent, 1)
})
for (const endpoint of ['stall', 'partial']) test(`actual ${endpoint} connection is aborted by the request deadline`, async () => {
  const started = performance.now()
  await assert.rejects(new compat.BuildDownloader().download(`${origin}/${endpoint}`, path.join(directory, endpoint), { quiet: true, timeout: { request: 80 } }), error => error.code === 'ETIMEDOUT' || error.name === 'AbortError')
  assert.ok(performance.now() - started < 2000)
})
test('server error retains builder retry status', async () => {
  await assert.rejects(new compat.BuildDownloader().download(`${origin}/failed`, path.join(directory, 'failed'), { quiet: true }), error => error.response.statusCode === 503)
})
test('real self-signed TLS endpoint is rejected without creating a download', async () => {
  const key = path.join(directory, 'key.pem'), cert = path.join(directory, 'cert.pem')
  execFileSync('openssl', ['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',key,'-out',cert,'-subj','/CN=haos-disposable-fixture'], { stdio: 'ignore' })
  const tls = https.createServer({ key: await fs.readFile(key), cert: await fs.readFile(cert) }, (_req,res) => res.end(contents))
  await new Promise(resolve => tls.listen(0, '127.0.0.1', resolve))
  const target = path.join(directory, 'untrusted')
  try {
    await assert.rejects(new compat.BuildDownloader().download(`https://127.0.0.1:${tls.address().port}/bytes`, target, { quiet: true }), error => error.cause?.code === 'DEPTH_ZERO_SELF_SIGNED_CERT')
    await assert.rejects(fs.stat(target), { code: 'ENOENT' })
  } finally { await new Promise(resolve => tls.close(resolve)); await fs.rm(key); await fs.rm(cert) }
})
test('real proxy tunnel is used for configured proxy and NO_PROXY bypass is honored', async () => {
  const old = Object.fromEntries(['HTTP_PROXY','http_proxy','HTTPS_PROXY','https_proxy','NO_PROXY','no_proxy'].map(k => [k, process.env[k]]))
  let tunnels = 0
  const proxy = http.createServer()
  proxy.on('connect', (req, socket, head) => {
    tunnels++
    const target = net.connect(server.address().port, '127.0.0.1', () => {
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n'); if (head.length) target.write(head)
      socket.pipe(target); target.pipe(socket)
    })
    socket.on('error', () => target.destroy()); target.on('error', () => socket.destroy()); socket.on('close', () => target.destroy())
  })
  await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve))
  try {
    for (const name of Object.keys(old)) delete process.env[name]
    process.env.HTTP_PROXY = `http://127.0.0.1:${proxy.address().port}`
    await new compat.BuildDownloader().download('http://haos-fixture.invalid/bytes', path.join(directory, 'proxied'), { quiet: true })
    assert.equal(tunnels, 1)
    process.env.NO_PROXY = '127.0.0.1'
    await new compat.BuildDownloader().download(`${origin}/bytes`, path.join(directory, 'direct'), { quiet: true })
    assert.equal(tunnels, 1)
    assert.deepEqual(await fs.readFile(path.join(directory, 'proxied')), contents)
  } finally {
    for (const [k,v] of Object.entries(old)) { if (v === undefined) delete process.env[k]; else process.env[k] = v }
    await new Promise(resolve => proxy.close(resolve))
  }
})
test('official checksum verification rejects damaged content and revalidates cached bytes', async () => {
  const options = { version: '44.5.1', artifactName: 'fixture.zip', isGeneric: true, mirrorOptions: { mirror: `${origin}/`, customDir: 'test' }, cacheRoot: path.join(directory, 'cache'), downloadOptions: { quiet: true } }
  checksum = 'correct'
  const file = await compat.downloadArtifact(options)
  assert.deepEqual(await fs.readFile(file), contents)
  const before = hits.filter(p => p.endsWith('SHASUMS256.txt')).length
  await compat.downloadArtifact(options)
  assert.equal(hits.filter(p => p.endsWith('SHASUMS256.txt')).length, before + 1)
  checksum = 'damaged'
  await assert.rejects(compat.downloadArtifact(options), /Checksum|checksum/)
  checksum = 'correct'
})
test('verification and custom downloader bypasses are denied', () => {
  assert.throws(() => compat.downloadArtifact({ unsafelyDisableChecksums: true }), TypeError)
  assert.throws(() => compat.downloadArtifact({ downloader: {} }), TypeError)
})
test('explicit packaging preload translates the actual default downloader', async () => {
  const original = require('@electron/get').FetchDownloader.prototype.download
  try {
    compat.install()
    await assert.rejects(new (require('@electron/get').FetchDownloader)().download(`${origin}/stall`, path.join(directory, 'default'), { quiet: true, timeout: { request: 80 } }), error => error.code === 'ETIMEDOUT')
  } finally { require('@electron/get').FetchDownloader.prototype.download = original }
})
