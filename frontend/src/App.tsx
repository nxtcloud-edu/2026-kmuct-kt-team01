import { useState } from 'react'
import { createApiClient, getDataMode } from './lib/api'
import { Landing, ReferenceRegistration } from './pages/EntryFlow'
import { Gallery } from './pages/Gallery'
import { CoverageDashboard, PhotoDetail } from './pages/PhotoDetail'
import { ChartIcon, GridIcon } from './components/icons'
import type { ActiveAlbum } from './lib/types'
import './styles/entry.css'
import './styles/gallery.css'
import './styles/detail.css'

type Screen = 'landing' | 'reference' | 'album' | 'detail' | 'coverage'
const mode = getDataMode()
const api = createApiClient(mode)

function Logo() {
  return <button className="logo" onClick={() => window.location.assign(window.location.pathname)} aria-label="찍 홈"><span>찍</span><b>ZZIK</b></button>
}

function AppHeader({ screen, activeAlbum, onNavigate }: { screen: Screen; activeAlbum: ActiveAlbum | null; onNavigate: (screen: Screen) => void }) {
  const inAlbum = ['album', 'detail', 'coverage'].includes(screen)
  return (
    <header className="app-header">
      <Logo />
      {inAlbum && <nav className="desktop-nav" aria-label="앨범 메뉴"><button className={screen !== 'coverage' ? 'active' : ''} onClick={() => onNavigate('album')}><GridIcon />사진</button><button className={screen === 'coverage' ? 'active' : ''} onClick={() => onNavigate('coverage')}><ChartIcon />현황</button></nav>}
      <div className="header-actions">{mode === 'mock' && <span className="sample-badge">샘플 데이터</span>}{inAlbum && activeAlbum && <span className="profile-chip"><span className="avatar coral">{activeAlbum.displayName.slice(0, 1)}</span><span>{activeAlbum.displayName}</span></span>}</div>
    </header>
  )
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')
  const [photoId, setPhotoId] = useState<string | null>(null)
  const [activeAlbum, setActiveAlbum] = useState<ActiveAlbum | null>(null)
  function openPhoto(id: string) { setPhotoId(id); setScreen('detail'); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  function preview() { setActiveAlbum({ albumId: 'album-demo', memberId: 'm-1', displayName: '나' }); setScreen('album') }

  return (
    <div className="app">
      <AppHeader screen={screen} activeAlbum={activeAlbum} onNavigate={setScreen} />
      {screen === 'landing' && <Landing client={api} onComplete={(album) => { setActiveAlbum(album); setScreen('reference') }} onPreview={preview} />}
      {screen === 'reference' && <ReferenceRegistration client={api} onDone={() => setScreen('album')} />}
      {screen === 'album' && activeAlbum && <Gallery client={api} albumId={activeAlbum.albumId} currentMemberId={activeAlbum.memberId} onOpen={openPhoto} onCoverage={() => setScreen('coverage')} />}
      {screen === 'detail' && activeAlbum && photoId && <PhotoDetail client={api} albumId={activeAlbum.albumId} photoId={photoId} onBack={() => setScreen('album')} />}
      {screen === 'coverage' && activeAlbum && <CoverageDashboard client={api} albumId={activeAlbum.albumId} onBack={() => setScreen('album')} />}
      {['album', 'detail', 'coverage'].includes(screen) && <nav className="mobile-nav"><button className={screen !== 'coverage' ? 'active' : ''} onClick={() => setScreen('album')}><GridIcon />사진</button><button className={screen === 'coverage' ? 'active' : ''} onClick={() => setScreen('coverage')}><ChartIcon />현황</button></nav>}
    </div>
  )
}
