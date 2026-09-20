import { useState } from 'react'
import { createApiClient, getDataMode } from './lib/api'
import { Landing, ReferenceRegistration } from './pages/EntryFlow'
import { Gallery } from './pages/Gallery'
import { CoverageDashboard, PhotoDetail } from './pages/PhotoDetail'
import { ChartIcon, GridIcon } from './components/icons'
import './styles/entry.css'
import './styles/gallery.css'
import './styles/detail.css'

type Screen = 'landing' | 'reference' | 'album' | 'detail' | 'coverage'
const mode = getDataMode()
const api = createApiClient(mode)

function Logo() {
  return <button className="logo" onClick={() => window.location.assign(window.location.pathname)} aria-label="찍 홈"><span>찍</span><b>ZZIK</b></button>
}

function AppHeader({ screen, onNavigate }: { screen: Screen; onNavigate: (screen: Screen) => void }) {
  const inAlbum = ['album', 'detail', 'coverage'].includes(screen)
  return (
    <header className="app-header">
      <Logo />
      {inAlbum && <nav className="desktop-nav" aria-label="앨범 메뉴"><button className={screen !== 'coverage' ? 'active' : ''} onClick={() => onNavigate('album')}><GridIcon />사진</button><button className={screen === 'coverage' ? 'active' : ''} onClick={() => onNavigate('coverage')}><ChartIcon />현황</button></nav>}
      <div className="header-actions">{mode === 'mock' && <span className="sample-badge">샘플 데이터</span>}{inAlbum && <span className="profile-chip"><span className="avatar coral">나</span><span>나</span></span>}</div>
    </header>
  )
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')
  const [photoId, setPhotoId] = useState<string | null>(null)
  function openPhoto(id: string) { setPhotoId(id); setScreen('detail'); window.scrollTo({ top: 0, behavior: 'smooth' }) }

  return (
    <div className="app">
      <AppHeader screen={screen} onNavigate={setScreen} />
      {screen === 'landing' && <Landing client={api} onComplete={() => setScreen('reference')} onPreview={() => setScreen('album')} />}
      {screen === 'reference' && <ReferenceRegistration client={api} onDone={() => setScreen('album')} />}
      {screen === 'album' && <Gallery client={api} onOpen={openPhoto} onCoverage={() => setScreen('coverage')} />}
      {screen === 'detail' && photoId && <PhotoDetail client={api} photoId={photoId} onBack={() => setScreen('album')} />}
      {screen === 'coverage' && <CoverageDashboard client={api} onBack={() => setScreen('album')} />}
      {['album', 'detail', 'coverage'].includes(screen) && <nav className="mobile-nav"><button className={screen !== 'coverage' ? 'active' : ''} onClick={() => setScreen('album')}><GridIcon />사진</button><button className={screen === 'coverage' ? 'active' : ''} onClick={() => setScreen('coverage')}><ChartIcon />현황</button></nav>}
    </div>
  )
}
