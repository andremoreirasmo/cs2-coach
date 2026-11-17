import { useState } from 'react'
// Utilidades compartilhadas: API, mapas, formatação e ícones.

export async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, { ...opts, headers: { 'X-Coach': '1', ...(opts.headers || {}) } })
  if (!r.ok) {
    let msg = `${r.status}`
    try { msg = (await r.json()).detail || msg } catch { /* sem corpo */ }
    throw new Error(msg)
  }
  return r.json()
}

export const post = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

const MAPS = {
  de_inferno: { name: 'Inferno', g: ['#7a2e1c', '#c4652b'] },
  de_mirage: { name: 'Mirage', g: ['#6b5130', '#c59b5a'] },
  de_dust2: { name: 'Dust II', g: ['#77612f', '#d2b366'] },
  de_nuke: { name: 'Nuke', g: ['#1f4d5c', '#4aa3b8'] },
  de_ancient: { name: 'Ancient', g: ['#2a4a2c', '#6f9a54'] },
  de_anubis: { name: 'Anubis', g: ['#1f5450', '#59b0a3'] },
  de_vertigo: { name: 'Vertigo', g: ['#28406b', '#6d8fc9'] },
  de_overpass: { name: 'Overpass', g: ['#34503a', '#86a77a'] },
  de_cache: { name: 'Cache', g: ['#3d4a2a', '#8fa35c'] },
  de_train: { name: 'Train', g: ['#3b4048', '#8a939f'] },
}
export function mapInfo(id) {
  return MAPS[id] || { name: (id || '?').replace(/^de_/, ''), g: ['#2a2f3a', '#535b6b'] }
}
// foto do mapa (tirada dos arquivos do CS) com um degradê por cima para o texto aparecer;
// se a foto não existir, fica só o degradê da cor do mapa
export function mapBg(id) {
  const { g } = mapInfo(id)
  const fade = 'linear-gradient(90deg, rgba(13,15,19,.15) 0%, rgba(13,15,19,.35) 60%, rgba(13,15,19,.85) 100%)'
  return {
    backgroundImage: `${fade}, url(/api/mapshot/${id}), radial-gradient(120% 140% at 0% 0%, ${g[1]} 0%, ${g[0]} 55%, #0d0f13 100%)`,
    backgroundSize: 'cover', backgroundPosition: 'center',
  }
}

export const SOURCE = { faceit: 'FACEIT', valve: 'Premier / Comp.', desconhecido: 'Partida' }

export function when(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const diff = (Date.now() - d) / 1000
  if (diff < 3600) return `há ${Math.max(1, Math.round(diff / 60))} min`
  if (diff < 86400) return `há ${Math.round(diff / 3600)} h`
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) +
    ' · ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

// quando a partida foi jogada; sem a data real (demo sem chave da FACEIT), mostra a do download
export function playedWhen(m) {
  if (m.played_at) return when(m.played_at)
  const t = m.ended_at || m.started_at
  return t ? `baixada ${when(t)}` : ''
}

export function ratingColor(r) {
  if (r == null) return 'var(--muted)'
  if (r >= 1.15) return 'var(--win)'
  if (r >= 0.95) return 'var(--text)'
  return 'var(--loss)'
}

export function resultClass(r) {
  return r === 'vitoria' ? 'win' : r === 'derrota' ? 'loss' : 'draw'
}

// foto de perfil da Steam; sem foto, a inicial do nome numa cor fixa
export function Avatar({ p, size = 28 }) {
  const [bad, setBad] = useState(false)
  const name = p?.name || p?.steam_name || '?'
  if (p?.avatar && !bad) {
    return <img className="avatar img" src={p.avatar} alt="" width={size} height={size} onError={() => setBad(true)} referrerPolicy="no-referrer" />
  }
  return <span className="avatar" style={{ background: avatarColor(name), width: size, height: size }}>{name.slice(0, 1).toUpperCase()}</span>
}

export function avatarColor(s) {
  let h = 0
  for (const c of s || '') h = (h * 31 + c.charCodeAt(0)) % 360
  return `hsl(${h} 55% 62%)`
}

