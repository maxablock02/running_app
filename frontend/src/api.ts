export const MILE_M = 1609.344

export interface Activity {
  id: number
  start_time: string
  name: string
  activity_type: string
  distance_m: number
  duration_s: number
  moving_s: number | null
  avg_hr: number | null
  max_hr: number | null
  elevation_gain_m: number | null
  avg_cadence: number | null
  garmin_training_load: number | null
  rpe: number | null
  pain: number | null
  notes: string | null
  load_override: number | null
  excluded: boolean
  load: number
  load_source: 'override' | 'hr' | 'hr+rpe' | 'rpe' | 'none'
  workout_type: WorkoutType | null
  workout_type_override: WorkoutType | null
  key: boolean
  key_override: boolean | null
  laps_fetched: boolean
}

export const WORKOUT_TYPES = ['race', 'race_practice', 'long', 'tempo', 'intervals', 'workout', 'easy'] as const
export type WorkoutType = (typeof WORKOUT_TYPES)[number]
export const TYPE_LABEL: Record<WorkoutType, string> = {
  race: 'Race', race_practice: 'Race practice', long: 'Long run', tempo: 'Tempo',
  intervals: 'Intervals', workout: 'Workout', easy: 'Easy',
}

export interface Work {
  reps: number
  distance_m: number
  duration_s: number
  avg_hr: number | null
  intervals: boolean
}

export interface Lap {
  lap_index: number
  distance_m: number
  duration_s: number
  moving_s: number | null
  avg_hr: number | null
  max_hr: number | null
  intensity: string | null
  step_index: number | null
  role: string | null  // Garmin's tag for plan workouts, inferred for unnamed runs
  work: boolean
}

export interface BlockWeek {
  weeks_out: number
  miles: number
  runs: number
  long_mi: number
}

export interface MpSample {
  activity_id: number
  date: string
  name: string
  work_mi: number
  speed: number
  avg_hr: number
  est_speed: number
}

export interface MpEstimate {
  marathon_hr: number
  hr_tolerance: number
  speed: number
  marathon_s: number
  samples: MpSample[]
  used: number[]
  actual_speed?: number
  calibration?: number
  calibrated_speed?: number
  calibrated_from?: string
  calibrated_marathon_s?: number
}

export interface Block {
  id: number
  name: string
  start_date: string
  end_date: string
  race_id: number | null
  notes: string | null
  race: Race | null
  weeks: BlockWeek[]
  stats: {
    total_mi: number
    avg_week_mi: number
    peak_week_mi: number
    runs: number
    long_runs: number
    longest_mi: number
    key_workouts: number
    fitness_end: number
    fitness_peak: number
  }
  interrupted_on: string | null
  pre_injury: {
    total_mi: number
    avg_week_mi: number
    peak_week_mi: number
    runs: number
    long_runs: number
    longest_mi: number
    weeks_out: number
    last_run: string | null
    fitness: number
  } | null
  steady: SteadyMarker | null
  result:
    | { status: 'finished'; time_s: number; vdot: number; avg_hr: number | null; equivalents: Record<string, number> }
    | { status: 'dnf'; distance_m: number | null; time_s: number | null; avg_hr: number | null }
    | null
  mp_estimate: MpEstimate | null
  key_runs?: (Activity & { work: Work | null; weeks_out: number })[]
  race_run?: Activity | null
}

export interface BlockInput {
  name: string
  start_date: string
  end_date: string
  race_id: number | null
  interrupted_on: string | null
  notes: string | null
}

export interface SteadyMarker {
  ref_hr: number
  speed: number
  low: number
  high: number
  laps: number
}

export interface SessionShape {
  activity_id: number
  date: string
  name: string
  workout_type: WorkoutType
  kind: 'reps' | 'segment'
  reps: number
  rep_m?: number
  distance_m: number
  duration_s: number
  avg_hr: number | null
  peak_hr: number | null
  speed: number
  block: string | null
}

export interface FitnessLevel {
  vdot: number
  equivalents: Record<string, number>
}

export interface CurrentFitness {
  block: { id: number; name: string; interrupted_on: string | null; end_date: string }
  pre: FitnessLevel & { marathon_speed: number; method: string; label: string; low_speed?: number; high_speed?: number }
  estimates: { method: string; label: string; marathon_speed: number; ratio?: number; reference?: string; low_speed?: number; high_speed?: number }[]
  since: string
  days: number
  fitness_then: number
  fitness_now: number | null
  retention: number
  now: FitnessLevel & { loss: number }
  curve: { day: string; vdot: number; fitness: number | null }[]
  observed: {
    activity_id: number; date: string; name: string; miles: number; speed: number; avg_hr: number
    speed_at_ref: number; ratio: number; vdot: number; laps: number; race_day: boolean
  }[]
  ref_hr: number
  hr_slope: number
}

export interface AerobicTrend {
  hr: number
  months: { month: string; runs: number; speed: number }[]
}

export interface LoadDay {
  day: string
  load: number
  fitness: number
  fatigue: number
  form: number
}

