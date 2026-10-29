import { useEffect, useState } from 'react'
import {
  CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, duration, shortDate, speedPace, type CurrentFitness as Data } from '../api'

const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 12 }, tickLine: false }
const ts = (iso: string) => new Date(iso + 'T00:00').getTime()
const longDate = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

export default function CurrentFitness() {
  const [d, setD] = useState<Data | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.currentFitness().then(setD).catch((e) => setError(e.message)) }, [])

  if (error) return <p className="error">{error}</p>
  if (!d) return null

  const injured = !!d.block.interrupted_on
  // Race-day runs (tapered, adrenaline) read optimistic, so prefer a training run for "latest".
  const training = d.observed.filter((o) => !o.race_day)
  const latest = training[training.length - 1] ?? d.observed[d.observed.length - 1]
  const rows = [
    ...d.curve.map((c) => ({ t: ts(c.day), model: c.vdot })),
    ...d.observed.map((o) => ({ t: ts(o.date), measured: o.vdot, o })),
  ].sort((a, b) => a.t - b.t)
  const all = [d.pre.vdot, ...d.curve.map((c) => c.vdot), ...d.observed.map((o) => o.vdot)]

  return (
    <div className="card">
      <h2>Current fitness</h2>
      <p className="sub">
        From {d.block.name}{injured ? `, before the injury on ${longDate(d.block.interrupted_on!)}` : ''}, carried forward {d.days} days.
        VDOT is Daniels' race-equivalent fitness score.
      </p>

      <div className="tiles" style={{ marginBottom: 12 }}>
        <div className="tile">
          <div className="label">{injured ? 'Before injury' : 'At end of block'}</div>
          <div className="value">VDOT {d.pre.vdot}</div>
          <div className="hint">
            Marathon ~{duration(d.pre.equivalents.Marathon)}
            {d.pre.low_speed && d.pre.high_speed && <> (range {duration(42195 / d.pre.high_speed)}–{duration(42195 / d.pre.low_speed)})</>}
            <br />{d.pre.label}
          </div>
        </div>
        <div className="tile">
          <div className="label">Now (detraining model)</div>
          <div className="value">VDOT {d.now.vdot}</div>
          <div className="hint">
            −{(d.now.loss * 100).toFixed(1)}% · marathon ~{duration(d.now.equivalents.Marathon)}<br />
            {d.days} days, {Math.round(d.retention * 100)}% of pre-injury load kept
          </div>
        </div>
        <div className="tile">
          <div className="label">Latest measured run</div>
          <div className="value">{latest ? `VDOT ${latest.vdot}` : '—'}</div>
          <div className="hint">
            {latest
              ? <>{shortDate(latest.date)}{latest.race_day ? ' (race day: reads high)' : ''}: {latest.miles} mi @ {speedPace(latest.speed)}, HR {Math.round(latest.avg_hr)}</>
              : `No steady run of 3+ mi near HR ${d.ref_hr} since then`}
          </div>
        </div>
        <div className="tile">
          <div className="label">Training load (fitness)</div>
          <div className="value">{d.fitness_then} → {d.fitness_now ?? '—'}</div>
          <div className="hint">42-day load average, {injured ? 'injury' : 'block end'} → today</div>
        </div>
      </div>

      <div className="grid2">
        <div>
          <div className="legend">
            <span><i style={{ background: 'var(--series-1)' }} />Model</span>
            <span><i style={{ background: 'var(--series-2)', height: 8, width: 8, borderRadius: 4 }} />Measured run</span>
            <span><i style={{ background: 'var(--axis)' }} />{injured ? 'Pre-injury' : 'Block end'}</span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} {...axis}
                tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
              <YAxis {...axis} axisLine={false} domain={[Math.floor(Math.min(...all) - 1), Math.ceil(Math.max(...all) + 1)]} />
              <ReferenceLine y={d.pre.vdot} stroke="var(--axis)" strokeDasharray="4 4" />
              <Tooltip
                content={({ active, payload }) => {
                  const p = active && (payload?.[0]?.payload as (typeof rows)[number] & { o?: Data['observed'][number] })
                  if (!p) return null
                  const day = new Date(p.t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                  return (
                    <div className="tooltip">
                      <b>{day}</b>
                      {'model' in p && <>Model: VDOT {p.model}</>}
                      {p.o && <>Measured{p.o.race_day ? ' (race day)' : ''}: VDOT {p.o.vdot}<br />{p.o.miles} mi @ {speedPace(p.o.speed)}, HR {Math.round(p.o.avg_hr)}</>}
                    </div>
                  )
                }}
              />
              <Line dataKey="model" stroke="var(--series-1)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              <Scatter dataKey="measured" fill="var(--series-2)" isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="table-wrap">
          <table>
            <thead><tr><th>Race-equivalent</th><th>{injured ? 'Pre-injury' : 'Block end'}</th><th>Now (model)</th>{latest && <th>Latest run{latest.race_day ? ' (race day, reads high)' : ''}</th>}</tr></thead>
            <tbody>
              {Object.keys(d.pre.equivalents).map((k) => (
                <tr key={k}>
                  <td className="muted">{k}</td>
                  <td>{duration(d.pre.equivalents[k])}</td>
                  <td>{duration(d.now.equivalents[k])}</td>
                  {latest && <td>{duration(d.pre.equivalents[k] / latest.ratio)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {d.estimates.length > 1 && (
            <table style={{ marginTop: 8 }}>
              <thead><tr><th>{injured ? 'Pre-injury' : 'Block'} estimate from</th><th>Marathon</th><th>Pace</th></tr></thead>
              <tbody>
                {d.estimates.map((e) => (
                  <tr key={e.method}>
                    <td className="muted">{e.label}</td>
                    <td>{duration(42195 / e.marathon_speed)}</td>
                    <td>{speedPace(e.marathon_speed)}</td>
                  </tr>
                ))}
                <tr><td><b>Average (used above)</b></td><td><b>{duration(42195 / d.pre.marathon_speed)}</b></td><td><b>{speedPace(d.pre.marathon_speed)}</b></td></tr>
              </tbody>
            </table>
          )}
          <p className="sub" style={{ marginTop: 8 }}>
            Pace at a different HR is shifted along your own measured slope ({(d.hr_slope * 1000).toFixed(0)} mm/s per bpm, from your steady laps).
            The model uses published detraining rates (~7% by 3 weeks off, ~16% by 8) eased by the load you've kept up.
            Measured runs scale your pace to HR {d.ref_hr} and compare it with the pre-injury steady pace; cooler weather
            than the build makes them read optimistic. The truth is likely between the two.
          </p>
        </div>
      </div>
    </div>
  )
}
