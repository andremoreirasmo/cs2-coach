import { useEffect, useMemo, useRef, useState } from 'react'
import { DeathCard, fmt, useRadar } from './Round.jsx'
import { duelType } from './Duels.jsx'
import { api, mapBg, mapInfo, when } from './lib.jsx'

// morte em que você se mexia no duelo (entrou no ângulo dele ou correndo): null se a partida não tem a medida
const bad = (k) => { const t = duelType(k.vic_speed, k.att_speed, k.vic_angle); return t && (t === 'entrou' || t === 'correndo') }

const FONTES = [['todas', 'Todas'], ['faceit', 'FACEIT'], ['valve', 'Premier / Comp.']]
const LADOS = [['ambos', 'CT e TR'], ['CT', 'CT'], ['T', 'TR']]
const ULTIMAS = [[5, '5'], [10, '10'], [20, '20'], [0, 'Todas']]
const CAMADAS = [['mortes', 'Mortes'], ['abates', 'Abates'], ['granadas', 'Granadas'], ['biblioteca', 'Biblioteca de granadas']]
const NOTA = { repete: ['Cai sempre no mesmo lugar', '#3ddc84'], varia: ['Cai em lugares diferentes', '#f4b23e'], uma_vez: ['Jogou 1 vez', '#8a93a4'],
  boa: ['Funciona', '#3ddc84'], as_vezes: ['Funciona às vezes', '#f4b23e'], ruim: ['Rende pouco', '#ff5d62'] }
const notaOf = (g) => NOTA[g.nota === 'uma vez' ? 'uma_vez' : g.nota] || ['', '#888']
const NADES = [['todas', 'Todas'], ['smoke', 'Smoke'], ['flash', 'Flash'], ['he', 'HE'], ['molotov', 'Molotov']]
const NADE_COL = { smoke: '#c9d1dc', flash: '#fff176', he: '#ff6b6b', molotov: '#ff9f43', decoy: '#8a93a4' }
const NADE_TXT = { smoke: 'Smoke', flash: 'Flash', he: 'HE', molotov: 'Molotov', decoy: 'Decoy' }
// paletas do mapa de calor: transparente -> forte
const PALETTE = {
  mortes: [[0, 'rgba(255,93,98,0)'], [0.25, 'rgba(255,93,98,.55)'], [0.6, 'rgba(255,140,60,.85)'], [1, 'rgba(255,240,120,.95)']],
  abates: [[0, 'rgba(61,220,132,0)'], [0.25, 'rgba(61,220,132,.55)'], [0.6, 'rgba(150,240,120,.85)'], [1, 'rgba(240,255,170,.95)']],
}

function Chips({ value, set, opts, label }) {
  return (
    <div className="chip-group">
      {label && <span className="cg-l">{label}</span>}
      <div className="chips">
        {opts.map(([v, l]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => set(v)}>{l}</button>)}
      </div>
    </div>
  )
}

function paletteData(stops) {
  const c = document.createElement('canvas')
  c.width = 256; c.height = 1
  const g = c.getContext('2d')
  const grd = g.createLinearGradient(0, 0, 256, 0)
  for (const [o, col] of stops) grd.addColorStop(o, col)
  g.fillStyle = grd; g.fillRect(0, 0, 256, 1)
  return g.getImageData(0, 0, 256, 1).data
}

// mapa de calor: acumula manchas suaves e colore pela densidade
function drawHeat(ctx, size, pts, stops) {
  if (!pts.length) return
  const off = document.createElement('canvas')
  off.width = size; off.height = size
  const o = off.getContext('2d')
  const r = size * 0.032
  const a = Math.min(0.5, Math.max(0.12, 3 / Math.sqrt(pts.length)))
  for (const [x, y] of pts) {
    const g = o.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, `rgba(0,0,0,${a})`); g.addColorStop(1, 'rgba(0,0,0,0)')
    o.fillStyle = g
    o.fillRect(x - r, y - r, r * 2, r * 2)
  }
  const img = o.getImageData(0, 0, size, size)
  const pal = paletteData(stops)
  const d = img.data
  for (let i = 0; i < d.length; i += 4) {
    const v = d[i + 3]
    if (!v) continue
    const j = v * 4
    d[i] = pal[j]; d[i + 1] = pal[j + 1]; d[i + 2] = pal[j + 2]; d[i + 3] = pal[j + 3]
  }
  o.putImageData(img, 0, 0)
  ctx.drawImage(off, 0, 0, size, size)
}

