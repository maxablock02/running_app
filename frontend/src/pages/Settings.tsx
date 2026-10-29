import { useEffect, useState } from 'react'
import { api, type Profile } from '../api'

export default function Settings() {
  const [p, setP] = useState<Profile | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)

  useEffect(() => { api.profile().then(setP).catch((e) => setStatus(e.message)) }, [])
  if (!p) return <p className="muted">{status ?? 'Loading…'}</p>

  const num = (key: keyof Profile, step = 1) => ({
    type: 'number', step, value: p[key] as number,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [key]: Number(e.target.value) }),
  })

  async function save() {
    try {
      setP(await api.saveProfile(p!))
      setStatus('Saved — load numbers recalculate everywhere.')
    } catch (e) {
      setStatus((e as Error).message)
    }
  }

  async function fullSync() {
    setSyncing(true)
    try {
      const r = await api.sync(true)
      setStatus(`Full re-sync: ${r.fetched} activities since ${r.since}`)
    } catch (e) {
      setStatus((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <>
      <div className="card">
        <h2>Physiology</h2>
        <p className="sub">
          These drive the heart-rate load score. Use real numbers if you have them (max HR from a hard race finish,
          threshold HR from a 30-min time trial); otherwise your Garmin estimates are a fine start.
        </p>
        <div className="form">
          <label>Max HR<input {...num('max_hr')} /></label>
          <label>Resting HR<input {...num('resting_hr')} /></label>
          <label>Threshold HR (LTHR)<input {...num('lthr')} /></label>
          <label>
            Sex (HR load formula)
            <select value={p.sex} onChange={(e) => setP({ ...p, sex: e.target.value as Profile['sex'] })}>
              <option value="male">Male</option><option value="female">Female</option>
            </select>
          </label>
          <label>
            RPE weight: {Math.round(p.rpe_weight * 100)}%
            <input type="range" min={0} max={1} step={0.05} value={p.rpe_weight}
              onChange={(e) => setP({ ...p, rpe_weight: Number(e.target.value) })} />
          </label>
          <label>Current injury focus<input value={p.injury_focus ?? ''} onChange={(e) => setP({ ...p, injury_focus: e.target.value || null })} /></label>
        </div>
        <p className="sub" style={{ marginTop: 12 }}>
          RPE weight: how far your RPE pulls a run's load away from the heart-rate number. 0% = HR only, 100% = RPE only.
        </p>
        <button className="btn" onClick={save}>Save</button> <span className="muted">{status}</span>
      </div>

      <div className="card">
        <h2>Garmin</h2>
        <p className="sub">Normal sync only fetches recent days. A full re-sync re-pulls the last ~400 days (keeps your RPE/pain/notes).</p>
        <button className="btn ghost" onClick={fullSync} disabled={syncing}>{syncing ? 'Syncing…' : 'Full re-sync'}</button>
      </div>
    </>
  )
}
