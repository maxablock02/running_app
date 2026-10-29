import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, shortDate, todayIso, type DailyLog } from '../api'

const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 12 }, tickLine: false }

const blank = (day: string): DailyLog => ({
  day, pain_morning: null, soreness: null, sleep_quality: null,
  calf_raises_left: null, calf_raises_right: null, rehab_done: false, notes: null,
})

export default function Rehab() {
  const [logs, setLogs] = useState<DailyLog[]>([])
  const [form, setForm] = useState<DailyLog>(blank(todayIso()))
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    api.daily(90).then((ls) => {
      setLogs(ls)
      setForm(ls.find((l) => l.day === todayIso()) ?? blank(todayIso()))
    }).catch((e) => setStatus(e.message))
  }, [])

  const pickDay = (day: string) => setForm(logs.find((l) => l.day === day) ?? blank(day))
  const num = (key: keyof DailyLog) => ({
    type: 'number',
    value: (form[key] as number | null) ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [key]: e.target.value === '' ? null : Number(e.target.value) }),
  })

  async function save() {
    try {
      const saved = await api.saveDaily(form)
      setLogs((ls) => [saved, ...ls.filter((l) => l.day !== saved.day)].sort((a, b) => b.day.localeCompare(a.day)))
      setStatus(`Saved ${shortDate(saved.day)}`)
    } catch (e) {
      setStatus((e as Error).message)
    }
  }

  const chart = [...logs].reverse()
  const latest = logs.find((l) => l.calf_raises_left != null && l.calf_raises_right != null)
  const symmetry = latest
    ? Math.round((100 * Math.min(latest.calf_raises_left!, latest.calf_raises_right!)) /
        Math.max(latest.calf_raises_left!, latest.calf_raises_right!, 1))
    : null

  return (
    <>
      <div className="card">
        <h2>Daily check-in</h2>
        <p className="sub">Morning pain is the most useful signal: if it's higher the morning after a run, that run was too much.</p>
        <div className="form">
          <label>Date<input type="date" value={form.day} onChange={(e) => pickDay(e.target.value)} /></label>
          <label>Pain on waking (0–10)<input min={0} max={10} {...num('pain_morning')} /></label>
          <label>General soreness (0–10)<input min={0} max={10} {...num('soreness')} /></label>
          <label>Sleep quality (1–5)<input min={1} max={5} {...num('sleep_quality')} /></label>
          <label>Single-leg calf raises — left<input min={0} {...num('calf_raises_left')} /></label>
          <label>Single-leg calf raises — right<input min={0} {...num('calf_raises_right')} /></label>
          <label className="check">
            <input type="checkbox" checked={form.rehab_done} onChange={(e) => setForm({ ...form, rehab_done: e.target.checked })} />
            &nbsp;Rehab exercises done
          </label>
          <label className="wide">Notes<textarea rows={2} value={form.notes ?? ''} onChange={(e) => setForm({ ...form, notes: e.target.value || null })} /></label>
        </div>
        <p style={{ marginBottom: 0 }}>
          <button className="btn" onClick={save}>Save</button>{' '}
          <span className="muted">{status}</span>
        </p>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Morning pain</h2>
          <p className="sub">Last 90 days, 0–10.</p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={30} {...axis} />
              <YAxis domain={[0, 10]} {...axis} axisLine={false} />
              <Tooltip
                content={({ active, payload }) => {
                  const d = active && (payload?.[0]?.payload as DailyLog | undefined)
                  return d ? <div className="tooltip"><b>{shortDate(d.day)}</b>Pain {d.pain_morning ?? '—'}{d.notes ? <><br />{d.notes}</> : null}</div> : null
                }}
              />
              <Line dataKey="pain_morning" stroke="var(--neg)" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>Calf strength</h2>
          <p className="sub">
            Single-leg calf raises to fatigue. A common return-to-run marker is the injured side reaching ~25 reps
            and ~90% of the other side — confirm targets with your physio.
          </p>
          <div className="legend">
            <span><i style={{ background: 'var(--series-1)' }} />Left</span>
            <span><i style={{ background: 'var(--series-2)' }} />Right</span>
            {symmetry !== null && <span>Latest symmetry: <b>{symmetry}%</b></span>}
          </div>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={chart.filter((l) => l.calf_raises_left != null || l.calf_raises_right != null)} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={30} {...axis} />
              <YAxis {...axis} axisLine={false} />
              <Tooltip
                content={({ active, payload }) => {
                  const d = active && (payload?.[0]?.payload as DailyLog | undefined)
                  return d ? <div className="tooltip"><b>{shortDate(d.day)}</b>Left {d.calf_raises_left ?? '—'} · Right {d.calf_raises_right ?? '—'}</div> : null
                }}
              />
              <Line dataKey="calf_raises_left" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
              <Line dataKey="calf_raises_right" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  )
}
