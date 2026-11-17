import { useEffect, useMemo, useState } from 'react'
import { MatchDeaths } from './Duels.jsx'
import { MatchAim } from './Aim.jsx'
import { CS2Button, Economy, Highlights } from './Moments.jsx'
import { Icon, REASON_TXT, SOURCE, Avatar, RankBadge, Tabs, api, useTab, mapBg, mapInfo, playedWhen, teamLabel, ratingColor, reasonIcon, resultClass } from './lib.jsx'

// MR12: 1º tempo 1-12, 2º tempo 13-24; prorrogações MR3 em blocos de 6
function segments(rounds) {
  const segs = []
  const add = (label, from, to) => {
    const rs = rounds.filter((r) => r.round_num >= from && r.round_num <= to)
    if (rs.length) segs.push({ label, rs })
  }
  add('Primeiro tempo', 1, 12)
  add('Segundo tempo', 13, 24)
  for (let i = 0; 25 + i * 6 <= (rounds.at(-1)?.round_num || 0); i++) add(`Prorrogação ${i + 1}`, 25 + i * 6, 30 + i * 6)
  return segs
}

function RoundStrip({ rounds, myTeam, open }) {
  const left = myTeam || 'A'
  const sc = (r) => (left === 'A' ? `${r.score_a}:${r.score_b}` : `${r.score_b}:${r.score_a}`)
  return (
    <div className="card section">
      <div className="strip-head">
        <h2>Rounds <span className="hint">clique num round para ver o replay 2D</span></h2>
        <button className="btn-primary" onClick={() => open(1)}>▶ Ver replay</button>
      </div>
      <div className="strip">
        {segments(rounds).map((s) => (
          <div className="seg" key={s.label}>
            <div className="seg-head"><span>{s.label}</span><b>{sc(s.rs.at(-1))}</b></div>
            <div className="seg-rounds">
              {s.rs.map((r) => (
                <div key={r.round_num} className={`rb ${r.winner_side}`} onClick={() => open(r.round_num)}
                  title={`Round ${r.round_num}: ${r.winner_side === 'CT' ? 'CT' : 'TR'} venceu — ${REASON_TXT[r.reason] || r.reason}`}>
                  <span className="n">{r.round_num}</span>
                  <span className="ico">{reasonIcon(r.reason)}</span>
                  <span className={`mine ${myTeam ? (r.winner_team === myTeam ? 'w' : 'l') : ''}`} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const COLS = [
  { k: 'kills', l: 'K' }, { k: 'deaths', l: 'D', low: true }, { k: 'assists', l: 'A' },
  { k: 'diff', l: '+/-' }, { k: 'adr', l: 'ADR' }, { k: 'kast', l: 'KAST', pct: true },
  { k: 'hs_pct', l: 'HS%', pct: true }, { k: 'first_kills', l: '1º abate' }, { k: 'trade_kills', l: 'Trades' },
  { k: 'util_damage', l: 'Dano util.' },
]

// placar de cada período: 1º e 2º half; cada prorrogação (MR3) mostra o total e as duas metades
function periods(rounds, t) {
  const last = rounds.at(-1)?.round_num || 0
  const sc = (a, b) => {
    const rs = rounds.filter((r) => r.round_num >= a && r.round_num <= b)
    const w = rs.filter((r) => r.winner_team === t).length
    return { a: w, b: rs.length - w }
  }
  const out = [{ l: '1º half', from: 1, to: Math.min(12, last), ...sc(1, 12) }]
  if (last > 12) out.push({ l: '2º half', from: 13, to: Math.min(24, last), ...sc(13, 24) })
  for (let i = 0; 25 + i * 6 <= last; i++) {
    const s = 25 + i * 6
    const h1 = sc(s, s + 2), h2 = sc(s + 3, s + 5)
    out.push({ l: `Prorrogação ${i + 1}`, from: s, to: Math.min(s + 5, last), a: h1.a + h2.a, b: h1.b + h2.b, parts: last > s + 2 ? [h1, h2] : [h1] })
  }
  return out
}

// tabela recalculada só com os rounds de from até to (mesma conta da análise)
function statsIn(d, from, to) {
  const inR = (rn) => rn >= from && rn <= to
  const base = {}
  for (const p of d.players) {
    base[p.steamid] = { ...p, kills: 0, deaths: 0, assists: 0, damage: 0, kastN: 0, rounds: 0, hs: 0,
      first_kills: 0, trade_kills: 0, util_damage: 0 }
  }
  for (const r of d.player_rounds || []) {
    const s = base[r.steamid]
    if (!s || !inR(r.round_num)) continue
    s.rounds += 1; s.deaths += r.deaths; s.assists += r.assists; s.damage += r.damage; s.kastN += r.kast ? 1 : 0
  }
  for (const k of d.kills) {
    const s = base[k.attacker]
    if (!s || !inR(k.round_num) || k.attacker === k.victim) continue
    if (base[k.victim] && base[k.victim].team === s.team) continue  // abate em aliado não conta
    s.kills += 1; s.hs += k.headshot ? 1 : 0; s.first_kills += k.first_kill ? 1 : 0
    // trade: conta um por aliado vingado (igual à análise), mortos pela vítima nos 5 s antes
    if (k.is_trade) {
      s.trade_kills += d.kills.filter((x) => x.attacker === k.victim && x.round_num === k.round_num && x.tick <= k.tick
        && k.tick - x.tick <= 5 * 64 && base[x.victim]?.team === s.team).length || 1
    }
  }
  for (const u of d.util_rounds || []) {
    const s = base[u.steamid]
    if (s && inR(u.round_num)) s.util_damage += u.dmg || 0
  }
  return Object.values(base).filter((s) => s.rounds > 0).map((s) => {
    const n = s.rounds
    const adr = s.damage / n, kast = (100 * s.kastN) / n
    const rating = (s.kills / n) / 0.679 * 0.35 + (n - s.deaths) / n / 0.317 * 0.25 + adr / 80 * 0.25 + kast / 100 / 0.70 * 0.15
    return { ...s, adr, kast, hs_pct: s.kills ? (100 * s.hs) / s.kills : 0, rating }
  }).sort((a, b) => b.rating - a.rating)
}

// lados do time no período escolhido, na ordem jogada (um half: ['CT']; prorrogação: ['CT', 'T'])
function periodSides(rounds, period, t) {
  const out = []
  for (const r of rounds) {
    if (r.round_num < period.from || r.round_num > period.to || !r.team_a_side) continue
    const s = t === 'A' ? r.team_a_side : r.team_a_side === 'CT' ? 'T' : 'CT'
    if (out.at(-1) !== s) out.push(s)
  }
  return out
}

function bestOf(players) {
  const b = {}
  for (const c of COLS) {
    const val = (p) => (c.k === 'diff' ? p.kills - p.deaths : p[c.k])
    const sorted = [...players].sort((x, y) => (c.low ? val(x) - val(y) : val(y) - val(x)))
    if (sorted[0]) b[c.k] = sorted[0].steamid
  }
  return b
}

function Periods({ rounds, t, sel, pick }) {
  return (
    <div className="periods">
      {periods(rounds, t).map((p) => (
        <button key={p.l} className={`period ${p.a > p.b ? 'w' : p.a < p.b ? 'l' : ''} ${sel?.l === p.l ? 'on' : ''}`}
          onClick={() => pick(sel?.l === p.l ? null : p)}
          title={`${p.parts ? `${p.l}: ${p.parts.map((x, i) => `${i + 1}º half ${x.a}-${x.b}`).join(', ')}` : `${p.l}: ${p.a}-${p.b}`} · clique para ver a tabela até aqui`}>
          <span className="pl">{p.l}</span>
          <b>{p.a}<i>-</i>{p.b}</b>
          {p.parts && <span className="pp">{p.parts.map((x) => `${x.a}-${x.b}`).join(' · ')}</span>}
        </button>
      ))}
    </div>
  )
}

function TeamAvg({ players, source }) {
  const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length
  const rating = players.length ? avg(players.map((p) => p.rating)) : null
  let rank = null
  if (source === 'faceit') {
    const lv = players.map((p) => p.faceit_level).filter(Boolean)
    if (lv.length) rank = <RankBadge p={{ faceit_level: Math.round(avg(lv)) }} source="faceit" />
  } else {
    const pr = players.map((p) => p.rank).filter((r) => r > 18)
    if (pr.length) rank = <RankBadge p={{ rank: Math.round(avg(pr)) }} source={source} />
  }
  return (
    <span className="team-avg" title="Média da nota (e do rank) dos jogadores do time">
      Média da equipe {rank} {rating != null && <b style={{ color: ratingColor(rating) }}>{rating.toFixed(2)}</b>}
    </span>
  )
}

function TeamTable({ name, sides, score, players, me, best, won, rounds, t, source, sel, pick }) {
  return (
    <div className="card">
      <div className="team-head">
        <div className="team-name">
          {sides.map((s, i) => (
            <span key={i} className="side-seq">
              {i > 0 && <span className="side-arrow">→</span>}
              <span className={`side-badge ${s}`} title={!sel ? 'Lado em que este time começou' : sides.length > 1 ? `${i + 1}º half da ${sel.l}` : 'Lado deste time no half selecionado'}>{s === 'CT' ? 'CT' : 'TR'}</span>
            </span>
          ))}
          {name}
          {won != null && <span className={`chip ${won ? 'win' : 'loss'}`} style={{ background: 'var(--panel-3)' }}>{won ? 'Vitória' : 'Derrota'}</span>}
        </div>
        <div className="team-score">{score}</div>
      </div>
      <div className="team-sub">
        <TeamAvg players={players} source={source} />
      </div>
      <Periods rounds={rounds} t={t} sel={sel} pick={pick} />
      <table className="tbl">
        <thead>
          <tr><th>Jogador</th>{COLS.map((c) => <th key={c.k}>{c.l}</th>)}<th>Nota</th></tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.steamid} className={p.steamid === me ? 'me' : ''}>
              <td>
                <div className="pname">
                  <Avatar p={p} />
                  {p.name}
                  <RankBadge p={p} source={source} />
                  {p.steamid === me && <span className="chip" style={{ background: 'var(--t-soft)', color: 'var(--t)' }}>você</span>}
                </div>
              </td>
              {COLS.map((c) => {
                const v = c.k === 'diff' ? p.kills - p.deaths : p[c.k]
                const txt = c.k === 'diff' ? (v > 0 ? `+${v}` : v) : c.pct ? `${Math.round(v)}%` : c.k === 'adr' ? v.toFixed(0) : v
                const cls = best[c.k] === p.steamid ? 'best' : c.k === 'diff' ? '' : 'dim'
                const color = c.k === 'diff' ? (v > 0 ? 'var(--win)' : v < 0 ? 'var(--loss)' : 'var(--muted)') : undefined
                return <td key={c.k} className={cls} style={{ color }}>{txt}</td>
              })}
              <td><span className="rating-pill" style={{ color: ratingColor(p.rating), background: 'var(--panel-2)' }}>{p.rating.toFixed(2)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MePicker({ players, onPick }) {
  return (
    <div className="card picker">
      <h2>Qual desses jogadores é você?</h2>
      <div className="status-text">Só precisa escolher uma vez. Depois o app reconhece você sozinho pelo SteamID.</div>
      <div className="picker-list">
        {players.map((p) => <button key={p.steamid} onClick={() => onPick(p.steamid)}><Avatar p={p} size={22} />{p.name}</button>)}
      </div>
    </div>
  )
}

export default function Match({ id, back, go }) {
  const [d, setD] = useState(null)
  const load = () => api(`/matches/${id}`).then(setD)
  useEffect(() => { load() }, [id])
  const [period, setPeriod] = useState(null)
  const [cumul, setCumul] = useState(true)  // acumulado até o fim do período ou só o período
  const [tab, setTab] = useTab('partida', 'placar')
  useEffect(() => setPeriod(null), [id])

  // jogadores da tabela: a partida inteira ou recalculados no período escolhido
  const shown = useMemo(() => {
    if (!d) return []
    const last = d.rounds.at(-1)?.round_num || 0
    if (!period || !d.player_rounds || (cumul && period.to >= last)) return d.players
    return statsIn(d, cumul ? 1 : period.from, period.to)
  }, [d, period, cumul])
  const best = useMemo(() => bestOf(shown), [shown])

  if (!d) return <div className="loading"><div><div className="spinner" />Carregando partida…</div></div>
  const m = d.match
  const me = m.my_steamid
  const myTeam = d.players.find((p) => p.steamid === me)?.team
  const teams = ['A', 'B'].map((t) => ({
    t,
    name: teamLabel(t === 'A' ? m.team_a : m.team_b, d.players.find((p) => p.team === t)?.name),
    start: t === 'A' ? 'CT' : 'T',
    // sem período: lado em que começou; com um half: o lado daquele half; prorrogação: os dois, na ordem
    sides: period ? periodSides(d.rounds, period, t) : [t === 'A' ? 'CT' : 'T'],
    players: shown.filter((p) => p.team === t),
    // placar no fim do período escolhido
    score: period ? d.rounds.find((r) => r.round_num === period.to)?.[t === 'A' ? 'score_a' : 'score_b'] ?? (t === 'A' ? m.score_a : m.score_b)
      : (t === 'A' ? m.score_a : m.score_b),
  }))
  if (myTeam === 'B') teams.reverse()
  const [L, R] = teams
  const openRound = (n) => go(`#/partida/${id}/round/${n}`)
  const pick = (sid) => api('/me', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ steamid: sid }) }).then(load)

  return (
    <div className="page">
      <div className="match-top">
        <button className="back" onClick={back}><Icon.back /> Partidas</button>
        <CS2Button mid={id} rounds={d.rounds} />
      </div>
      <div className="hero">
        <div className="hero-bg" style={mapBg(m.map)} />
        <div className="hero-team">{L.name}<small>{myTeam ? 'Seu time' : `Começou de ${L.start === 'CT' ? 'CT' : 'TR'}`}</small></div>
        <div className="hero-score">
          <span className={myTeam ? resultClass(m.result) : ''}>{L.score}</span>
          <span style={{ color: 'var(--faint)', margin: '0 10px' }}>:</span>
          <span>{R.score}</span>
          <small>{mapInfo(m.map).name} · {SOURCE[m.source] || ''} · {playedWhen(m)}</small>
        </div>
        <div className="hero-team right">{R.name}<small>{myTeam ? 'Adversário' : `Começou de ${R.start === 'CT' ? 'CT' : 'TR'}`}</small></div>
      </div>

      {!me && <MePicker players={d.players} onPick={pick} />}

      <Tabs value={tab} set={setTab} opts={[
        ['placar', 'Placar'],
        ['destaques', 'Destaques'],
        ...(me ? [['mortes', 'Mortes'], ['mira', 'Mira'], ['economia', 'Economia']] : []),
      ]} />

      {tab === 'destaques' && <Highlights mid={id} go={go} />}
      {tab === 'economia' && me && <Economy mid={id} go={go} />}

      {tab === 'mortes' && me && <MatchDeaths mid={id} go={go} />}

      {tab === 'mira' && me && <MatchAim mid={id} go={go} />}

      {(tab === 'placar' || (['mortes', 'mira', 'economia'].includes(tab) && !me) || !['placar', 'mortes', 'mira', 'destaques', 'economia'].includes(tab)) && <>
      <RoundStrip rounds={d.rounds} myTeam={myTeam} open={openRound} />

      {period && (
        <div className="period-bar section">
          <span>Tabela {cumul ? <>até o fim do <b>{period.l}</b> (rounds 1-{period.to})</> : <>só no <b>{period.l}</b> (rounds {period.from}-{period.to})</>}</span>
          <div className="chips">
            <button className={cumul ? 'on' : ''} onClick={() => setCumul(true)}>Acumulado até aqui</button>
            <button className={!cumul ? 'on' : ''} onClick={() => setCumul(false)}>Só este período</button>
          </div>
          <button className="link-btn" onClick={() => setPeriod(null)}>✕ Partida inteira</button>
        </div>
      )}
      <div className="teams section">
        {[L, R].map((t) => (
          <TeamTable key={t.t} t={t.t} rounds={d.rounds} source={m.source} sel={period} pick={setPeriod} name={t.name} sides={t.sides} score={t.score} players={t.players} me={me} best={best}
            won={myTeam && !period ? t.score > (t === L ? R.score : L.score) : null} />
        ))}
      </div>
      </>}
    </div>
  )
}
