import { useEffect, useState } from 'react'
import { api, type SyncState } from './api'
import Activities from './pages/Activities'
import Blocks from './pages/Blocks'
import Dashboard from './pages/Dashboard'
import Races from './pages/Races'
import Rehab from './pages/Rehab'
import Settings from './pages/Settings'

const TABS = { Dashboard, Blocks, Activities, Races, Rehab, Settings } as const
type Tab = keyof typeof TABS

export default function App() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('tab') as Tab) || 'Dashboard')
  const [syncState, setSyncState] = useState<SyncState | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0) // bump to make pages refetch after a sync

  useEffect(() => {
    api.syncState().then(setSyncState).catch((e) => setError(e.message))
  }, [])

  const choose = (t: Tab) => {
    setTab(t)
    localStorage.setItem('tab', t)
  }

  async function sync() {
    setSyncing(true)
    setError(null)
    try {
      await api.sync()
      setSyncState(await api.syncState())
      setVersion((v) => v + 1)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  const Page = TABS[tab]
  return (
    <div className="app">
      <header className="topbar">
        <h1>Running</h1>
        <nav className="tabs">
          {(Object.keys(TABS) as Tab[]).map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} onClick={() => choose(t)}>
              {t}
            </button>
          ))}
        </nav>
        <div className="sync">
          {error ? (
            <span className="error">{error}</span>
          ) : (
            syncState?.last_sync && <span>Synced {new Date(syncState.last_sync).toLocaleString()}</span>
          )}
          <button className="btn" onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync Garmin'}
          </button>
        </div>
      </header>
      <Page key={version} />
    </div>
  )
}