const s = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }
export const Icon = {
  home: (p) => <svg {...s} width={22} height={22} {...p}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" /></svg>,
  chart: (p) => <svg {...s} width={22} height={22} {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>,
  map: (p) => <svg {...s} width={22} height={22} {...p}><path d="m9 4-6 2v14l6-2 6 2 6-2V4l-6 2z" /><path d="M9 4v14M15 6v14" /></svg>,
  aim: (p) => <svg {...s} width={22} height={22} {...p}><circle cx="12" cy="12" r="8" /><path d="M12 2v5M12 17v5M2 12h5M17 12h5" /></svg>,
  gear: (p) => <svg {...s} width={22} height={22} {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>,
  trophy: (p) => <svg {...s} width={22} height={22} {...p}><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z" /><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3" /></svg>,
  versus: (p) => <svg {...s} width={22} height={22} {...p}><circle cx="8" cy="8" r="3" /><circle cx="16" cy="16" r="3" /><path d="M3 20a5 5 0 0 1 8-4M21 4a5 5 0 0 1-8 4" /></svg>,
  back: (p) => <svg {...s} {...p}><path d="m15 18-6-6 6-6" /></svg>,
  bulb: (p) => <svg {...s} width={22} height={22} {...p}><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z" /></svg>,
  // como o round acabou
  skull: (p) => <svg {...s} {...p}><path d="M12 3a8 8 0 0 0-8 8c0 2.8 1.4 4.6 3 5.6V20h10v-3.4c1.6-1 3-2.8 3-5.6a8 8 0 0 0-8-8z" /><circle cx="9" cy="11" r="1.6" fill="currentColor" /><circle cx="15" cy="11" r="1.6" fill="currentColor" /><path d="M10 20v-2M14 20v-2" /></svg>,
  boom: (p) => <svg {...s} {...p}><path d="m12 2 2 6 6-3-3 6 5 3-6 1 1 6-5-4-5 4 1-6-6-1 5-3-3-6 6 3z" /></svg>,
  defuse: (p) => <svg {...s} {...p}><path d="M5 19 19 5M14 4l6 6M4 14l6 6" /><circle cx="6.5" cy="17.5" r="1" fill="currentColor" /></svg>,
  clock: (p) => <svg {...s} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>,
}

export function reasonIcon(reason) {
  if (reason === 'bomb_exploded') return <Icon.boom />
  if (reason === 'bomb_defused') return <Icon.defuse />
  if (reason === 'target_saved' || reason === 'time_ran_out') return <Icon.clock />
  return <Icon.skull />
}
export const REASON_TXT = {
  t_killed: 'TRs eliminados', ct_killed: 'CTs eliminados', bomb_exploded: 'Bomba explodiu',
  bomb_defused: 'Bomba desarmada', target_saved: 'Tempo esgotado', time_ran_out: 'Tempo esgotado',
}


// ---------- rank do jogador ----------
const SKILL = ['Prata I', 'Prata II', 'Prata III', 'Prata IV', 'Prata Elite', 'Prata Elite Mestre', 'Ouro I', 'Ouro II',
  'Ouro III', 'Ouro Mestre', 'AK I', 'AK II', 'AK Cruzada', 'Xerife', 'Águia I', 'Águia Mestre', 'Supremo', 'Global Elite']
const premierColor = (r) => (r >= 30000 ? '#f5c542' : r >= 25000 ? '#eb4b4b' : r >= 20000 ? '#d32ce6'
  : r >= 15000 ? '#8847ff' : r >= 10000 ? '#4b69ff' : r >= 5000 ? '#5e98d9' : '#b0c3d9')
const faceitColor = (l) => (l >= 10 ? '#fe1f00' : l >= 8 ? '#ff6309' : l >= 4 ? '#ffc800' : l >= 2 ? '#1ce400' : '#eeeeee')

// devolve {txt, color, title} ou null
export function rankOf(p, source) {
  if (source === 'faceit') {
    if (p.faceit_level) return { txt: `${p.faceit_level}`, color: faceitColor(p.faceit_level), title: `FACEIT nível ${p.faceit_level}${p.faceit_elo ? ` · ${p.faceit_elo} de elo` : ''} (atual)`, lvl: true }
    return null
  }
  const r = p.rank
  if (!r) return null
  if (r <= 18) return { txt: SKILL[r - 1], color: '#b0c3d9', title: `Competitivo: ${SKILL[r - 1]}` }
  return { txt: r.toLocaleString('pt-BR'), color: premierColor(r), title: `Premier: ${r.toLocaleString('pt-BR')}${p.rank_wins ? ` · ${p.rank_wins} vitórias` : ''}` }
}

export function RankBadge({ p, source }) {
  const k = rankOf(p, source)
  if (!k) {
    if (source === 'faceit') return <span className="rank-badge none" title="O nível FACEIT aparece com a chave opcional da FACEIT (Configurações → Avançado)">—</span>
    return null
  }
  return <span className={`rank-badge ${k.lvl ? 'lvl' : ''}`} style={{ color: k.color, borderColor: k.color }} title={k.title}>{k.txt}</span>
}

// "Time A" / "Time B" (Premier não tem nome de time): usa o melhor jogador do time
export function teamLabel(name, mvp) {
  if (mvp && (!name || /^Time [AB]$/.test(name))) return `Time do ${mvp}`
  return name
}


// ---------- abas ----------
// Telas que precisam saber quem é você (Geral, Mira): o que fazer quando ainda não dá.
export function NoMe({ n }) {
  if (!n) {
    return (
      <div className="card empty">
        <b>Nenhuma partida analisada ainda</b>
        Traga sua primeira partida pela tela inicial: os números aparecem aqui assim que ela for analisada.
        <div><button className="btn-primary" onClick={() => { location.hash = '#/' }}>Ir para o início</button></div>
      </div>
    )
  }
  return <div className="card empty"><b>Escolha quem é você</b>Abra uma partida e clique no seu nome no placar.</div>
}

export function useTab(page, first) {
  const key = `tab:${page}`
  const [tab, setTab] = useState(() => { try { return localStorage.getItem(key) || first } catch { return first } })
  const set = (v) => { setTab(v); try { localStorage.setItem(key, v) } catch { /* sem storage */ } }
  return [tab, set]
}

// opts: [[valor, rótulo, marcador opcional]]
export function Tabs({ value, set, opts }) {
  const ok = opts.some(([v]) => v === value)
  const cur = ok ? value : opts[0][0]
  return (
    <div className="tabs" role="tablist">
      {opts.map(([v, l, dot]) => (
        <button key={v} role="tab" aria-selected={cur === v} className={cur === v ? 'on' : ''} onClick={() => set(v)}>
          {l}{dot ? <span className="tab-dot" title={dot} /> : null}
        </button>
      ))}
    </div>
  )
}
