import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BestPlays } from './Moments.jsx'
import { FaceitSyncButton, syncText, useFaceitSync } from './FaceitSync.jsx'
import { SOURCE, Tabs, api, mapBg, mapInfo, playedWhen, post, teamLabel, ratingColor, resultClass, useTab } from './lib.jsx'

const STATUS = {
  ao_vivo: 'Partida em andamento',
  terminada: 'Partida terminada — procurando a demo',
  aguardando_demo: 'Aguardando a demo',
  demo_pronta: 'Demo encontrada — analisando…',
  erro: 'Não consegui ler a demo desta partida',
}

// Adiciona demos: seletor do Windows (na janela do app) ou envio pelo navegador (plano B)
export function useAddDemo(onDone) {
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState(null)
  const show = (t) => { setToast(t); setTimeout(() => setToast(null), 6000) }
  const report = (res) => {
    if (!res.results.length) return
    const ok = res.results.filter((r) => r.ok)
    const bad = res.results.filter((r) => !r.ok)
    show({ ok: !bad.length, text: [...ok.map((r) => `${r.file}: ${r.msg}`), ...bad.map((r) => `${r.file}: ${r.msg}`)].join('\n') })
    onDone?.()
  }
  const upload = (matchId) => new Promise((resolve) => {
    const inp = document.createElement('input')
    inp.type = 'file'; inp.accept = '.dem,.gz,.zst,.bz2'
    inp.onchange = async () => {
      const f = inp.files[0]
      if (!f) return resolve()
      setBusy(true)
      try {
        report(await api('/demos/upload', { method: 'POST', body: f, headers: { 'X-Filename': f.name, ...(matchId ? { 'X-Match-Id': String(matchId) } : {}) } }))
      } catch (e) { show({ ok: false, text: e.message }) }
      setBusy(false); resolve()
    }
    inp.click()
  })
  const add = async (matchId) => {
    setBusy(true)
    try {
      report(await post('/demos/pick', { match_id: matchId || null }))
    } catch (e) {
      if (e.message.includes('indisponível')) { setBusy(false); return upload(matchId) }
      show({ ok: false, text: e.message })
    }
    setBusy(false)
  }
  return { add, busy, toast }
}

function queueText(live, fila) {
  const a = fila?.analise
  if (fila?.pausado) return 'CS aberto — análise pausada até você sair do jogo'
  if (a) return `Analisando demos: ${a.feitas} de ${a.total} prontas${fila.rodando > 1 ? ` · ${fila.rodando} ao mesmo tempo` : ''}`
  return 'Pronto · aguardando a próxima partida'
}

function MatchRow({ m, open, addDemo }) {
  const done = m.analyzed_at != null
  const info = mapInfo(m.map)
  const known = m.my_score != null
  const a = known ? m.my_score : m.score_a
  const b = known ? m.enemy_score : m.score_b
  const rc = known ? resultClass(m.result) : ''
  const waiting = !done && ['aguardando_demo', 'terminada', 'erro'].includes(m.status)
  const stop = (fn) => (e) => { e.stopPropagation(); fn() }
  return (
    <div role="button" tabIndex={0} className={`match-row ${done ? '' : 'pending'}`} onClick={() => done && open(m.id)}>
      <div className="map-art" style={mapBg(m.map)}><span>{info.name}</span></div>
      <div className="mr-info">
        <div className="mr-teams">
          {done ? `${teamLabel(m.team_a, m.mvp_a)} vs ${teamLabel(m.team_b, m.mvp_b)}` : <span className="status-text">{STATUS[m.status] || m.status}</span>}
        </div>
        <div className="mr-meta">
          <span className={`chip ${m.source || 'desconhecido'}`}>{SOURCE[m.source] || 'Partida'}</span>
          <span title={m.played_at ? 'Quando a partida foi jogada' : 'A data real aparece com a chave da FACEIT (Configurações → Avançado)'}>{playedWhen(m)}</span>
          {done && <span>· {m.rounds_total} rounds</span>}
        </div>
        {waiting && (
          <div className="row-actions">
            {m.faceit_match_id && <button className="link-btn" onClick={stop(() => post(`/open-faceit/${m.faceit_match_id}`))}>Abrir sala FACEIT ↗</button>}
            <button className="link-btn" onClick={stop(() => addDemo(m.id))}>+ Adicionar demo</button>
          </div>
        )}
      </div>
      <div className="score">
        {a != null ? (<><span className={rc}>{a}</span><span className="sep">:</span><span>{b}</span></>) : <span className="sep">–</span>}
      </div>
      <div className="rating-box">
        <div className="v" style={{ color: ratingColor(m.my_rating) }}>{m.my_rating != null ? m.my_rating.toFixed(2) : '—'}</div>
        <div className="l">Nota</div>
      </div>
    </div>
  )
}