export interface WeekSummary {
  week: string
  miles: number
  runs: number
  load: number
  avg_pain: number | null
}

export interface DailyLog {
  day: string
  pain_morning: number | null
  soreness: number | null
  sleep_quality: number | null
  calf_raises_left: number | null
  calf_raises_right: number | null
  rehab_done: boolean
  notes: string | null
}

export interface Race {
  id: number | null
  name: string
  race_date: string | null
  distance_m: number
  priority: 'A' | 'B' | 'C'
  goal_time_s: number | null
  result_time_s: number | null
  status: 'dnf' | 'dns' | null
  notes: string | null
}

export interface Profile {
  id: number
  max_hr: number
  resting_hr: number
  lthr: number
  sex: 'male' | 'female'
  rpe_weight: number
  injury_focus: string | null
  marathon_hr: number
  aerobic_hr: number
}

export interface SyncState {
  last_sync: string | null
  last_result: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

const send = (method: string, body?: unknown) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  activities: (limit = 100) => request<Activity[]>(`/api/activities?limit=${limit}`),
  updateActivity: (id: number, patch: Partial<Activity>) => request<Activity>(`/api/activities/${id}`, send('PATCH', patch)),
  loadMetrics: (days = 180) => request<LoadDay[]>(`/api/metrics/load?days=${days}`),
  weekly: (weeks = 26) => request<WeekSummary[]>(`/api/metrics/weekly?weeks=${weeks}`),
  daily: (days = 60) => request<DailyLog[]>(`/api/daily?days=${days}`),
  saveDaily: (log: DailyLog) => request<DailyLog>(`/api/daily/${log.day}`, send('PUT', log)),
  races: () => request<Race[]>('/api/races'),
  createRace: (race: Race) => request<Race>('/api/races', send('POST', race)),
  updateRace: (race: Race) => request<Race>(`/api/races/${race.id}`, send('PUT', race)),
  deleteRace: (id: number) => request<{ ok: boolean }>(`/api/races/${id}`, send('DELETE')),
  profile: () => request<Profile>('/api/profile'),
  saveProfile: (p: Profile) => request<Profile>('/api/profile', send('PUT', p)),
  laps: (id: number) => request<{ laps: Lap[]; work: Work | null; inferred: boolean }>(`/api/activities/${id}/laps`),
  similar: (id: number) => request<{ shape: SessionShape | null; matches: SessionShape[] }>(`/api/activities/${id}/similar`),
  aerobic: () => request<AerobicTrend>('/api/metrics/aerobic'),
  currentFitness: () => request<CurrentFitness | null>('/api/fitness/current'),
  blocks: () => request<Block[]>('/api/blocks'),
  block: (id: number) => request<Block>(`/api/blocks/${id}`),
  createBlock: (b: BlockInput) => request<Block>('/api/blocks', send('POST', b)),
  updateBlock: (id: number, b: BlockInput) => request<Block>(`/api/blocks/${id}`, send('PUT', b)),
  deleteBlock: (id: number) => request<{ ok: boolean }>(`/api/blocks/${id}`, send('DELETE')),
  fetchBlockLaps: (id: number) => request<{ fetched: number }>(`/api/blocks/${id}/fetch-laps`, send('POST')),
  syncState: () => request<SyncState>('/api/sync'),
  sync: (full = false) => request<{ fetched: number; new: number; since: string }>('/api/sync', send('POST', { full })),
}

// --- Formatting --------------------------------------------------------------

export const miles = (m: number) => (m / MILE_M).toFixed(2)

export function duration(s: number): string {
  s = Math.round(s) // round first, or 7:59.6 renders as "7:60"
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(h ? 2 : 1, '0')
  return `${h ? `${h}:` : ''}${mm}:${String(sec).padStart(2, '0')}`
}

export function pace(distance_m: number, seconds: number): string {
  if (!distance_m) return '—'
  return duration(seconds / (distance_m / MILE_M)) + '/mi'
}

/** m/s -> "7:06/mi" */
export const speedPace = (mps: number) => (mps ? duration(MILE_M / mps) + '/mi' : '—')

/** "6 × 600 m" for interval reps, "9.5 mi" for one continuous segment. */
export function workLabel(w: Work): string {
  const mi = w.distance_m / MILE_M
  if (!w.intervals || w.reps <= 1) return `${mi.toFixed(1)} mi`
  const each = mi / w.reps
  return `${w.reps} × ${each < 0.95 ? Math.round((each * MILE_M) / 10) * 10 + ' m' : each.toFixed(1) + ' mi'}`
}

/** Parse "h:mm:ss" or "mm:ss" into seconds; empty -> null. */
export function parseDuration(text: string): number | null {
  if (!text.trim()) return null
  const parts = text.split(':').map(Number)
  if (parts.some(isNaN)) return null
  return parts.reduce((acc, p) => acc * 60 + p, 0)
}

export const shortDate = (iso: string) =>
  new Date(iso.length === 10 ? iso + 'T00:00' : iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

export const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
