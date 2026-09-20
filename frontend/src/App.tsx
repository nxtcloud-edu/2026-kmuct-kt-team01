import { useState } from 'react'
import { createApiClient, getDataMode } from './lib/api'
import { Landing, ReferenceRegistration } from './pages/EntryFlow'
import './styles/entry.css'

type Screen = 'landing' | 'reference'
const mode = getDataMode()
const api = createApiClient(mode)

function Logo() {
  return <button className="logo" onClick={() => window.location.assign(window.location.pathname)} aria-label="찍 홈"><span>찍</span><b>ZZIK</b></button>
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')

  return (
    <div className="app">
      <header className="app-header">
        <Logo />
        {mode === 'mock' && <span className="sample-badge">샘플 데이터</span>}
      </header>
      {screen === 'landing' && <Landing client={api} onComplete={() => setScreen('reference')} onPreview={() => setScreen('reference')} />}
      {screen === 'reference' && <ReferenceRegistration client={api} onDone={() => setScreen('landing')} />}
    </div>
  )
}
