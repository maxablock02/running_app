import { Fragment, useEffect, useState } from 'react'
import { api, duration, miles, pace, shortDate, TYPE_LABEL, WORKOUT_TYPES, type Activity, type WorkoutType } from '../api'
import { Laps } from './Blocks'

const SOURCE_LABEL: Record<Activity['load_source'], string> = {
  override: 'manual',
  hr: 'HR',
  'hr+rpe': 'HR + RPE',
  rpe: 'RPE',
  none: 'no data',
}

const numOrNull = (v: string) => (v === '' ? null : Number(v))

export default function Activities() {
  const [rows, setRows] = useState<Activity[]>([])
  const [runsOnly, setRunsOnly] = useState(true)
  const [open, setOpen] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.activities(300).then(setRows).catch((e) => setError(e.message))
  }, [])

  // Optimistic local edit; persist on blur/change so typing doesn't spam the API.
  const edit = (id: number, patch: Partial<Activity>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))

  async function save(id: number, patch: Partial<Activity>) {
    try {
      const updated = await api.updateActivity(id, patch)
      setRows((rs) => rs.map((r) => (r.id === id ? updated : r)))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const shown = runsOnly ? rows.filter((r) => r.activity_type.includes('running')) : rows

  return (
    <div className="card">
      <h2>Activities</h2>
      <p className="sub">
        Add RPE (1–10) and pain (0–10) after each run. RPE adjusts the run's load; pain feeds the rehab trend.
        {' '}<label><input type="checkbox" checked={runsOnly} onChange={(e) => setRunsOnly(e.target.checked)} /> Runs only</label>
      </p>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th /><th title="Key workout">★</th><th>Date</th><th>Type</th><th>Name</th><th>Miles</th><th>Time</th><th>Pace</th><th>Avg HR</th>
              <th>RPE</th><th>Pain</th><th>Load</th><th>Notes</th><th title="Exclude from load (bad HR data etc.)">Excl.</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <Fragment key={a.id}>
              <tr className={a.excluded ? 'excluded' : ''}>
                <td>
                  <button className="star" title={open === a.id ? 'Hide laps' : 'Show laps'}
                    onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? '▾' : '▸'}</button>
                </td>
                <td>
                  <button className={`star ${a.key ? 'on' : ''}`} title={a.key ? 'Key workout (click to remove)' : 'Mark as key workout'}
                    onClick={() => save(a.id, { key_override: !a.key })}>{a.key ? '★' : '☆'}</button>
                </td>
                <td>{shortDate(a.start_time)}</td>
                <td>
                  {a.workout_type && (
                    <select value={a.workout_type} title={a.workout_type_override ? 'Set by you' : 'Auto-detected'}
                      onChange={(e) => save(a.id, { workout_type_override: e.target.value as WorkoutType })}>
                      {WORKOUT_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                    </select>
                  )}
                </td>
                <td className="name" title={a.name}>{a.name}</td>
                <td>{miles(a.distance_m)}</td>
                <td>{duration(a.duration_s)}</td>
                <td>{pace(a.distance_m, a.moving_s ?? a.duration_s)}</td>
                <td>{a.avg_hr ? Math.round(a.avg_hr) : '—'}</td>
                <td>
                  <input className="num" type="number" min={1} max={10} value={a.rpe ?? ''}
                    onChange={(e) => edit(a.id, { rpe: numOrNull(e.target.value) })}
                    onBlur={(e) => save(a.id, { rpe: numOrNull(e.target.value) })} />
                </td>
                <td>
                  <input className="num" type="number" min={0} max={10} value={a.pain ?? ''}
                    onChange={(e) => edit(a.id, { pain: numOrNull(e.target.value) })}
                    onBlur={(e) => save(a.id, { pain: numOrNull(e.target.value) })} />
                </td>
                <td title={`Source: ${SOURCE_LABEL[a.load_source]}${a.garmin_training_load ? ` · Garmin: ${Math.round(a.garmin_training_load)}` : ''}`}>
                  {Math.round(a.load)} <span className="muted">{SOURCE_LABEL[a.load_source]}</span>
                </td>
                <td>
                  <input value={a.notes ?? ''} placeholder="…"
                    onChange={(e) => edit(a.id, { notes: e.target.value })}
                    onBlur={(e) => save(a.id, { notes: e.target.value || null })} />
                </td>
                <td>
                  <input type="checkbox" checked={a.excluded} onChange={(e) => save(a.id, { excluded: e.target.checked })} />
                </td>
              </tr>
              {open === a.id && <tr><td colSpan={15}><Laps activityId={a.id} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!shown.length && <p className="muted">No activities yet — sync Garmin.</p>}
    </div>
  )
}