function Summary({ camada, data, items, nade }) {
  const count = (arr, key) => {
    const c = {}
    for (const x of arr) if (x[key]) c[x[key]] = (c[x[key]] || 0) + 1
    return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 6)
  }
  const pct = (n, d) => (d ? Math.round(100 * n / d) : 0)
  const Places = ({ list }) => {
    const max = list[0]?.[1] || 1
    return list.map(([k, v]) => <div key={k} className="pbar place"><span>{k}</span><div><i style={{ width: `${100 * v / max}%` }} /></div><b>{v}</b></div>)
  }
  if (camada === 'mortes') {
    const typed = items.filter((k) => bad(k) != null)
    return (
      <>
        <div className="mstats">
          <div><b>{items.length}</b><span>mortes</span></div>
          <div><b>{pct(items.filter((k) => !k.traded).length, items.length)}%</b><span>não trocadas</span></div>
          <div><b>{pct(items.filter((k) => k.first_kill).length, items.length)}%</b><span>1ª do round</span></div>
          <div><b>{typed.length ? `${pct(typed.filter(bad).length, typed.length)}%` : '—'}</b><span>em movimento no ângulo dele</span></div>
        </div>
        <h3>Onde você mais morre</h3>
        <Places list={count(items, 'vic_place')} />
      </>
    )
  }
  if (camada === 'abates') {
    return (
      <>
        <div className="mstats">
          <div><b>{items.length}</b><span>abates</span></div>
          <div><b>{pct(items.filter((k) => k.headshot).length, items.length)}%</b><span>headshot</span></div>
          <div><b>{pct(items.filter((k) => k.first_kill).length, items.length)}%</b><span>abertura</span></div>
          <div><b>{pct(items.filter((k) => k.is_trade).length, items.length)}%</b><span>trades</span></div>
        </div>
        <h3>De onde você mais mata</h3>
        <Places list={count(items, 'att_place')} />
      </>
    )
  }
  const all = data.granadas
  const by = (t) => all.filter((g) => g.type === t)
  const fl = by('flash'), he = [...by('he'), ...by('molotov')]
  return (
    <>
      <div className="mstats">
        {['smoke', 'flash', 'he', 'molotov'].map((t) => (
          <div key={t}><b style={{ color: NADE_COL[t] }}>{by(t).length}</b><span>{NADE_TXT[t]}</span></div>
        ))}
      </div>
      <h3>Flashes</h3>
      <div className="kv"><span>Cegaram pelo menos 1 inimigo</span><b>{pct(fl.filter((g) => g.enemies_blinded > 0).length, fl.length)}%</b></div>
      <div className="kv"><span>Inimigos cegados por flash</span><b>{fl.length ? (fl.reduce((s, g) => s + (g.enemies_blinded || 0), 0) / fl.length).toFixed(1) : '—'}</b></div>
      <div className="kv"><span>Cegaram aliados</span><b>{pct(fl.filter((g) => g.mates_blinded > 0).length, fl.length)}%</b></div>
      <h3>HE e molotov</h3>
      <div className="kv"><span>Dano total</span><b>{he.reduce((s, g) => s + (g.damage || 0), 0)}</b></div>
      <div className="kv"><span>Acertaram alguém</span><b>{pct(he.filter((g) => g.damage > 0).length, he.length)}%</b></div>
      <div className="kv"><span>Dano médio por granada</span><b>{he.length ? (he.reduce((s, g) => s + (g.damage || 0), 0) / he.length).toFixed(0) : '—'}</b></div>
      {nade !== 'todas' && <p className="hint-line">Mostrando só {NADE_TXT[nade]} no mapa.</p>}
    </>
  )
}

function effect(g) {
  if (g.tipo === 'flash') return `cega ${g.cegou} inimigo(s) em média${g.cegou_aliado ? ` · ${g.cegou_aliado} aliado(s)` : ''}`
  if (g.tipo === 'he' || g.tipo === 'molotov') return `${g.dano} de dano em média`
  return g.n > 1 ? `cai num raio de ${g.espalhamento_m} m` : ''
}

