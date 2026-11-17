import { useEffect, useMemo, useRef, useState } from 'react'
import { Icon, REASON_TXT, api, reasonIcon } from './lib.jsx'
import { TypeChip, TIPOS, duelFacts, duelType } from './Duels.jsx'
import { CS2Button } from './Moments.jsx'

const COL = { CT: '#5aa9ff', T: '#f4b23e' }
const SPEEDS = [0.5, 1, 1.5, 2, 4]
const NADE_TXT = { smoke: 'Smoke', flash: 'Flash', he: 'HE', molotov: 'Molotov', decoy: 'Decoy' }
const BUY_TXT = { pistol: 'Pistol', eco: 'Eco', 'forçado': 'Forçado', completo: 'Compra completa' }
const WEAPON = (w) => (w || '').replace(/^weapon_/, '').replace('_silencer', '-S').replace('hegrenade', 'HE')
  .replace('inferno', 'Molotov').replace('usp-S', 'USP-S')

export function fmt(sec) {
  sec = Math.max(0, sec)
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`
}

// ---------- desenho do replay ----------
export function useRadar(map) {
  const [ov, setOv] = useState(null)
  const [imgs, setImgs] = useState({})
  useEffect(() => {
    if (!map) return
    api(`/maps/${map}/overview`).then((o) => {
      setOv(o)
      const load = (k, f) => { const im = new Image(); im.onload = () => setImgs((s) => ({ ...s, [k]: im })); im.src = `/api/radar/${f}` }
      load('main', o.image)
      if (o.lower) load('lower', o.lower.image)
    }).catch(() => setOv(false))
  }, [map])
  return { ov, imgs }
}

// parte desenhada do radar (sem a borda transparente), em pixels do radar 1024
const boxCache = new WeakMap()
export function radarBox(img) {
  if (!img) return { x0: 0, y0: 0, x1: 1024, y1: 1024 }
  if (boxCache.has(img)) return boxCache.get(img)
  let b = { x0: 0, y0: 0, x1: 1024, y1: 1024 }
  try {
    const n = 256, c = document.createElement('canvas'); c.width = n; c.height = n
    const g = c.getContext('2d'); g.drawImage(img, 0, 0, n, n)
    const a = g.getImageData(0, 0, n, n).data
    let x0 = n, y0 = n, x1 = -1, y1 = -1
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      if (a[(y * n + x) * 4 + 3] > 20) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y }
    }
    if (x1 > x0 && y1 > y0) { const s = 1024 / n; b = { x0: x0 * s, y0: y0 * s, x1: (x1 + 1) * s, y1: (y1 + 1) * s } }
  } catch { /* imagem sem acesso aos pixels: usa o radar inteiro */ }
  boxCache.set(img, b)
  return b
}

// encaixa a parte desenhada do radar (com uma margem) no canvas w x h
export function fitView(w, h, box) {
  const pad = 24
  const bw = box.x1 - box.x0, bh = box.y1 - box.y0
  const z = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh)
  return { w, h, z, ox: (w - bw * z) / 2 - box.x0 * z, oy: (h - bh * z) / 2 - box.y0 * z }
}

function frameAt(pl, f) {
  const i = Math.floor(f), j = Math.min(i + 1, pl.x.length - 1), a = f - i
  if (pl.x[i] == null) return null
  const lerp = (arr) => (arr[j] == null ? arr[i] : arr[i] + (arr[j] - arr[i]) * a)
  let yaw = pl.yaw[i]
  if (pl.yaw[j] != null) { let d = pl.yaw[j] - pl.yaw[i]; if (d > 180) d -= 360; if (d < -180) d += 360; yaw = pl.yaw[i] + d * a }
  return { x: lerp(pl.x), y: lerp(pl.y), z: pl.z[i], hp: pl.hp[i], yaw, w: pl.w[i], fl: pl.fl[i] }
}

function draw(ctx, view, S) {
  const { ov, imgs, rep, t, me, kills, grenades, bomb, floor, names, sel } = S
  const { w, h, z, ox, oy } = view
  const P = (x, y) => [ox + ((x - ov.pos_x) / ov.scale) * z, oy + ((ov.pos_y - y) / ov.scale) * z]
  const R = (u) => (u / ov.scale) * z
  const onFloor = (z) => !ov.lower || z == null || (floor === 'lower' ? z < ov.lower.z_max : z >= ov.lower.z_max)
  ctx.clearRect(0, 0, w, h)
  const img = floor === 'lower' && imgs.lower ? imgs.lower : imgs.main
  if (img) { ctx.globalAlpha = 0.95; ctx.drawImage(img, ox, oy, 1024 * z, 1024 * z); ctx.globalAlpha = 1 }

  // granadas
  for (const g of grenades) {
    if (t < g.throw_tick || t > g.end_tick + 32) continue
    const col = g.side ? COL[g.side] : '#ccc'
    if (t < g.det_tick) { // em voo
      const path = g.path
      let i = path.findIndex((p) => p[0] > t)
      if (i <= 0) i = path.length - 1
      const [t0, x0, y0] = path[Math.max(0, i - 1)], [t1, x1, y1] = path[i]
      const a = t1 > t0 ? Math.min(1, (t - t0) / (t1 - t0)) : 1
      ctx.strokeStyle = col; ctx.globalAlpha = 0.35; ctx.lineWidth = 1; ctx.setLineDash([3, 3])
      ctx.beginPath(); path.filter((p) => p[0] <= t).forEach((p, n) => { const q = P(p[1], p[2]); n ? ctx.lineTo(...q) : ctx.moveTo(...q) }); ctx.stroke()
      ctx.setLineDash([]); ctx.globalAlpha = 1
      const [px, py] = P(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a)
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(px, py, 3, 0, 7); ctx.fill()
      continue
    }
    const [x, y] = P(g.x, g.y)
    const life = (t - g.det_tick) / Math.max(1, g.end_tick - g.det_tick)
    if (g.type === 'smoke') {
      const r = R(144) * Math.min(1, (t - g.det_tick) / 64 + 0.3)
      ctx.fillStyle = `rgba(200,205,215,${0.55 * (life > 0.9 ? (1 - life) * 10 : 1)})`
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill()
      ctx.strokeStyle = col; ctx.globalAlpha = 0.6; ctx.lineWidth = 1.5; ctx.stroke(); ctx.globalAlpha = 1
    } else if (g.type === 'molotov') {
      const grd = ctx.createRadialGradient(x, y, 0, x, y, R(120))
      grd.addColorStop(0, 'rgba(255,120,30,.75)'); grd.addColorStop(1, 'rgba(255,60,20,.15)')
      ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(x, y, R(120), 0, 7); ctx.fill()
    } else if ((g.type === 'flash' || g.type === 'he') && t - g.det_tick < 40) {
      const a = 1 - (t - g.det_tick) / 40
      ctx.strokeStyle = g.type === 'flash' ? `rgba(255,255,255,${a})` : `rgba(255,90,60,${a})`
      ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(x, y, R(g.type === 'flash' ? 60 : 110) * (1.4 - a * 0.6), 0, 7); ctx.stroke()
    }
  }

  // bomba
  const planted = bomb.find((b) => b.kind === 'plantou' && b.tick <= t)
  if (planted && planted.x != null) {
    const done = bomb.find((b) => b.kind !== 'plantou' && b.tick <= t)
    const [x, y] = P(planted.x, planted.y)
    if (done?.kind === 'explodiu' && t - done.tick < 160) {
      const a = 1 - (t - done.tick) / 160
      ctx.fillStyle = `rgba(255,110,40,${a * 0.6})`; ctx.beginPath(); ctx.arc(x, y, R(500) * (1.2 - a * 0.5), 0, 7); ctx.fill()
    }
    const blink = !done && Math.floor(t / 32) % 2 === 0
    ctx.fillStyle = done?.kind === 'desarmou' ? '#3ddc84' : blink ? '#ff5d62' : '#9a2f33'
    ctx.strokeStyle = '#000'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.roundRect(x - 7, y - 7, 14, 14, 3); ctx.fill(); ctx.stroke()
  }

  // mortes (X) e linha do abate
  for (const kl of kills) {
    if (kl.tick > t || kl.vx == null) continue
    const [vx, vy] = P(kl.vx, kl.vy)
    const age = t - kl.tick
    if (age < 128 && kl.ax != null) {
      const [ax, ay] = P(kl.ax, kl.ay)
      ctx.strokeStyle = `rgba(255,255,255,${0.7 * (1 - age / 128)})`; ctx.lineWidth = 1.5
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(vx, vy); ctx.stroke()
    }
    const mine = kl.victim === me
    const s = mine ? 7 : 5
    ctx.strokeStyle = kl.victim_side ? COL[kl.victim_side] : '#999'; ctx.lineWidth = mine ? 3 : 2
    ctx.globalAlpha = onFloor(kl.vz) ? 1 : 0.3
    ctx.beginPath(); ctx.moveTo(vx - s, vy - s); ctx.lineTo(vx + s, vy + s); ctx.moveTo(vx + s, vy - s); ctx.lineTo(vx - s, vy + s); ctx.stroke()
    if (sel && sel.tick === kl.tick && sel.victim === kl.victim) {
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(vx, vy, 13, 0, 7); ctx.stroke()
    }
    ctx.globalAlpha = 1
  }

  // jogadores
  const f = Math.max(0, Math.min(rep.n - 1, (t - rep.t0) / rep.step))
  const order = [...rep.players].sort((a, b) => (a.sid === me) - (b.sid === me))
  for (const pl of order) {
    const st = frameAt(pl, f)
    if (!st) continue
    const [x, y] = P(st.x, st.y)
    const mine = pl.sid === me
    const r = mine ? 8.5 : 6.5
    ctx.globalAlpha = onFloor(st.z) ? 1 : 0.3
    // mira
    const a = (-st.yaw * Math.PI) / 180
    ctx.strokeStyle = COL[pl.side]; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(x + Math.cos(a) * r, y + Math.sin(a) * r); ctx.lineTo(x + Math.cos(a) * (r + 9), y + Math.sin(a) * (r + 9)); ctx.stroke()
    if (st.fl > 0) { ctx.fillStyle = 'rgba(255,255,255,.55)'; ctx.beginPath(); ctx.arc(x, y, r + 6, 0, 7); ctx.fill() }
    ctx.fillStyle = COL[pl.side]
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill()
    ctx.lineWidth = mine ? 3 : 1.5; ctx.strokeStyle = mine ? '#fff' : 'rgba(0,0,0,.7)'; ctx.stroke()
    // vida
    ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(x - 9, y + r + 3, 18, 3)
    ctx.fillStyle = st.hp > 50 ? '#3ddc84' : st.hp > 20 ? '#f4b23e' : '#ff5d62'; ctx.fillRect(x - 9, y + r + 3, 18 * st.hp / 100, 3)
    if (names || mine) {
      ctx.font = `${mine ? 700 : 600} 11px Inter Variable, sans-serif`; ctx.textAlign = 'center'
      ctx.fillStyle = 'rgba(0,0,0,.75)'; ctx.fillText(pl.name, x + 1, y - r - 5)
      ctx.fillStyle = mine ? '#fff' : '#d8dde6'; ctx.fillText(pl.name, x, y - r - 6)
    }
    ctx.globalAlpha = 1
  }
}

// ---------- componentes ----------
export function DeathCard({ k, nameOf, me, onClose }) {
  if (!k) return null
  const mine = k.victim === me
  const dt = duelType(k.vic_speed, k.att_speed, k.vic_angle)
  const facts = [
    ...duelFacts(k.vic_speed, k.att_speed, k.vic_angle),
    k.att_dist != null && `Distância do atirador: ${Math.round(k.att_dist / 39.37)} m`,
    `Aliados vivos: ${k.mates_alive} · inimigos vivos: ${k.enemies_alive}`,
    k.mate_dist != null ? `Aliado mais próximo a ${Math.round(k.mate_dist / 39.37)} m (${k.mates_near} perto o bastante para trocar)` : 'Nenhum aliado vivo por perto',
    k.traded ? 'A morte foi trocada (trade) em até 5 s' : 'A morte não foi trocada',
    k.util_before ? `Usou ${k.util_before} granada(s) nos 20 s antes` : 'Não usou granada nos 20 s antes',
    k.victim_blind > 0 && `Estava cego (${k.victim_blind}s restantes)`,
    k.dmg_sources > 1 && `Levou dano de ${k.dmg_sources} inimigos nos últimos 5 s`,
    k.thru_smoke && 'Abate através da smoke',
    k.wallbang > 0 && 'Abate atravessando parede',
    k.attacker_blind && 'O atirador estava cego',
  ].filter(Boolean)
  return (
    <div className="death-card">
      <div className="dc-head">
        <div>
          <div className="dc-title">{mine ? 'Sua morte' : `Morte de ${nameOf(k.victim)}`} · {fmt(k.round_time)}</div>
          <div className="dc-sub">
            <b style={{ color: COL[k.attacker_side] }}>{nameOf(k.attacker) || 'Mundo'}</b> com {WEAPON(k.weapon)}{k.headshot ? ' · headshot' : ''}
          </div>
        </div>
        <button className="x" onClick={onClose}>×</button>
      </div>
      <ul>{facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
      {dt && (
        <div className="dc-tip">
          <TypeChip t={dt} />
          <span>{TIPOS[dt][1]}</span>
        </div>
      )}
    </div>
  )
}

export default function Round({ mid, rn, at, go }) {
  const [d, setD] = useState(null)
  const [me, setMe] = useState(null)
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  // velocidade: lembra a última escolhida
  const [speed, setSpeedState] = useState(() => {
    try { const v = +localStorage.getItem('replaySpeed'); return SPEEDS.includes(v) ? v : 1 } catch { return 1 }
  })
  const setSpeed = (v) => { setSpeedState(v); try { localStorage.setItem('replaySpeed', String(v)) } catch { /* sem storage */ } }
  const [tab, setTab] = useState('kills')
  const [names, setNames] = useState(true)
  const [floor, setFloor] = useState('main')
  const [sel, setSel] = useState(null)
  const canvasRef = useRef(null)
  const boxRef = useRef(null)
  const [box, setBox] = useState({ w: 700, h: 600 })
  const { ov, imgs } = useRadar(d?.map)

  useEffect(() => {
    setD(null); setSel(null); setPlaying(false)
    api(`/matches/${mid}/rounds/${rn}`).then((x) => { setD(x); setT(at && x.replay ? Math.max(x.replay.t0, at) : (x.replay?.t0 || x.round.start_tick)); if (x.replay) setPlaying(true) })
    api('/me').then((x) => setMe(x.steamid))
  }, [mid, rn])

  // o canvas ocupa a largura da coluna e a altura livre da janela
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const fit = () => {
      const top = el.getBoundingClientRect().top + window.scrollY
      const w = Math.floor(el.clientWidth)
      const h = Math.floor(Math.max(380, Math.min(w * 1.1, window.innerHeight - top - 120)))
      setBox((b) => (b.w === w && b.h === h ? b : { w, h }))
    }
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    addEventListener('resize', fit)
    fit()
    return () => { ro.disconnect(); removeEventListener('resize', fit) }
  }, [d])
  const view = useMemo(() => {
    const img = floor === 'lower' && imgs.lower ? imgs.lower : imgs.main
    const b = radarBox(img)
    // os dois andares usam o mesmo enquadramento (junta as duas caixas)
    const l = imgs.lower ? radarBox(imgs.lower) : b
    const u = { x0: Math.min(b.x0, l.x0), y0: Math.min(b.y0, l.y0), x1: Math.max(b.x1, l.x1), y1: Math.max(b.y1, l.y1) }
    return fitView(box.w, box.h, u)
  }, [box, imgs, floor])

  const rep = d?.replay
  const tEnd = rep ? rep.t0 + (rep.n - 1) * rep.step : 0

  // play
  useEffect(() => {
    if (!playing) return
    let last = performance.now(), id
    const loop = (now) => {
      const dt = (now - last) / 1000; last = now
      setT((x) => {
        const nx = x + dt * 64 * speed
        if (nx >= tEnd) { setPlaying(false); return tEnd }
        return nx
      })
      id = requestAnimationFrame(loop)
    }
    id = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(id)
  }, [playing, speed, tEnd])

  // teclado: espaço = play/pause, setas = ±5 s
  useEffect(() => {
    const f = (e) => {
      if (e.code === 'Space') { e.preventDefault(); setPlaying((p) => !p) }
      if (e.code === 'ArrowRight') setT((x) => Math.min(tEnd, x + 5 * 64))
      if (e.code === 'ArrowLeft') setT((x) => Math.max(rep?.t0 || 0, x - 5 * 64))
    }
    addEventListener('keydown', f)
    return () => removeEventListener('keydown', f)
  }, [tEnd, rep])

  // desenho
  useEffect(() => {
    const c = canvasRef.current
    if (!c || !ov || !rep) return
    const dpr = window.devicePixelRatio || 1
    if (c.width !== view.w * dpr || c.height !== view.h * dpr) { c.width = view.w * dpr; c.height = view.h * dpr }
    const ctx = c.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    draw(ctx, view, { ov, imgs, rep, t, me, kills: d.kills, grenades: d.grenades, bomb: d.bomb, floor, names, sel })
  }, [t, view, ov, imgs, rep, me, d, floor, names, sel])

  const nameOf = useMemo(() => {
    const m = {}
    rep?.players.forEach((p) => { m[p.sid] = p.name })
    return (sid) => m[sid] || ''
  }, [rep])
  const sideOf = useMemo(() => {
    const m = {}
    rep?.players.forEach((p) => { m[p.sid] = p.side })
    return (sid) => m[sid]
  }, [rep])

  if (!d) return <div className="loading"><div><div className="spinner" />Carregando round…</div></div>
  if (!rep) return <div className="page"><div className="card empty"><b>Sem replay para este round</b></div></div>

  const r = d.round
  const t0 = rep.t0
  const roundTime = (tick) => (tick - t0) / 64
  const seek = (tick) => { setT(Math.max(t0, Math.min(tEnd, tick))); }

  const clickCanvas = (e) => {
    if (!ov) return
    const rect = e.currentTarget.getBoundingClientRect()
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top
    const { z, ox, oy } = view
    let best = null, bd = 14
    for (const kl of d.kills) {
      if (kl.tick > t || kl.vx == null) continue
      const x = ox + ((kl.vx - ov.pos_x) / ov.scale) * z, y = oy + ((ov.pos_y - kl.vy) / ov.scale) * z
      const dd = Math.hypot(cx - x, cy - y)
      if (dd < bd) { bd = dd; best = kl }
    }
    setSel(best)
  }

  const f = Math.max(0, Math.min(rep.n - 1, Math.round((t - t0) / rep.step)))
  const events = tab === 'kills'
    ? [...d.kills.map((k) => ({ type: 'kill', tick: k.tick, k })), ...d.bomb.map((b) => ({ type: 'bomb', tick: b.tick, b }))].sort((a, b) => a.tick - b.tick)
    : d.grenades.filter((g) => g.type !== 'decoy').map((g) => ({ type: 'nade', tick: g.det_tick, g }))
  const myDeath = d.kills.find((k) => k.victim === me)
  const sideWon = r.winner_side
  const myPlayer = rep.players.find((p) => p.sid === me)

  return (
    <div className="page round-page">
      <div className="round-top">
        <button className="back" onClick={() => go(`#/partida/${mid}`)}><Icon.back /> Partida</button>
        <div className="round-nav">
          <button disabled={rn <= 1} onClick={() => go(`#/partida/${mid}/round/${rn - 1}`)}>‹</button>
          <div className="round-title">
            Round {rn}
            <span className={`side-badge ${sideWon}`}>{sideWon === 'CT' ? 'CT' : 'TR'} venceu</span>
            <span className="dim-txt">{reasonIcon(r.reason)} {REASON_TXT[r.reason] || r.reason}</span>
          </div>
          <button disabled={rn >= d.total} onClick={() => go(`#/partida/${mid}/round/${rn + 1}`)}>›</button>
        </div>
        <div className="buys">
          <span>A: {BUY_TXT[r.buy_a] || r.buy_a} (${(r.equip_a / 1000).toFixed(1)}k)</span>
          <span>B: {BUY_TXT[r.buy_b] || r.buy_b} (${(r.equip_b / 1000).toFixed(1)}k)</span>
          <CS2Button mid={mid} rounds={[{ round_num: rn, start_tick: r.start_tick }]} round={rn} className="btn-ghost sm" />
          <span className="sc">{r.score_a}:{r.score_b}</span>
        </div>
      </div>

      <div className="round-grid">
        <div className="roster">
          {['CT', 'T'].map((s) => (
            <div key={s} className="roster-team">
              <div className="roster-head" style={{ color: COL[s] }}>{s === 'CT' ? 'CT' : 'TR'}</div>
              {rep.players.filter((p) => p.side === s).map((p) => {
                const hp = p.hp[f] || 0
                const w = rep.weapons[p.w[f]]
                const eco = d.economy.find((e) => e.steamid === p.sid)
                return (
                  <div key={p.sid} className={`roster-row ${hp ? '' : 'dead'} ${p.sid === me ? 'me' : ''}`}>
                    <div className="rr-top"><span className="rr-name">{p.name}</span><span className="rr-hp">{hp || '✕'}</span></div>
                    <div className="hpbar"><i style={{ width: `${hp}%`, background: COL[s] }} /></div>
                    <div className="rr-sub"><span>{hp ? w : 'morto'}</span><span>${eco?.equip ?? '–'}</span></div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        <div className="stage" ref={boxRef}>
          <div className="canvas-wrap" style={{ width: view.w, height: view.h }}>
            {ov === false ? <div className="empty">Radar deste mapa não encontrado</div>
              : <canvas ref={canvasRef} style={{ width: view.w, height: view.h }} onClick={clickCanvas} />}
            <div className="map-tools">
              <button className={names ? 'on' : ''} onClick={() => setNames(!names)}>Nomes</button>
              {ov?.lower && <>
                <button className={floor === 'main' ? 'on' : ''} onClick={() => setFloor('main')}>Superior</button>
                <button className={floor === 'lower' ? 'on' : ''} onClick={() => setFloor('lower')}>Inferior</button>
              </>}
            </div>
            <DeathCard k={sel} nameOf={nameOf} me={me} onClose={() => setSel(null)} />
          </div>
          <div className="timeline" style={{ width: view.w }}>
            <button className="play" onClick={() => { if (t >= tEnd) setT(t0); setPlaying(!playing) }}>
              {playing ? <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
                : <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z" /></svg>}
            </button>
            <span className="time">{fmt(roundTime(t))}</span>
            <div className="track">
              <input type="range" min={t0} max={tEnd} step={1} value={t}
                onChange={(e) => { setT(+e.target.value) }} />
              <div className="marks">
                {d.kills.map((k) => (
                  <i key={k.tick + k.victim} title={`${nameOf(k.attacker)} → ${nameOf(k.victim)}`}
                    style={{ left: `${((k.tick - t0) / (tEnd - t0)) * 100}%`, background: COL[k.victim_side] || '#888', height: k.victim === me ? 14 : 9 }} />
                ))}
                {d.bomb.map((b) => <b key={b.tick} style={{ left: `${((b.tick - t0) / (tEnd - t0)) * 100}%` }} title={`Bomba ${b.kind}`} />)}
              </div>
            </div>
            <span className="time dim-txt">{fmt(roundTime(tEnd))}</span>
            {at && (
              <button className="replay-again" title="Volta para o começo do lance e dá play"
                onClick={() => { setSel(null); setT(Math.max(t0, at)); setPlaying(true) }}>↺ Ver o lance de novo</button>
            )}
            <div className="speeds">
              {SPEEDS.map((s) => <button key={s} className={s === speed ? 'on' : ''} onClick={() => setSpeed(s)}>{s}x</button>)}
            </div>
          </div>
        </div>

        <div className="side-col" style={{ height: view.h + 52 }}>
        <div className="events card">
          <div className="tabs">
            <button className={tab === 'kills' ? 'on' : ''} onClick={() => setTab('kills')}>Abates</button>
            <button className={tab === 'util' ? 'on' : ''} onClick={() => setTab('util')}>Utilitários</button>
          </div>
          <div className="ev-list">
            {events.map((ev, i) => {
              const past = ev.tick <= t
              if (ev.type === 'kill') {
                const k = ev.k
                return (
                  <button key={i} className={`ev ${past ? '' : 'future'} ${k.victim === me ? 'mine' : ''}`}
                    onClick={() => { seek(k.tick - 64); setSel(k); setPlaying(false) }}>
                    <div className="ev-line">
                      <b style={{ color: COL[k.attacker_side] }}>{nameOf(k.attacker) || 'Mundo'}</b>
                      <span className="wpn">{WEAPON(k.weapon)}{k.headshot ? ' ◎' : ''}</span>
                      <b style={{ color: COL[k.victim_side] }}>{nameOf(k.victim)}</b>
                    </div>
                    <div className="ev-meta">{fmt(k.round_time)}{k.first_kill ? ' · primeiro abate' : ''}{k.is_trade ? ' · trade' : ''}</div>
                  </button>
                )
              }
              if (ev.type === 'bomb') {
                const b = ev.b
                return (
                  <button key={i} className={`ev bomb ${past ? '' : 'future'}`} onClick={() => seek(b.tick - 64)}>
                    <div className="ev-line"><b>{nameOf(b.steamid) || 'Bomba'}</b> <span className="wpn">{b.kind} {b.site && `no ${b.site}`}</span></div>
                    <div className="ev-meta">{fmt(roundTime(b.tick))}</div>
                  </button>
                )
              }
              const g = ev.g
              const info = g.type === 'flash' ? `cegou ${g.enemies_blinded} inimigo(s)${g.mates_blinded ? `, ${g.mates_blinded} aliado(s)` : ''}`
                : g.damage ? `${g.damage} de dano em ${g.hits}` : ''
              return (
                <button key={i} className={`ev ${past ? '' : 'future'} ${g.thrower === me ? 'mine' : ''}`} onClick={() => seek(g.throw_tick - 16)}>
                  <div className="ev-line">
                    <b style={{ color: COL[g.side] }}>{nameOf(g.thrower)}</b>
                    <span className="wpn">{NADE_TXT[g.type]}</span>
                  </div>
                  <div className="ev-meta">{fmt(roundTime(g.det_tick))}{info && ` · ${info}`}</div>
                </button>
              )
            })}
          </div>
        </div>
        <div className="tip-card">
          <span className="ic"><Icon.bulb /></span>
          <div>
            {(() => {
              if (!myPlayer) return <><b>Sua morte</b><p>Escolha qual jogador é você na tela da partida.</p></>
              if (!myDeath) return <><b>Você sobreviveu a este round</b></>
              const dt = duelType(myDeath.vic_speed, myDeath.att_speed, myDeath.vic_angle)
              return (
                <>
                  <b>Você morreu aos {fmt(myDeath.round_time)} {dt && <TypeChip t={dt} />}</b>
                  <p className="round-death">
                    {duelFacts(myDeath.vic_speed, myDeath.att_speed, myDeath.vic_angle).join(' · ')}
                    {' '}<button className="link-btn" onClick={() => setSel(myDeath)}>Ver a morte no mapa</button>
                  </p>
                </>
              )
            })()}
          </div>
        </div>
        </div>
      </div>

    </div>
  )
}
