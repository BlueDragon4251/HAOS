// Compatibility boundary for electron-builder 26's got-shaped options. The
// official v5 downloader retains artifact validation and cache implementation.
const modern = require('@electron/get')
const { EnvHttpProxyAgent } = require('undici')
const fetchDownload = modern.FetchDownloader.prototype.download
const fields = new Set(['quiet', 'getProgressCallback', 'timeout', 'agent', 'signal', 'headers'])
const proxyValue = (upper, lower) => [process.env[upper], process.env[lower]].find(v => v?.trim())?.trim()

function translate(options = {}) {
  if (!options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(k => !fields.has(k))) {
    throw new TypeError('Unsupported build download options')
  }
  const { timeout = { request: 600000 }, agent, ...rest } = options
  if (!timeout || Object.keys(timeout).some(k => k !== 'request') || !Number.isSafeInteger(timeout.request) || timeout.request < 1 || timeout.request > 600000) {
    throw new TypeError('A bounded build download deadline is required')
  }
  // Only builder-util's environment-derived proxy identities are compatible.
  // Never silently discard a caller's custom transport or TLS configuration.
  if (agent !== undefined) {
    if (!agent || typeof agent !== 'object' || Object.keys(agent).some(k => !['http', 'https'].includes(k))) throw new TypeError('Unsupported proxy agent')
    for (const [protocol, value] of Object.entries(agent)) {
      const configured = proxyValue(`${protocol.toUpperCase()}_PROXY`, `${protocol}_proxy`)
      if (!configured || !(value?.proxy instanceof URL) || value.proxy.href !== new URL(configured).href) throw new TypeError('Proxy identity differs from build environment')
    }
  }
  const deadline = AbortSignal.timeout(timeout.request)
  return { ...rest, signal: rest.signal ? AbortSignal.any([deadline, rest.signal]) : deadline }
}

class BuildDownloader extends modern.FetchDownloader {
  async download(url, target, options) {
    const translated = translate(options)
    const dispatcher = new EnvHttpProxyAgent()
    try {
      return await fetchDownload.call(this, url, target, { ...translated, dispatcher })
    } catch (error) {
      // Preserve electron-builder's existing server-error/timeout retry contract.
      if (error instanceof modern.HTTPError) error.response.statusCode = error.response.status
      if (translated.signal.aborted && error.name === 'TimeoutError') {
        const bounded = new Error('Build download deadline exceeded', { cause: error })
        bounded.code = 'ETIMEDOUT'
        throw bounded
      }
      throw error
    } finally {
      await dispatcher.destroy()
    }
  }
}

function downloadArtifact(options) {
  if (options.unsafelyDisableChecksums || options.downloader) throw new TypeError('Build artifact verification cannot be bypassed')
  return modern.downloadArtifact({ ...options, downloader: new BuildDownloader() })
}

// Only the explicit packaging entry point installs this compatibility method.
// It changes no global fetch/TLS/proxy policy or Electron application runtime.
function install() {
  modern.FetchDownloader.prototype.download = BuildDownloader.prototype.download
}

module.exports = { ...modern, downloadArtifact, download: (version, options) => downloadArtifact({ ...options, version, platform: process.platform, arch: process.arch, artifactName: 'electron' }), BuildDownloader, translate, install }