function Library({ lib, sel, pick }) {
  if (!lib) return <p className="hint-line">Carregando…</p>
  if (!lib.grupos.length) return <p className="hint-line">Nenhuma granada sua neste filtro.</p>
  const r = lib.resumo || {}
  return (
    <>
      <div className="mstats">
        {['smoke', 'flash', 'he', 'molotov'].map((t) => (
          <div key={t}><b style={{ color: NADE_COL[t] }}>{r[t]?.n || 0}</b><span>{NADE_TXT[t]}</span></div>
        ))}
      </div>
      <p className="hint-line">Suas granadas agrupadas por onde você joga e onde caem. Clique para ver no mapa e abrir o replay.</p>
      <div className="lib-list">
        {lib.grupos.map((g, i) => {
          const [txt, col] = notaOf(g)
          return (
            <button key={i} className={`lib-item ${sel === g ? 'on' : ''}`} onClick={() => pick(g)}>
              <span className="lib-type" style={{ color: NADE_COL[g.tipo] }}>{NADE_TXT[g.tipo]} · {g.lado === 'CT' ? 'CT' : 'TR'}</span>
              <b>{g.de} → {g.para}</b>
              <span className="lib-meta"><em>{g.n}×</em> {effect(g)}</span>
              <span className="lib-nota" style={{ color: col }}>{txt}</span>
            </button>
          )
        })}
      </div>
    </>
  )
}

function GroupCard({ g, map, go, onClose }) {
  const [txt, col] = notaOf(g)
  const eff = effect(g)
  return (
    <div className="sel death-card">
      <div className="dc-head">
        <div>
          <div className="dc-title" style={{ color: NADE_COL[g.tipo] }}>{NADE_TXT[g.tipo]} · {g.de} → {g.para}</div>
          <div className="dc-sub">{g.lado === 'CT' ? 'CT' : 'TR'} · {g.n} vez(es) · <span style={{ color: col }}>{txt}</span></div>
        </div>
        <button className="x" onClick={onClose}>×</button>
      </div>
      <ul>
        {eff && <li>{eff[0].toUpperCase() + eff.slice(1)}</li>}
        {g.tipo !== 'smoke' && g.tipo !== 'molotov' && <li>Deu certo {g.boas} de {g.n} vezes</li>}
        <li>A linha vai de onde você jogou até onde caiu (média).</li>
      </ul>
      <div className="lib-ex">
        {g.exemplos.map((e, i) => (
          <button key={i} className={`btn-ghost sm ${e.boa ? '' : 'dim'}`}
            onClick={() => go(`#/partida/${e.match_id}/round/${e.round_num}/t/${Math.max(0, e.tick - 64 * 8)}`)}>
            ▶ Round {e.round_num}{e.boa ? '' : ' (não rendeu)'}
          </button>
        ))}
      </div>
      <div className="sel-meta">{mapInfo(map).name} · abre o replay 3 s antes do lançamento</div>
    </div>
  )
}