// números do card: [chave, rótulo, conta sobre uma lista de partidas, formato, maior é melhor, diferença mínima, extra, dica]
const sum = (d, k) => d.reduce((s, x) => s + (x[k] || 0), 0)
const mean = (d, k) => { const v = d.map((x) => x[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null }
const ratio = (a, b) => (b ? a / b : null)
const wins = (d) => d.filter((x) => x.result === 'vitoria').length
const STATS = [
  ['nota', 'Nota média', (d) => mean(d, 'rating'), (v) => v.toFixed(2), true, 0.03],
  ['adr', 'ADR médio', (d) => mean(d, 'adr'), (v) => v.toFixed(0), true, 3],
  ['kast', 'KAST médio', (d) => mean(d, 'kast'), (v) => `${v.toFixed(0)}%`, true, 2],
  ['vit', 'Vitórias', (d) => 100 * wins(d) / d.length, (v, d) => `${wins(d)}/${d.length}`, true, 5, (v) => `${v.toFixed(0)}%`],
  ['kd', 'K/D', (d) => ratio(sum(d, 'kills'), sum(d, 'deaths')), (v) => v.toFixed(2), true, 0.05],
  ['hs', 'HS dos abates', (d) => ratio(d.reduce((s, x) => s + (x.hs_pct || 0) * (x.kills || 0), 0), sum(d, 'kills')), (v) => `${v.toFixed(0)}%`, true, 3],
  ['abertura', 'Duelos de abertura', (d) => { const n = sum(d, 'first_kills') + sum(d, 'first_deaths'); return n ? 100 * sum(d, 'first_kills') / n : null },
    (v) => `${v.toFixed(0)}%`, true, 4, null, 'Primeiro duelo do round: quantos você ganhou'],
  ['trocadas', 'Mortes trocadas', (d) => { const n = sum(d, 'deaths'); return n ? 100 * sum(d, 'traded_deaths') / n : null },
    (v) => `${v.toFixed(0)}%`, true, 3, null, 'Quando você morre, um aliado mata quem te matou em até 5 s'],
  ['util', 'Dano de granada', (d) => ratio(sum(d, 'util_damage'), sum(d, 'rounds')), (v) => v.toFixed(1), true, 0.8, () => '/round'],
  ['clutch', 'Clutches ganhos', (d) => { const n = sum(d, 'clutches'); return n ? 100 * sum(d, 'clutches_won') / n : null },
    (v, d) => `${sum(d, 'clutches_won')}/${sum(d, 'clutches')}`, true, 5, (v) => `${v.toFixed(0)}%`],
  ['bala', '1ª bala', (d) => mean(d, 'primeira_bala'), (v) => `${v.toFixed(0)}%`, true, 2, null, 'Quanto o 1º tiro de cada rajada acerta (sem sniper)'],
  ['parou', 'Parou antes de atirar', (d) => mean(d, 'parou'), (v) => `${v.toFixed(0)}%`, true, 4, null,
    'Counter-strafe: das vezes em que precisou frear, quantas você atirou já parado'],
]
const CHART = [['rating', 'Nota', 1], ['adr', 'ADR', null], ['hs_pct', 'HS', null], ['primeira_bala', '1ª bala', null], ['parou', 'Parou', null]]

function Evolution({ data }) {
  const [metric, setMetric] = useState('rating')
  if (data.length < 2) {
    return (
      <div className="card">
        <h2>Sua evolução</h2>
        <div className="status-text">O gráfico aparece a partir da segunda partida analisada.</div>
        {data.length === 1 && <Tiles d={data} />}
      </div>
    )
  }
  const chart = CHART.find((c) => c[0] === metric)
  const pts = data.map((d, i) => ({ i: i + 1, v: d[metric], map: mapInfo(d.map).name, res: d.result }))
  const avgLine = chart[2] ?? mean(data, metric)
  const fmtV = (v) => (v == null ? '—' : metric === 'rating' ? v.toFixed(2) : metric === 'adr' ? v.toFixed(0) : `${v.toFixed(0)}%`)
  const resTxt = (r) => (r === 'vitoria' ? ' · vitória' : r === 'derrota' ? ' · derrota' : '')
  return (
    <div className="card">
      <div className="evo-head">
        <h2>Sua evolução</h2>
        <div className="chips sm">
          {CHART.map(([k, l]) => <button key={k} className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}>{l}</button>)}
        </div>
      </div>
      <div style={{ height: 180, marginLeft: -18 }}>
        <ResponsiveContainer>
          <AreaChart data={pts}>
            <defs>
              <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f4b23e" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#f4b23e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#242a35" vertical={false} />
            <XAxis dataKey="i" tick={{ fill: '#8a93a4', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis domain={['auto', 'auto']} tick={{ fill: '#8a93a4', fontSize: 11 }} axisLine={false} tickLine={false} />
            {avgLine != null && <ReferenceLine y={avgLine} stroke="#3a4352" strokeDasharray="4 4" />}
            <Tooltip contentStyle={{ background: '#1e232d', border: '1px solid #242a35', borderRadius: 10 }}
              labelFormatter={(i) => `Partida ${i} · ${pts[i - 1]?.map || ''}${resTxt(pts[i - 1]?.res)}`}
              formatter={(v) => [fmtV(v), chart[1]]} />
            <Area type="monotone" dataKey="v" stroke="#f4b23e" strokeWidth={2.5} fill="url(#g)" dot={{ r: 3, fill: '#f4b23e' }} connectNulls />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <Tiles d={data} />
    </div>
  )
}

function Tiles({ d }) {
  const recent = d.slice(-10)
  const before = d.slice(0, -10)
  const cmp = before.length >= 5
  return (
    <>
      <div className="stat-tiles">
        {STATS.map(([k, label, calc, fmt, up, min, extra, tip]) => {
          const v = calc(d)
          if (v == null) return null
          const r = cmp ? calc(recent) : null
          const b = cmp ? calc(before) : null
          const diff = r != null && b != null ? r - b : null
          const cls = diff == null || Math.abs(diff) < min ? '' : (diff > 0) === up ? 'up' : 'down'
          return (
            <div key={k} className="tile" title={tip || undefined}>
              <div className="v">{fmt(v, d)}{extra && <small> {extra(v)}</small>}</div>
              <div className="l">{label}</div>
              {r != null && <div className={`trend ${cls}`}>{cls === 'up' ? '▲' : cls === 'down' ? '▼' : '•'} últimas 10: {fmt(r, recent)}</div>}
            </div>
          )
        })}
      </div>
      {cmp && <p className="hint-line">▲ ▼ = últimas 10 partidas comparadas com as {before.length} anteriores. Passe o mouse num número para ver o que ele mede.</p>}
    </>
  )
}

function GetStarted({ cfg, fs, add, fila }) {
  const nick = cfg.faceit.ok, entrou = !!fs.st?.entrou, rodando = !!fs.st?.rodando
  const st = fs.st || {}
  const step3 = rodando
    ? (st.total ? `Baixando a partida ${Math.min(st.feitas + 1, st.total)} de ${st.total} (uma por vez, com pausa).` : 'Abrindo seu histórico na FACEIT…')
      + ' Cada partida aparece aqui assim que chega; a análise leva uns 30 s por partida.'
    : fila?.analise ? `Analisando: ${fila.analise.feitas} de ${fila.analise.total} prontas. As partidas aparecem aqui em seguida.`
    : st.erro || 'O app abre seu histórico e baixa as demos dos últimos 30 dias, uma por vez.'
  const Step = ({ n, done, title, text, children }) => (
    <li className={`gs-step ${done ? 'done' : ''}`}>
      <span className="gs-n">{done ? '✓' : n}</span>
      <div className="gs-body"><b>{title}</b><p>{text}</p></div>
      {!done && <div className="gs-act">{children}</div>}
    </li>
  )
  return (
    <div className="card getstarted">
      <h2>Comece por aqui</h2>
      <ol>
        <Step n={1} done={nick} title="Seu nick da FACEIT" text="Para o app achar as suas partidas.">
          <button className="btn-primary" onClick={() => { location.hash = '#/config' }}>Configurar</button>
        </Step>
        <Step n={2} done={entrou} title="Entrar na FACEIT dentro do app"
          text="Faça login na janela que abrir e feche-a; o download começa sozinho. Se aparecer &quot;verificando se você é humano&quot;, é normal: espere uns segundos ou marque a caixa. É uma vez só; o login fica salvo.">
          <button className={nick ? 'btn-primary' : 'btn-ghost'} disabled={!nick || fs.st?.indisponivel} onClick={fs.login}>Entrar na FACEIT</button>
        </Step>
        <Step n={3} done={false} title="Baixar suas partidas" text={step3}>
          {rodando ? <span className="spinner sm" /> : <button className={entrou ? 'btn-primary' : 'btn-ghost'} disabled={!entrou} onClick={fs.sync}>Baixar da FACEIT</button>}
        </Step>
      </ol>
      <p className="gs-alt"><b>Joga Premier ou Competitivo?</b> No CS2: Assistir → Suas partidas → baixar a demo. Ela aparece aqui sozinha.
        Tem um arquivo .dem? <button className="link-btn" onClick={() => add()}>+ Adicionar demo</button></p>
    </div>
  )
}

export default function Home({ open, live, fila, go }) {
  const [matches, setMatches] = useState(null)
  const [tab, setTab] = useTab('inicio', 'partidas')
  const [evo, setEvo] = useState([])
  const [cfg, setCfg] = useState(null)
  useEffect(() => { api('/settings').then(setCfg).catch(() => {}) }, [])
  const load = () => {
    api('/matches').then(setMatches).catch(() => {})
    api('/evolution').then(setEvo).catch(() => {})
  }
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])
  const { add, busy, toast } = useAddDemo(load)
  const fs = useFaceitSync()
  const fsText = (fs.st?.alvo ? null : syncText(fs.st)) || fs.err

  return (
    <div className="page">
      <div className="topbar">
        <div>
          <h1>Suas partidas</h1>
          <div className="sub">Análise automática depois de cada partida de Premier, Competitivo e FACEIT</div>
        </div>
        <div className="topbar-right">
          <div className="pill">
            <span className={`dot ${live ? 'live' : fila?.analise ? 'work' : 'ok'}`} />
            {queueText(live, fila)}
          </div>
          {cfg?.faceit.ok && <FaceitSyncButton f={fs} />}
          <button className="btn-primary" disabled={busy} onClick={() => add()}>{busy ? 'Importando…' : '+ Adicionar demo'}</button>
        </div>
      </div>
      {toast && <div className={`toast ${toast.ok ? 'good' : 'bad'}`}>{toast.text}</div>}
      {fsText && <div className={`toast ${fs.st?.erro || fs.err ? 'bad' : 'good'}`}>
        {fsText}
        {(fs.st?.erro || '').includes('logado') && <> <button className="link-btn" onClick={fs.login}>Entrar na FACEIT</button></>}
      </div>}
      {matches?.length === 0 && cfg && <GetStarted cfg={cfg} fs={fs} add={add} fila={fila} />}
      {matches?.length > 0 && cfg?.faceit.ok && fs.st?.expirou && !fs.st?.rodando && (
        <div className="setup-banner warn">
          <div>
            <b>Seu login na FACEIT expirou</b>
            <p>As suas partidas novas da FACEIT não estão sendo baixadas. Entre de novo; o download recomeça sozinho quando você fechar a janela.</p>
          </div>
          <button className="btn-primary" onClick={fs.login}>Entrar na FACEIT</button>
        </div>
      )}
      {matches?.length > 0 && cfg && !cfg.faceit.ok && (
        <div className="setup-banner">
          <div>
            <b>Conecte suas contas</b>
            <p>Nick da FACEIT ainda não configurado. Leva poucos minutos, com passo a passo.</p>
          </div>
          <button className="btn-primary" onClick={() => { location.hash = '#/config' }}>Configurar</button>
        </div>
      )}
      {matches?.length > 0 && <Tabs value={tab} set={setTab} opts={[['partidas', 'Partidas'], ['jogadas', 'Melhores jogadas']]} />}
      {tab === 'jogadas' && matches?.length > 0 ? <BestPlays go={go} /> : (
      <div className="home-grid">
        <div className="matches">
          {matches === null && <div className="loading"><div><div className="spinner" />Carregando…</div></div>}
          {matches?.map((m) => <MatchRow key={m.id} m={m} open={open} addDemo={add} />)}
        </div>
        {matches?.length > 0 && <Evolution data={evo} />}
      </div>
      )}
    </div>
  )
}
