import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, shortDate, type LoadDay, type Race, type WeekSummary } from '../api'
import CurrentFitness from './CurrentFitness'

const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 12 }, tickLine: false }

function formLabel(form: number): string {
  if (form > 15) return 'Very fresh — detraining if it lasts'
  if (form > 5) return 'Fresh — good for racing'
  if (form > -10) return 'Neutral'
  if (form > -30) return 'Productive training'
  return 'Overreaching — watch it'
}

export default function Dashboard() {
  const [load, setLoad] = useState<LoadDay[]>([])
  const [weeks, setWeeks] = useState<WeekSummary[]>([])
  const [races, setRaces] = useState<Race[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.loadMetrics(180), api.weekly(16), api.races()])
      .then(([l, w, r]) => { setLoad(l); setWeeks(w); setRaces(r) })
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!load.length) {
    return (
      <div className="card">
        <h2>No activities yet</h2>
        <p className="sub">Log in to Garmin once (see README), then press “Sync Garmin”.</p>
      </div>
    )
  }

  const today = load[load.length - 1]
  const thisWeek = weeks[weeks.length - 1]
  const lastWeek = weeks[weeks.length - 2]
  const nextRace = races.find((r) => r.race_date && r.race_date >= today.day)
  const daysToRace = nextRace?.race_date
    ? Math.round((new Date(nextRace.race_date).getTime() - new Date(today.day).getTime()) / 86400000)
    : null

  return (
    <>
      <div className="tiles">
        <div className="tile">
          <div className="label">Fitness</div>
          <div className="value">{today.fitness.toFixed(0)}</div>
          <div className="hint">42-day load average</div>
        </div>
        <div className="tile">
          <div className="label">Fatigue</div>
          <div className="value">{today.fatigue.toFixed(0)}</div>
          <div className="hint">7-day load average</div>
        </div>
        <div className="tile">
          <div className="label">Form</div>
          <div className="value">{today.form > 0 ? '+' : ''}{today.form.toFixed(0)}</div>
          <div className="hint">{formLabel(today.form)}</div>
        </div>
        <div className="tile">
          <div className="label">This week</div>
          <div className="value">{thisWeek?.miles.toFixed(1) ?? 0} mi</div>
          <div className="hint">Last week {lastWeek?.miles.toFixed(1) ?? 0} mi · {thisWeek?.runs ?? 0} runs</div>
        </div>
        <div className="tile">
          <div className="label">Next race</div>
          <div className="value">{daysToRace !== null ? `${daysToRace} d` : '—'}</div>
          <div className="hint">{nextRace ? nextRace.name : 'Set race dates on the Races tab'}</div>
        </div>
      </div>

      <CurrentFitness />

      <div className="card">
        <h2>Fitness and fatigue</h2>
        <p className="sub">Last 180 days. Load scale: 100 ≈ one hour at threshold heart rate.</p>
        <div className="legend">
          <span><i style={{ background: 'var(--series-1)' }} />Fitness</span>
          <span><i style={{ background: 'var(--series-2)' }} />Fatigue</span>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={load} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={40} {...axis} />
            <YAxis {...axis} axisLine={false} />
            <Tooltip
              content={({ active, payload }) => {
                const d = active && (payload?.[0]?.payload as LoadDay | undefined)
                if (!d) return null
                return (
                  <div className="tooltip">
                    <b>{shortDate(d.day)}</b>
                    Fitness {d.fitness} · Fatigue {d.fatigue}<br />
                    Form {d.form} · Day load {d.load}
                  </div>
                )
              }}
            />
            <Line dataKey="fitness" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="fatigue" stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Form</h2>
          <p className="sub">Fitness minus fatigue. Above zero = fresh, below = carrying fatigue.</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={load.slice(-60)} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={40} {...axis} />
              <YAxis {...axis} axisLine={false} />
              <ReferenceLine y={0} stroke="var(--axis)" />
              <Tooltip
                cursor={{ fill: 'var(--surface-2)' }}
                content={({ active, payload }) => {
                  const d = active && (payload?.[0]?.payload as LoadDay | undefined)
                  return d ? <div className="tooltip"><b>{shortDate(d.day)}</b>Form {d.form} — {formLabel(d.form)}</div> : null
                }}
              />
              <Bar dataKey="form" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                {load.slice(-60).map((d) => <Cell key={d.day} fill={d.form >= 0 ? 'var(--pos)' : 'var(--neg)'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>Weekly running miles</h2>
          <p className="sub">Last 16 weeks (Mon–Sun). Hover a week for runs and average pain.</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={weeks} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="week" tickFormatter={shortDate} minTickGap={30} {...axis} />
              <YAxis {...axis} axisLine={false} />
              <Tooltip
                cursor={{ fill: 'var(--surface-2)' }}
                content={({ active, payload }) => {
                  const w = active && (payload?.[0]?.payload as WeekSummary | undefined)
                  if (!w) return null
                  return (
                    <div className="tooltip">
                      <b>Week of {shortDate(w.week)}</b>
                      {w.miles} mi · {w.runs} runs · load {w.load}<br />
                      Avg pain {w.avg_pain ?? '—'}
                    </div>
                  )
                }}
              />
              <Bar dataKey="miles" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  )
}