function Selected({ sel, go, onClose }) {
  if (!sel) return <p className="hint-line">Clique num ponto do mapa para ver o que aconteceu.</p>
  const { kind, it } = sel
  const meta = <div className="sel-meta">{mapInfo(it.map).name} · round {it.round_num}{it.quando ? ` · ${when(it.quando)}` : ''}</div>
  const replay = <button className="btn-primary sm" onClick={() => go(`#/partida/${it.match_id}/round/${it.round_num}`)}>▶ Ver no replay</button>
  if (kind === 'mortes') {
    return (
      <div className="sel">
        <DeathCard k={it} me={it.victim} onClose={onClose} nameOf={(sid) => (sid === it.attacker ? it.attacker_name : '')} />
        <div className="sel-foot">{meta}{replay}</div>
      </div>
    )
  }
  if (kind === 'abates') {
    return (
      <div className="sel death-card">
        <div className="dc-head">
          <div>
            <div className="dc-title">Seu abate · {fmt(it.round_time)}</div>
            <div className="dc-sub"><b>{it.victim_name}</b> com {(it.weapon || '').replace('_silencer', '-S')}{it.headshot ? ' · headshot' : ''}</div>
          </div>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <ul>
          {it.att_place && <li>Você em {it.att_place}{it.vic_place ? `, ele em ${it.vic_place}` : ''}</li>}
          {it.att_dist != null && <li>Distância: {Math.round(it.att_dist / 39.37)} m</li>}
          {it.first_kill ? <li>Abertura do round</li> : null}
          {it.is_trade ? <li>Trade: vingou um aliado</li> : null}
          {it.thru_smoke ? <li>Através da smoke</li> : null}
          {it.wallbang ? <li>Atravessando parede</li> : null}
        </ul>
        <div className="sel-foot">{meta}{replay}</div>
      </div>
    )
  }
  return (
    <div className="sel death-card">
      <div className="dc-head">
        <div>
          <div className="dc-title" style={{ color: NADE_COL[it.type] }}>{NADE_TXT[it.type] || it.type}</div>
          <div className="dc-sub">Lançada de {it.side === 'CT' ? 'CT' : 'TR'}</div>
        </div>
        <button className="x" onClick={onClose}>×</button>
      </div>
      <ul>
        {it.type === 'flash' && <li>Cegou {it.enemies_blinded} inimigo(s){it.mates_blinded ? ` e ${it.mates_blinded} aliado(s)` : ''}{it.blind_time ? ` · ${it.blind_time.toFixed(1)} s de cegueira somada` : ''}</li>}
        {(it.type === 'he' || it.type === 'molotov') && <li>{it.damage ? `${it.damage} de dano em ${it.hits} jogador(es)` : 'Não acertou ninguém'}</li>}
        {it.type === 'smoke' && <li>A linha mostra de onde você jogou até onde ela caiu.</li>}
      </ul>
      <div className="sel-foot">{meta}{replay}</div>
    </div>
  )
}

