import { Fragment, useEffect, useState } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  api, duration, MILE_M, pace, shortDate, speedPace, TYPE_LABEL, workLabel,
  type AerobicTrend, type Block, type BlockInput, type Lap, type Race, type SessionShape,
} from '../api'

const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 12 }, tickLine: false }
// Color follows the block (by id order), never its position in a filtered list.
const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']
const colorFor = (blocks: Block[], id: number) => SERIES[[...blocks].sort((a, b) => a.id - b.id).findIndex((b) => b.id === id) % SERIES.length]

const longDate = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

const finished = (b: Block) => (b.result?.status === 'finished' ? b.result : null)
const dnfLabel = (b: Block) =>
  b.result?.status === 'dnf' ? `DNF${b.result.distance_m ? ` at ${(b.result.distance_m / MILE_M).toFixed(1)} mi` : ''}` : null
// Training totals: for a block cut short by injury, the part before it is the meaningful one.
const training = (b: Block) => b.pre_injury ?? b.stats

export default function Blocks() {
  const [blocks, setBlocks] = useState<Block[]>([])
  const [aerobic, setAerobic] = useState<AerobicTrend | null>(null)
  const [selected, setSelected] = useState<number | null>(() => Number(localStorage.getItem('block')) || null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const load = () =>
    Promise.all([api.blocks(), api.aerobic()])
      .then(([b, a]) => {
        setBlocks(b)
        setAerobic(a)
        setSelected((s) => (b.some((x) => x.id === s) ? s : (b[0]?.id ?? null)))
      })
      .catch((e) => setError(e.message))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (id: number) => {
    setSelected(id)
    localStorage.setItem('block', String(id))
  }

  if (error) return <p className="error">{error}</p>

  return (
    <>
      <div className="block-cards">
        {blocks.map((b) => (
          <button key={b.id} className={`block-card ${b.id === selected ? 'active' : ''}`} onClick={() => choose(b.id)}>
            <span className="swatch" style={{ background: colorFor(blocks, b.id) }} />
            <b>{b.name}</b>
            <span className="muted">{longDate(b.end_date)}</span>
            <span className="big">
              {finished(b) ? duration(finished(b)!.time_s) : dnfLabel(b) ? 'DNF'
                : b.mp_estimate?.calibrated_marathon_s ? `~${duration(b.mp_estimate.calibrated_marathon_s)}` : '—'}
            </span>
            <span className="muted">
              {finished(b) ? `VDOT ${finished(b)!.vdot}` : b.interrupted_on ? `injured ${longDate(b.interrupted_on)}`
                : b.mp_estimate?.calibrated_marathon_s ? 'estimated' : 'no result'}
              {' · '}peak {training(b).peak_week_mi} mi/wk
            </span>
          </button>
        ))}
        <button className="block-card add" onClick={() => setAdding(!adding)}>+ New block</button>
      </div>

      {adding && <NewBlock onDone={() => { setAdding(false); load() }} />}
      {blocks.length > 0 && <Compare blocks={blocks} />}
      {selected && <BlockDetail key={selected} id={selected} color={colorFor(blocks, selected)} onChanged={load} />}
      {aerobic && aerobic.months.length > 1 && <AerobicChart trend={aerobic} blocks={blocks} />}
    </>
  )
}

// --- Compare ----------------------------------------------------------------

function Compare({ blocks }: { blocks: Block[] }) {
  const maxWeeks = Math.max(...blocks.map((b) => b.weeks.length))
  const data = Array.from({ length: maxWeeks }, (_, i) => {
    const weeksOut = maxWeeks - 1 - i
    const row: Record<string, number | null> = { weeks_out: weeksOut }
    for (const b of blocks) row[b.name] = b.weeks.find((w) => w.weeks_out === weeksOut)?.miles ?? null
    return row
  })
  const ordered = [...blocks].sort((a, b) => a.end_date.localeCompare(b.end_date))
  const rows: [string, (b: Block) => string][] = [
    ['Result', (b) => (finished(b) ? duration(finished(b)!.time_s) : dnfLabel(b) ?? '—')],
    ['Avg race HR', (b) => (b.result?.avg_hr ? String(Math.round(b.result.avg_hr)) : '—')],
    ['VDOT', (b) => (finished(b) ? String(finished(b)!.vdot) : '—')],
    ['Injury', (b) => (b.pre_injury ? `${longDate(b.interrupted_on!)} (${b.pre_injury.weeks_out} wk out)` : '—')],
    ['Weeks trained', (b) => String(b.pre_injury ? b.weeks.length - b.pre_injury.weeks_out - 1 : b.weeks.length)],
    ['Total miles', (b) => String(training(b).total_mi)],
    ['Avg week', (b) => `${training(b).avg_week_mi} mi`],
    ['Peak week', (b) => `${training(b).peak_week_mi} mi`],
    ['Runs ≥ 16 mi', (b) => String(training(b).long_runs)],
    ['Longest run', (b) => `${training(b).longest_mi} mi`],
    ['Key workouts', (b) => String(b.stats.key_workouts)],
    ['Fitness, race morning / injury', (b) => String(b.pre_injury?.fitness ?? b.stats.fitness_end)],
    ['Peak fitness', (b) => String(b.stats.fitness_peak)],
    ['Steady pace at HR ' + (blocks.find((b) => b.steady)?.steady?.ref_hr ?? ''), (b) => (b.steady ? speedPace(b.steady.speed) : '—')],
    ['MP from workouts', (b) => (b.mp_estimate ? speedPace(b.mp_estimate.speed) : '—')],
    ['Actual race pace', (b) => (b.mp_estimate?.actual_speed ? speedPace(b.mp_estimate.actual_speed) : '—')],
  ]

  return (
    <div className="grid2">
      <div className="card">
        <h2>Weekly miles, lined up by race day</h2>
        <p className="sub">Week 0 is race week. Hover for each block's miles.</p>
        <div className="legend">
          {ordered.map((b) => <span key={b.id}><i style={{ background: colorFor(blocks, b.id) }} />{b.name}</span>)}
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="weeks_out" {...axis} tickFormatter={(w) => (w === 0 ? 'Race' : `-${w}`)} />
            <YAxis {...axis} axisLine={false} />
            <Tooltip
              content={({ active, payload }) => {
                const row = active && (payload?.[0]?.payload as Record<string, number | null> | undefined)
                if (!row) return null
                return (
                  <div className="tooltip">
                    <b>{row.weeks_out === 0 ? 'Race week' : `${row.weeks_out} weeks out`}</b>
                    {ordered.map((b) => <div key={b.id}>{b.name}: {row[b.name] ?? '—'} mi</div>)}
                  </div>
                )
              }}
            />
            {ordered.map((b) => (
              <Line key={b.id} dataKey={b.name} stroke={colorFor(blocks, b.id)} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Side by side</h2>
        <p className="sub">Race-day run excluded from training totals. Injured blocks: totals and steady pace cover the weeks before the injury.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th />{ordered.map((b) => <th key={b.id}>{b.name}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map(([label, f]) => (
                <tr key={label}><td className="muted">{label}</td>{ordered.map((b) => <td key={b.id}>{f(b)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// --- Detail -----------------------------------------------------------------

function BlockDetail({ id, color, onChanged }: { id: number; color: string; onChanged: () => void }) {
  const [b, setB] = useState<Block | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)

  const load = () => api.block(id).then(setB).catch((e) => setStatus(e.message))
  useEffect(() => { load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!b) return <p className="muted">{status ?? 'Loading…'}</p>

  const missingLaps = (b.key_runs ?? []).filter((k) => !k.laps_fetched).length

  async function fetchLaps() {
    setBusy(true)
    try {
      const r = await api.fetchBlockLaps(id)
      setStatus(`Fetched laps for ${r.fetched} workouts`)
      await load()
      onChanged()
    } catch (e) {
      setStatus((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function toggleKey(activityId: number, key: boolean) {
    await api.updateActivity(activityId, { key_override: key })
    await load()
    onChanged()
  }

  const est = b.mp_estimate
  return (
    <>
      <div className="card" style={{ borderTop: `3px solid ${color}` }}>
        <div className="row-between">
          <div>
            <h2>{b.name}</h2>
            <p className="sub">
              {longDate(b.start_date)} – {longDate(b.end_date)} · {b.weeks.length} weeks
              {b.race && <> · {b.race.name}</>}
            </p>
          </div>
          <div>
            <button className="btn ghost" onClick={() => setEditing(!editing)}>Edit</button>
          </div>
        </div>
        {editing && <EditBlock block={b} onDone={() => { setEditing(false); load(); onChanged() }} />}

        <div className="tiles" style={{ marginBottom: 0 }}>
          {(() => {
            const fin = finished(b)
            if (fin && b.race) return (
              <>
                <div className="tile">
                  <div className="label">Result</div>
                  <div className="value">{duration(fin.time_s)}</div>
                  <div className="hint">{speedPace(b.race.distance_m / fin.time_s)} · HR {fin.avg_hr ?? '—'}</div>
                </div>
                <div className="tile">
                  <div className="label">VDOT</div>
                  <div className="value">{fin.vdot}</div>
                  <div className="hint">{Object.entries(fin.equivalents).filter(([k]) => k !== 'Marathon').map(([k, s]) => `${k} ${duration(s)}`).join(' · ')}</div>
                </div>
              </>
            )
            if (b.result?.status === 'dnf') return (
              <div className="tile">
                <div className="label">Result</div>
                <div className="value">DNF</div>
                <div className="hint">
                  {b.result.distance_m && b.result.time_s
                    ? `${(b.result.distance_m / MILE_M).toFixed(1)} mi @ ${speedPace(b.result.distance_m / b.result.time_s)} · HR ${b.result.avg_hr ?? '—'}`
                    : 'No race-day run'}
                </div>
              </div>
            )
            return <div className="tile"><div className="label">Result</div><div className="value">—</div><div className="hint">No race result</div></div>
          })()}
          {b.pre_injury && (
            <div className="tile">
              <div className="label">Injury</div>
              <div className="value">{shortDate(b.interrupted_on!)}</div>
              <div className="hint">
                {b.pre_injury.weeks_out} weeks before race day · last run {b.pre_injury.last_run ? shortDate(b.pre_injury.last_run) : '—'}<br />
                Fitness {b.pre_injury.fitness} at the time
              </div>
            </div>
          )}
          <div className="tile">
            <div className="label">Marathon pace from workouts</div>
            <div className="value">{est ? speedPace(est.calibrated_speed ?? est.speed) : '—'}</div>
            <div className="hint">
              {!est && `No marathon-effort segments in the last 8 weeks${b.pre_injury ? ' before the injury' : ''}`}
              {est && est.actual_speed && <>Workouts said {duration(est.marathon_s)}; ran {speedPace(est.actual_speed)} ({Math.round((est.calibration! - 1) * 1000) / 10}%)</>}
              {est && est.calibrated_speed && <>~{duration(est.calibrated_marathon_s!)}, adjusted by {est.calibrated_from}'s race</>}
              {est && !est.actual_speed && !est.calibrated_speed && <>~{duration(est.marathon_s)} at HR {est.marathon_hr}</>}
            </div>
          </div>
          <div className="tile">
            <div className="label">Training{b.pre_injury ? ' before injury' : ''}</div>
            <div className="value">{training(b).avg_week_mi} <span className="unit">mi/wk</span></div>
            <div className="hint">
              Peak {training(b).peak_week_mi} · {training(b).long_runs} runs ≥ 16 mi · longest {training(b).longest_mi}
              {b.steady && <><br />Steady pace {speedPace(b.steady.speed)} at HR {b.steady.ref_hr} ({b.steady.laps} laps)</>}
            </div>
          </div>
        </div>
      </div>

      {est && (
        <div className="card">
          <h2>Marathon-effort segments</h2>
          <p className="sub">
            Continuous work of 3+ miles within {est.hr_tolerance} bpm of your marathon HR ({est.marathon_hr}) in the last 8 weeks
            {b.pre_injury ? ' before the injury' : ''}, shifted to {est.marathon_hr} bpm along your own pace-vs-HR slope.
            The latest three (marked ●) set the estimate.
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th /><th>Date</th><th>Workout</th><th>Segment</th><th>Pace</th><th>HR</th><th>At HR {est.marathon_hr}</th></tr></thead>
              <tbody>
                {est.samples.map((s) => (
                  <tr key={s.activity_id}>
                    <td>{est.used.includes(s.activity_id) ? '●' : ''}</td>
                    <td>{shortDate(s.date)}</td>
                    <td>{s.name}</td>
                    <td>{s.work_mi} mi</td>
                    <td>{speedPace(s.speed)}</td>
                    <td>{s.avg_hr}</td>
                    <td>{speedPace(s.est_speed)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="row-between">
          <div>
            <h2>Key workouts</h2>
            <p className="sub">
              Picked out from your workout names, or from distance and HR for unnamed runs. Click a row for its laps; ☆ to add or remove a run.
            </p>
          </div>
          {missingLaps > 0 && (
            <button className="btn" onClick={fetchLaps} disabled={busy}>{busy ? 'Fetching…' : `Fetch laps (${missingLaps})`}</button>
          )}
        </div>
        {status && <p className="muted">{status}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th /><th>Date</th><th>Wk</th><th>Type</th><th>Name</th><th>Miles</th><th>Avg pace</th><th>HR</th><th>Work</th><th>Work pace</th><th>Work HR</th></tr>
            </thead>
            <tbody>
              {(b.key_runs ?? []).map((k) => (
                <Fragment key={k.id}>
                  <tr className="clickable" onClick={() => setOpen(open === k.id ? null : k.id)}>
                    <td>
                      <button className="star" title="Remove from key workouts" onClick={(e) => { e.stopPropagation(); toggleKey(k.id, false) }}>★</button>
                    </td>
                    <td>{shortDate(k.start_time)}</td>
                    <td className="muted">{k.weeks_out === 0 ? 'Race' : `-${k.weeks_out}`}</td>
                    <td><span className={`chip t-${k.workout_type}`}>{k.workout_type ? TYPE_LABEL[k.workout_type] : '—'}</span></td>
                    <td className="name">{k.name}</td>
                    <td>{(k.distance_m / MILE_M).toFixed(1)}</td>
                    <td>{pace(k.distance_m, k.moving_s ?? k.duration_s)}</td>
                    <td>{k.avg_hr ? Math.round(k.avg_hr) : '—'}</td>
                    <td>{k.work ? workLabel(k.work) : <span className="muted">{k.laps_fetched ? '—' : 'no laps'}</span>}</td>
                    <td>{k.work ? pace(k.work.distance_m, k.work.duration_s) : ''}</td>
                    <td>{k.work?.avg_hr ? Math.round(k.work.avg_hr) : ''}</td>
                  </tr>
                  {open === k.id && <tr><td colSpan={11}><Laps activityId={k.id} /></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sub" style={{ marginTop: 12, marginBottom: 0 }}>
          To add a run that isn't listed, star it on the Activities tab.
        </p>
      </div>
    </>
  )
}

export function Laps({ activityId }: { activityId: number }) {
  const [laps, setLaps] = useState<Lap[] | null>(null)
  const [inferred, setInferred] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.laps(activityId).then((r) => { setLaps(r.laps); setInferred(r.inferred) }).catch((e) => setError(e.message))
  }, [activityId])
  if (error) return <p className="error">{error}</p>
  if (!laps) return <p className="muted">Loading laps…</p>
  return (
    <>
      <table className="laps">
        <thead><tr><th>Lap</th><th title={inferred ? 'Inferred from lap lengths and paces' : 'From the watch workout'}>{inferred ? 'Role (inferred)' : 'Step'}</th><th>Distance</th><th>Time</th><th>Pace</th><th>HR</th><th>Max HR</th></tr></thead>
        <tbody>
          {laps.map((l) => (
            <tr key={l.lap_index} className={l.work ? 'work' : 'muted'}>
              <td>{l.lap_index}</td>
              <td>{l.role ? l.role.toLowerCase() : ''}{l.step_index != null ? ` #${l.step_index}` : ''}</td>
              <td>{(l.distance_m / MILE_M).toFixed(2)} mi</td>
              <td>{duration(l.moving_s ?? l.duration_s)}</td>
              <td>{pace(l.distance_m, l.moving_s ?? l.duration_s)}</td>
              <td>{l.avg_hr ?? '—'}</td>
              <td>{l.max_hr ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Similar activityId={activityId} />
    </>
  )
}

const shapeLabel = (s: SessionShape) =>
  s.kind === 'reps' ? workLabel({ ...s, intervals: true }) : `${(s.distance_m / MILE_M).toFixed(1)} mi continuous`

function Similar({ activityId }: { activityId: number }) {
  const [data, setData] = useState<{ shape: SessionShape | null; matches: SessionShape[] } | null>(null)
  useEffect(() => { api.similar(activityId).then(setData).catch(() => setData(null)) }, [activityId])
  if (!data?.shape || !data.matches.length) return null
  const me = data.shape
  const rows = [me, ...data.matches]
  return (
    <div className="similar">
      <b>Similar sessions</b>
      <span className="muted">
        {' '}{me.kind === 'reps' ? `reps of ~${Math.round(me.rep_m!)} m (±20%)` : `continuous efforts of ${(me.distance_m / MILE_M).toFixed(1)} mi (±35%)`}.
        Same pace at a lower HR = fitter.
      </span>
      <table className="laps">
        <thead><tr><th>Date</th><th>Block</th><th>Session</th><th>Pace</th><th>vs this</th><th>Avg HR</th><th title="Average of the reps' max HR; on short reps HR lags, so this is the better effort signal">Peak HR</th></tr></thead>
        <tbody>
          {rows.map((m) => {
            const diff = MILE_M / m.speed - MILE_M / me.speed
            return (
              <tr key={m.activity_id} className={m.activity_id === me.activity_id ? 'work' : ''}>
                <td>{shortDate(m.date)}{m.date.slice(0, 4) !== new Date().getFullYear().toString() ? ` '${m.date.slice(2, 4)}` : ''}</td>
                <td>{m.block ?? <span className="muted">—</span>}</td>
                <td>{shapeLabel(m)}</td>
                <td>{speedPace(m.speed)}</td>
                <td className="muted">{m.activity_id === me.activity_id ? 'this' : `${diff > 0 ? '+' : '−'}${Math.abs(Math.round(diff))}s`}</td>
                <td>{m.avg_hr ? Math.round(m.avg_hr) : '—'}</td>
                <td>{m.peak_hr ? Math.round(m.peak_hr) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// --- Aerobic trend ----------------------------------------------------------

function AerobicChart({ trend, blocks }: { trend: AerobicTrend; blocks: Block[] }) {
  const data = trend.months.map((m) => ({ ...m, secs: Math.round(MILE_M / m.speed) }))
  const months = data.map((d) => d.month)
  const clampMonth = (iso: string) => {
    const m = iso.slice(0, 7)
    return months.find((x) => x >= m) ?? months[months.length - 1]
  }
  return (
    <div className="card">
      <h2>Easy-run pace at HR {trend.hr}</h2>
      <p className="sub">
        Monthly median of easy runs, scaled to {trend.hr} bpm: your aerobic engine over time. Up = faster. Shaded = training blocks.
      </p>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="month" {...axis} tickFormatter={(m) => new Date(m + '-01T00:00').toLocaleDateString(undefined, { month: 'short', year: '2-digit' })} />
          <YAxis {...axis} axisLine={false} reversed domain={['dataMin - 10', 'dataMax + 10']} tickFormatter={(s) => duration(s)} width={48} />
          {blocks.map((b) => (
            <ReferenceArea key={b.id} x1={clampMonth(b.start_date)} x2={clampMonth(b.end_date)} fill="var(--surface-2)" fillOpacity={1} ifOverflow="visible" />
          ))}
          <Tooltip
            content={({ active, payload }) => {
              const d = active && (payload?.[0]?.payload as (typeof data)[number] | undefined)
              return d ? <div className="tooltip"><b>{d.month}</b>{duration(d.secs)}/mi at HR {trend.hr} · {d.runs} runs</div> : null
            }}
          />
          <Line dataKey="secs" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- Create / edit ----------------------------------------------------------

function BlockForm({ initial, onSave, onDelete }: { initial: BlockInput; onSave: (b: BlockInput) => Promise<unknown>; onDelete?: () => Promise<unknown> }) {
  const [f, setF] = useState(initial)
  const [races, setRaces] = useState<Race[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.races().then(setRaces) }, [])

  const pickRace = (raceId: number | null) => {
    const r = races.find((x) => x.id === raceId)
    if (r?.race_date) {
      const end = new Date(r.race_date + 'T00:00')
      const start = new Date(end.getTime() - (18 * 7 - 1) * 86400000)
      setF({ ...f, race_id: raceId, name: f.name || r.name, end_date: r.race_date, start_date: start.toISOString().slice(0, 10) })
    } else {
      setF({ ...f, race_id: raceId })
    }
  }

  async function save() {
    try { await onSave(f) } catch (e) { setError((e as Error).message) }
  }

  return (
    <div className="form" style={{ margin: '12px 0' }}>
      <label>Race
        <select value={f.race_id ?? ''} onChange={(e) => pickRace(e.target.value ? Number(e.target.value) : null)}>
          <option value="">— none —</option>
          {races.map((r) => <option key={r.id} value={r.id!}>{r.name}{r.race_date ? ` (${r.race_date})` : ''}</option>)}
        </select>
      </label>
      <label>Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>Start<input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
      <label>End (race day)<input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
      <label title="First day training stopped. Fitness estimates use only the weeks before it.">Injury / interruption (optional)
        <input type="date" value={f.interrupted_on ?? ''} onChange={(e) => setF({ ...f, interrupted_on: e.target.value || null })} />
      </label>
      <label className="wide">Notes<input value={f.notes ?? ''} onChange={(e) => setF({ ...f, notes: e.target.value || null })} /></label>
      <div>
        <button className="btn" onClick={save} disabled={!f.name || !f.start_date || !f.end_date}>Save</button>{' '}
        {onDelete && <button className="btn ghost" onClick={() => confirm(`Delete block "${f.name}"? Runs aren't affected.`) && onDelete()}>Delete</button>}
        {error && <span className="error"> {error}</span>}
      </div>
    </div>
  )
}

function NewBlock({ onDone }: { onDone: () => void }) {
  return (
    <div className="card">
      <h2>New block</h2>
      <p className="sub">Pick a race to default to the 18 weeks before it, or set any date range.</p>
      <BlockForm
        initial={{ name: '', start_date: '', end_date: '', race_id: null, interrupted_on: null, notes: null }}
        onSave={async (b) => { await api.createBlock(b); onDone() }}
      />
    </div>
  )
}

function EditBlock({ block, onDone }: { block: Block; onDone: () => void }) {
  const { name, start_date, end_date, race_id, interrupted_on, notes } = block
  return (
    <BlockForm
      initial={{ name, start_date, end_date, race_id, interrupted_on, notes }}
      onSave={async (b) => { await api.updateBlock(block.id, b); onDone() }}
      onDelete={async () => { await api.deleteBlock(block.id); localStorage.removeItem('block'); onDone() }}
    />
  )
}
