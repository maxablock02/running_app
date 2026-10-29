import { useEffect, useState } from 'react'
import { api, duration, MILE_M, pace, parseDuration, type Race } from '../api'

const newRace = (): Race => ({
  id: null, name: '', race_date: null, distance_m: 5000, priority: 'C', goal_time_s: null, result_time_s: null, status: null, notes: null,
})

export default function Races() {
  const [races, setRaces] = useState<Race[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = () => api.races().then(setRaces).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const edit = (i: number, patch: Partial<Race>) => setRaces((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  async function save(race: Race) {
    if (!race.name) return
    try {
      await (race.id ? api.updateRace(race) : api.createRace(race))
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function remove(race: Race) {
    if (race.id && !confirm(`Delete ${race.name}?`)) return
    if (race.id) await api.deleteRace(race.id)
    load()
  }

  return (
    <div className="card">
      <h2>Races</h2>
      <p className="sub">A = goal race the plan builds toward; B = tune-up; C = fun. Times as h:mm:ss. Changes save when you leave a field.</p>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Race</th><th>Date</th><th>Miles</th><th>Pri.</th><th>Goal</th><th>Goal pace</th><th>Result</th><th>Status</th><th>Notes</th><th /></tr>
          </thead>
          <tbody>
            {races.map((r, i) => (
              <tr key={r.id ?? `new-${i}`}>
                <td><input value={r.name} onChange={(e) => edit(i, { name: e.target.value })} onBlur={() => save(r)} /></td>
                <td>
                  <input type="date" value={r.race_date ?? ''} onChange={(e) => edit(i, { race_date: e.target.value || null })}
                    onBlur={(e) => save({ ...r, race_date: e.target.value || null })} />
                </td>
                <td>
                  <input className="num" type="number" step="0.1" value={+(r.distance_m / MILE_M).toFixed(2)}
                    onChange={(e) => edit(i, { distance_m: Number(e.target.value) * MILE_M })} onBlur={() => save(r)} />
                </td>
                <td>
                  <select value={r.priority} onChange={(e) => save({ ...r, priority: e.target.value as Race['priority'] })}>
                    <option>A</option><option>B</option><option>C</option>
                  </select>
                </td>
                <td>
                  <input style={{ width: 80 }} defaultValue={r.goal_time_s ? duration(r.goal_time_s) : ''} placeholder="h:mm:ss"
                    onBlur={(e) => save({ ...r, goal_time_s: parseDuration(e.target.value) })} />
                </td>
                <td>{r.goal_time_s ? pace(r.distance_m, r.goal_time_s) : '—'}</td>
                <td>
                  <input style={{ width: 80 }} defaultValue={r.result_time_s ? duration(r.result_time_s) : ''} placeholder="h:mm:ss"
                    onBlur={(e) => save({ ...r, result_time_s: parseDuration(e.target.value) })} />
                </td>
                <td>
                  <select value={r.status ?? ''} onChange={(e) => save({ ...r, status: (e.target.value || null) as Race['status'] })}>
                    <option value="">—</option><option value="dnf">DNF</option><option value="dns">DNS</option>
                  </select>
                </td>
                <td><input value={r.notes ?? ''} onChange={(e) => edit(i, { notes: e.target.value })} onBlur={() => save(r)} /></td>
                <td><button className="btn ghost" onClick={() => remove(r)}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ marginBottom: 0 }}><button className="btn ghost" onClick={() => setRaces([...races, newRace()])}>+ Add race</button></p>
    </div>
  )
}