export default function Maps({ go }) {
  const [maps, setMaps] = useState(null)
  const [map, setMap] = useState(null)
  const [fonte, setFonte] = useState('todas')
  const [lado, setLado] = useState('ambos')
  const [ultimas, setUltimas] = useState(0)
  const [camada, setCamada] = useState('mortes')
  const [nade, setNade] = useState('todas')
  const [pontos, setPontos] = useState(true)
  const [floor, setFloor] = useState('main')
  const [data, setData] = useState(null)
  const [lib, setLib] = useState(null)
  const [sel, setSel] = useState(null)
  const canvasRef = useRef(null)
  const boxRef = useRef(null)
  const [size, setSize] = useState(640)
  const { ov, imgs } = useRadar(map)

  useEffect(() => {
    api('/mapas').then((l) => { setMaps(l); if (l.length) setMap((m) => m || l[0].map) }).catch(() => setMaps([]))
  }, [])
  useEffect(() => {
    if (!map) return
    setSel(null)
    api(`/mapas/${map}?lado=${lado}&fonte=${fonte}&ultimas=${ultimas}`).then(setData).catch(() => {})
  }, [map, lado, fonte, ultimas])
  useEffect(() => {
    if (!map || camada !== 'biblioteca') return
    setLib(null)
    api(`/granadas/${map}?tipo=${nade}&lado=${lado}&fonte=${fonte}&ultimas=${ultimas}`).then(setLib).catch(() => setLib({ grupos: [], lances: [] }))
  }, [map, camada, nade, lado, fonte, ultimas])
  useEffect(() => { setSel(null); setFloor('main') }, [map])
  useEffect(() => setSel(null), [camada, nade])
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize(Math.floor(Math.min(e.contentRect.width, window.innerHeight - 190))))
    if (boxRef.current) ro.observe(boxRef.current)
    return () => ro.disconnect()
  }, [maps])

  // pontos da camada atual já no andar escolhido, em pixels do canvas
  const items = useMemo(() => {
    if (!data || !ov) return []
    const zOf = (it) => (camada === 'mortes' ? it.vz : camada === 'abates' ? it.az : it.z)
    const onFloor = (z) => !ov.lower || z == null || (floor === 'lower' ? z < ov.lower.z_max : z >= ov.lower.z_max)
    if (camada === 'biblioteca') return lib?.grupos || []
    let arr = camada === 'granadas' ? data.granadas.filter((g) => g.type !== 'decoy' && (nade === 'todas' || g.type === nade)) : data[camada]
    return arr.filter((it) => onFloor(zOf(it))).map((it) => ({ ...it, map }))
  }, [data, lib, ov, camada, nade, floor, map])

  const toPx = (x, y) => [((x - ov.pos_x) / ov.scale) * (size / 1024), ((ov.pos_y - y) / ov.scale) * (size / 1024)]
  const posOf = (it) => (camada === 'mortes' ? [it.vx, it.vy] : camada === 'abates' ? [it.ax, it.ay] : [it.x, it.y])
  const pickGroup = (g) => setSel(sel?.it === g ? null : { kind: 'biblioteca', it: g })

  useEffect(() => {
    const c = canvasRef.current
    if (!c || !ov) return
    const dpr = window.devicePixelRatio || 1
    if (c.width !== size * dpr) { c.width = size * dpr; c.height = size * dpr }
    const ctx = c.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, size, size)
    const img = floor === 'lower' && imgs.lower ? imgs.lower : imgs.main
    if (img) { ctx.globalAlpha = 0.9; ctx.drawImage(img, 0, 0, size, size); ctx.globalAlpha = 1 }
    ctx.fillStyle = 'rgba(10,12,16,.25)'; ctx.fillRect(0, 0, size, size)

    if (camada === 'biblioteca') {
      const max = Math.max(1, ...items.map((g) => g.n))
      const on = sel?.it
      for (const g of [...items].sort((a, b) => a.n - b.n)) {
        const [sx, sy] = toPx(g.tx, g.ty), [x, y] = toPx(g.x, g.y)
        const col = NADE_COL[g.tipo] || '#ccc'
        const dim = !!on && on !== g
        const bad = g.nota === 'ruim' || g.nota === 'varia'
        ctx.globalAlpha = dim ? 0.08 : bad ? 0.35 : 0.7
        ctx.strokeStyle = col; ctx.lineWidth = 1 + 3 * (g.n / max)
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(x, y); ctx.stroke()
        ctx.beginPath(); ctx.arc(sx, sy, 2.5, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill()
        ctx.beginPath(); ctx.arc(x, y, 4 + 6 * (g.n / max), 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill()
        ctx.globalAlpha = 1
      }
    } else if (camada !== 'granadas') {
      ctx.save(); ctx.scale(1, 1)
      drawHeat(ctx, size, items.map((it) => toPx(...posOf(it))), PALETTE[camada])
      ctx.restore()
      if (pontos) {
        for (const it of items) {
          const [x, y] = toPx(...posOf(it))
          ctx.beginPath(); ctx.arc(x, y, 2.6, 0, Math.PI * 2)
          ctx.fillStyle = camada === 'mortes' ? (bad(it) ? '#ff5d62' : '#ffffff') : '#3ddc84'
          ctx.globalAlpha = 0.9; ctx.fill(); ctx.globalAlpha = 1
        }
      }
    } else {
      for (const g of items) {
        const [x, y] = toPx(g.x, g.y)
        const col = NADE_COL[g.type] || '#ccc'
        if (g.tx != null) {
          const [sx, sy] = toPx(g.tx, g.ty)
          ctx.strokeStyle = col; ctx.globalAlpha = 0.18; ctx.lineWidth = 1
          ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(x, y); ctx.stroke(); ctx.globalAlpha = 1
        }
        const good = g.type === 'flash' ? g.enemies_blinded > 0 : g.type === 'smoke' ? true : g.damage > 0
        const r = g.type === 'flash' ? 3 + 1.6 * Math.min(4, g.enemies_blinded || 0) : g.type === 'smoke' ? 5 : 3 + Math.min(6, (g.damage || 0) / 25)
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2)
        ctx.fillStyle = col; ctx.globalAlpha = good ? 0.85 : 0.28; ctx.fill(); ctx.globalAlpha = 1
      }
    }
    // selecionado
    if (sel && camada !== 'biblioteca') {
      const it = sel.it
      const [x, y] = toPx(...posOf(it))
      if (camada === 'mortes' && it.ax != null) {
        const [ax, ay] = toPx(it.ax, it.ay)
        ctx.strokeStyle = '#ff5d62'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(x, y); ctx.stroke(); ctx.setLineDash([])
        ctx.beginPath(); ctx.arc(ax, ay, 5, 0, Math.PI * 2); ctx.fillStyle = '#ff5d62'; ctx.fill()
      }
      if (camada === 'abates' && it.vx != null) {
        const [vx, vy] = toPx(it.vx, it.vy)
        ctx.strokeStyle = '#3ddc84'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(vx, vy); ctx.stroke(); ctx.setLineDash([])
        ctx.beginPath(); ctx.arc(vx, vy, 4, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill()
      }
      if (camada === 'granadas' && it.tx != null) {
        const [sx, sy] = toPx(it.tx, it.ty)
        ctx.strokeStyle = NADE_COL[it.type]; ctx.lineWidth = 2
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(x, y); ctx.stroke()
        ctx.beginPath(); ctx.arc(sx, sy, 4, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill()
      }
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2)
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke()
    }
  }, [items, ov, imgs, size, floor, pontos, sel, camada])

  const click = (e) => {
    if (!ov) return
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - r.left, my = e.clientY - r.top
    let best = null, bd = 14 * 14
    for (const it of items) {
      const [x, y] = toPx(...posOf(it))
      const d = (x - mx) ** 2 + (y - my) ** 2
      if (d < bd) { bd = d; best = it }
    }
    setSel(best ? { kind: camada, it: best } : null)
  }

  if (maps === null) return <div className="loading"><div><div className="spinner" />Carregando…</div></div>
  if (!maps.length) return <div className="page"><div className="card empty"><b>Nenhum mapa ainda</b>Os mapas aparecem aqui quando houver partidas analisadas e você tiver escolhido qual jogador é você.</div></div>

  return (
    <div className="page">
      <div className="topbar">
        <div>
          <h1>Mapas</h1>
          <div className="sub">Onde você morre, onde você mata e onde caem as suas granadas, somando suas partidas</div>
        </div>
      </div>
      <div className="map-pick">
        {maps.map((m) => (
          <button key={m.map} className={`mp ${m.map === map ? 'on' : ''}`} style={mapBg(m.map)} onClick={() => setMap(m.map)}>
            <b>{mapInfo(m.map).name}</b><span>{m.partidas} partida{m.partidas > 1 ? 's' : ''}</span>
          </button>
        ))}
      </div>
      <div className="map-filters">
        <Chips value={camada} set={setCamada} opts={CAMADAS} />
        {(camada === 'granadas' || camada === 'biblioteca') && <Chips value={nade} set={setNade} opts={NADES} />}
        <Chips value={lado} set={setLado} opts={LADOS} />
        <Chips value={ultimas} set={setUltimas} opts={ULTIMAS} label="Partidas" />
        <Chips value={fonte} set={setFonte} opts={FONTES} />
      </div>
      <div className="map-layout">
        <div className="map-box" ref={boxRef}>
          <canvas ref={canvasRef} style={{ width: size, height: size, cursor: 'crosshair' }} onClick={click} />
          <div className="map-tools">
            {camada !== 'granadas' && camada !== 'biblioteca' && <button className={pontos ? 'on' : ''} onClick={() => setPontos(!pontos)}>Pontos</button>}
            {ov?.lower && <>
              <button className={floor === 'main' ? 'on' : ''} onClick={() => setFloor('main')}>Superior</button>
              <button className={floor === 'lower' ? 'on' : ''} onClick={() => setFloor('lower')}>Inferior</button>
            </>}
          </div>
          {camada === 'mortes' && pontos && <div className="map-legend"><i style={{ background: '#ff5d62' }} />você se mexendo no duelo <i style={{ background: '#fff' }} />outras</div>}
          {camada === 'biblioteca' && <div className="map-legend">Linha = de onde você joga até onde cai · mais grossa = joga mais vezes · apagada = rende pouco ou varia</div>}
          {camada === 'granadas' && <div className="map-legend">Bolinha apagada = não cegou / não causou dano · tamanho = efeito</div>}
        </div>
        <div className="map-side card">
          {data && <div className="sel-meta" style={{ marginBottom: 10 }}>{data.partidas} partida(s) neste filtro</div>}
          {camada === 'biblioteca' ? (
            <>
              {sel && <div className="sel-wrap"><GroupCard g={sel.it} map={map} go={go} onClose={() => setSel(null)} /></div>}
              <Library lib={lib} sel={sel?.it} pick={pickGroup} />
            </>
          ) : (
            <>
              {data && <Summary camada={camada} data={data} items={items} nade={nade} />}
              <div className="sel-wrap"><Selected sel={sel} go={go} onClose={() => setSel(null)} /></div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
