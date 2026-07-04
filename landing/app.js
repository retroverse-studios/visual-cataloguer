const REPO = 'retroverse-studios/visual-cataloguer'
const RELEASES_API = `https://api.github.com/repos/${REPO}/releases/latest`
const FALLBACK_URL = `https://github.com/${REPO}/releases/latest`
const PLATFORM_LABEL = { mac: 'macOS', windows: 'Windows', linux: 'Linux' }

// ---------- platform-aware download ----------

function detectPlatform() {
  const ua = navigator.userAgent.toLowerCase()
  const platform = (navigator.platform || '').toLowerCase()
  if (platform.includes('mac') || ua.includes('macintosh') || ua.includes('mac os')) return 'mac'
  if (platform.includes('win') || ua.includes('windows')) return 'windows'
  if (ua.includes('linux') || platform.includes('linux')) return 'linux'
  return 'mac'
}

let selectedPlatform = detectPlatform()
let release = null // { tag, assets[] }
let releaseChecked = false

async function loadRelease() {
  try {
    const res = await fetch(RELEASES_API)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    release = { tag: data.tag_name, assets: data.assets || [] }
  } catch {
    release = null // rate-limited or no release yet
  }
  releaseChecked = true
  render()
}

// Desktop asset conventions (see .github/workflows/desktop.yml):
//   VisualCataloguer-macos-arm64.zip / -macos-x64.zip
//   VisualCataloguer-windows-x64.zip
//   VisualCataloguer-linux-x64.tar.gz
function assetsFor(platform) {
  if (!release) return { primary: null, alt: null }
  const find = (test) => release.assets.find((a) => test(a.name.toLowerCase())) || null
  if (platform === 'mac') {
    const arm = find((n) => n.includes('macos-arm64'))
    const intel = find((n) => n.includes('macos-x64'))
    return { primary: arm || intel, alt: arm ? intel : null }
  }
  if (platform === 'windows') {
    return { primary: find((n) => n.includes('windows')), alt: null }
  }
  return { primary: find((n) => n.includes('linux')), alt: null }
}

function render() {
  const { primary, alt } = assetsFor(selectedPlatform)
  const label = PLATFORM_LABEL[selectedPlatform]
  const heroBtn = document.getElementById('download-btn')
  const runBtn = document.getElementById('download-btn-2')
  const version = document.getElementById('version')
  const altLink = document.getElementById('alt-arch')
  const others = document.getElementById('other-platforms')

  const noReleaseYet = releaseChecked && !primary

  for (const btn of [heroBtn, runBtn]) {
    if (!btn) continue
    if (noReleaseYet) {
      btn.textContent = btn === heroBtn ? 'Desktop app — see releases' : 'See releases'
      btn.href = FALLBACK_URL
    } else {
      btn.textContent = `Download for ${label}`
      btn.href = primary ? primary.browser_download_url : FALLBACK_URL
    }
  }

  version.textContent = release ? `${release.tag} · ${label}` : ' '

  if (selectedPlatform === 'mac' && alt) {
    altLink.hidden = false
    altLink.textContent = 'Intel Mac? Download x64 →'
    altLink.href = alt.browser_download_url
  } else {
    altLink.hidden = true
  }

  if (others) {
    const rest = Object.keys(PLATFORM_LABEL).filter((p) => p !== selectedPlatform)
    others.innerHTML = noReleaseYet
      ? ''
      : 'Also for ' + rest
          .map((p) => {
            const a = assetsFor(p).primary
            const href = a ? a.browser_download_url : FALLBACK_URL
            return `<a href="${href}">${PLATFORM_LABEL[p]}</a>`
          })
          .join(' · ')
  }

  document.querySelectorAll('.platform-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.platform === selectedPlatform)
  })
}

document.querySelectorAll('.platform-btn').forEach((b) => {
  b.addEventListener('click', () => {
    selectedPlatform = b.dataset.platform
    render()
  })
})

render()
loadRelease()
