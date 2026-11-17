import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Tabs, api, mapInfo, ratingColor, useTab, when } from './lib.jsx'
import { TypeBars } from './Duels.jsx'

const FONTES = [['todas', 'Todas'], ['faceit', 'FACEIT'], ['valve', 'Premier / Comp.']]
const ULTIMAS = [[10, 'Últimas 10'], [20, 'Últimas 20'], [0, 'Todas']]
const SRC_COLOR = { faceit: '#ff7a33', valve: '#5aa9ff' }

// métricas da comparação: [chave, rótulo, sufixo, menor é melhor]
const METRICS = [
  ['winrate', 'Vitórias', '%'], ['nota', 'Nota', ''], ['adr', 'ADR', ''], ['kast', 'KAST', '%'], ['kd', 'K/D', ''],
  ['hs', 'HS', '%'], ['abertura', 'Duelos de abertura vencidos', '%'], ['trocadas', 'Suas mortes trocadas', '%'],
  ['trades', 'Trades por partida', ''], ['util', 'Dano de granada / round', ''], ['cegou', 'Inimigos cegados / partida', ''],
  ['dpr', 'Mortes por round', '', true],
]

function Chips({ value, set, opts }) {
  return (
    <div className="chips">
      {opts.map(([v, l]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => set(v)}>{l}</button>)}
    </div>
  )
}

function Tiles({ t }) {
  const items = [
    ['Partidas', t.partidas], ['Vitórias', `${t.winrate}%`], ['Nota', t.nota.toFixed(2), ratingColor(t.nota)],
    ['ADR', t.adr.toFixed(0)], ['KAST', `${t.kast.toFixed(0)}%`], ['K/D', t.kd.toFixed(2)], ['HS', `${t.hs.toFixed(0)}%`],
    ['Abertura', `${t.abertura}%`], ['Clutches', t.clutch],
  ]
  return (
    <div className="ov-tiles">
      {items.map(([l, v, c]) => <div key={l} className="tile"><div className="v" style={c ? { color: c } : null}>{v}</div><div className="l">{l}</div></div>)}
    </div>
  )
}

function Compare({ fontes }) {
  const f = fontes.faceit?.total, v = fontes.valve?.total
  const sides = (s) => fontes[s]?.lados || {}
  if (!f && !v) return null
  const cell = (row, a, b) => {
    const [k, , suf, low] = row
    if (!a) return <td className="na">—</td>
    const better = b && a[k] !== b[k] && (low ? a[k] < b[k] : a[k] > b[k])
    return <td className={better ? 'best' : ''}>{typeof a[k] === 'number' && !Number.isInteger(a[k]) ? a[k].toFixed(k === 'nota' || k === 'kd' || k === 'dpr' ? 2 : 1) : a[k]}{suf}</td>
  }
  return (
    <div className="card">
      <h2>FACEIT x Premier / Competitivo</h2>
      {(!f || !v) && <p className="hint-line">A comparação completa aparece quando houver partidas analisadas das duas fontes.</p>}
      <table className="tbl cmp">
        <thead><tr><th /><th style={{ color: SRC_COLOR.faceit }}>FACEIT{f && <small>{f.partidas} partidas</small>}</th>
          <th style={{ color: SRC_COLOR.valve }}>Premier / Comp.{v && <small>{v.partidas} partidas</small>}</th></tr></thead>
        <tbody>
          {METRICS.map((row) => <tr key={row[0]}><td className="lbl">{row[1]}</td>{cell(row, f, v)}{cell(row, v, f)}</tr>)}
          {['CT', 'T'].map((s) => (
            <tr key={s}><td className="lbl">Rounds vencidos de {s === 'CT' ? 'CT' : 'TR'}</td>
              {['faceit', 'valve'].map((src) => <td key={src}>{sides(src)[s] ? `${sides(src)[s].winrate}%` : '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Sides({ lados }) {
  const rows = [['winrate', 'Rounds vencidos', '%'], ['adr', 'ADR', ''], ['kast', 'KAST', '%'], ['kpr', 'Abates / round', ''], ['dpr', 'Mortes / round', '']]
  return (
    <div className="card">
      <h2>CT x TR</h2>
      <div className="sides">
        {['CT', 'T'].map((s) => lados[s] && (
          <div key={s} className={`side ${s}`}>
            <div className="side-h">{s === 'CT' ? 'Contra-terroristas' : 'Terroristas'}<small>{lados[s].rounds} rounds</small></div>
            {rows.map(([k, l, suf]) => <div key={k} className="kv"><span>{l}</span><b>{lados[s][k]}{suf}</b></div>)}
          </div>
        ))}
      </div>
    </div>
  )
}

function Maps({ mapas }) {
  return (
    <div className="card">
      <h2>Mapas</h2>
      <table className="tbl">
        <thead><tr><th>Mapa</th><th>Partidas</th><th>Vitórias</th><th>Nota</th><th>ADR</th><th>KAST</th></tr></thead>
        <tbody>
          {mapas.map((m) => (
            <tr key={m.mapa}>
              <td className="lbl">{mapInfo(m.mapa).name}</td><td>{m.partidas}</td><td>{m.winrate}%</td>
              <td style={{ color: ratingColor(m.nota) }}>{m.nota.toFixed(2)}</td><td>{m.adr.toFixed(0)}</td><td>{m.kast.toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Deaths({ d }) {
  if (!d) return null
  const bars = [
    ['Primeira morte do round', d.abertura], ['Não foram trocadas', d.nao_trocadas],
    ['Sem aliado perto para trocar', d.sozinho], ['Sem granada nos 20 s antes', d.sem_granada],
    ['Levou headshot', d.headshot], ['Estava cego', d.cego],
  ]
  const max = d.lugares[0]?.n || 1
  return (
    <div className="card">
      <h2>Suas mortes <span className="hint">{d.total} no total</span></h2>
      <div className="deaths-grid">
        <div>
          {bars.map(([l, v]) => (
            <div key={l} className="pbar"><span>{l}</span><div><i style={{ width: `${v}%` }} /></div><b>{v}%</b></div>
          ))}
        </div>
        <div>
          <h3>Onde você mais morre</h3>
          {d.lugares.map((x) => <div key={x.lugar} className="pbar place"><span>{x.lugar}</span><div><i style={{ width: `${100 * x.n / max}%` }} /></div><b>{x.n}</b></div>)}
          <h3>Armas que mais te mataram</h3>
          <div className="weapons">{d.armas.map((x) => <span key={x.arma}>{x.arma} <b>{x.n}</b></span>)}</div>
        </div>
      </div>
    </div>
  )
}

function Trend({ pts }) {
  if (pts.length < 2) return null
  const data = pts.map((p, i) => ({ i: i + 1, ...p, faceit: p.source === 'faceit' ? p.nota : null, valve: p.source === 'valve' ? p.nota : null }))
  return (
    <div className="card">
      <h2>Nota partida a partida <span className="hint"><i className="dot-src faceit" /> FACEIT <i className="dot-src valve" /> Premier / Comp.</span></h2>
      <div style={{ height: 200, marginLeft: -18 }}>
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid stroke="#242a35" vertical={false} />
            <XAxis dataKey="i" tick={{ fill: '#8a93a4', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis domain={['auto', 'auto']} tick={{ fill: '#8a93a4', fontSize: 11 }} axisLine={false} tickLine={false} />
            <ReferenceLine y={1} stroke="#3a4352" strokeDasharray="4 4" />
            <Tooltip contentStyle={{ background: '#1e232d', border: '1px solid #242a35', borderRadius: 10 }}
              labelFormatter={(i) => { const p = data[i - 1]; return p ? `${mapInfo(p.map).name} · ${when(p.quando)}` : '' }}
              formatter={(v) => (v == null ? null : v.toFixed(2))} />
            <Line type="monotone" dataKey="nota" stroke="#3a4352" strokeWidth={1.5} dot={false} name="Nota" />
            <Line dataKey="faceit" stroke="none" dot={{ r: 4, fill: SRC_COLOR.faceit }} name="FACEIT" isAnimationActive={false} />
            <Line dataKey="valve" stroke="none" dot={{ r: 4, fill: SRC_COLOR.valve }} name="Premier" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Duels({ d }) {
  if (!d) return <div className="card empty">Sem a medida ainda. Ela aparece quando as partidas forem reanalisadas.</div>
  const bad = (x) => x.entrou + x.correndo
  const pts = d.tendencia.map((x, i) => ({ i: i + 1, v: bad(x), map: mapInfo(x.map).name }))
  return (
    <div className="ov-two">
      <div className="card">
        <h2>Como você morre <span className="hint">{d.voce.n} mortes</span></h2>
        <TypeBars voce={d.voce} lobby={d.lobby} />
      </div>
      <div className="card">
        <h2>Você se mexendo no duelo <span className="hint">% das mortes por partida (entrou no ângulo + correndo)</span></h2>
        {pts.length > 1 ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={pts} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="#242a35" vertical={false} />
              <XAxis dataKey="i" tick={{ fill: '#8b93a3', fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fill: '#8b93a3', fontSize: 11 }} unit="%" />
              <ReferenceLine y={bad(d.lobby)} stroke="#8b93a3" strokeDasharray="4 4" label={{ value: `lobby ${bad(d.lobby)}%`, fill: '#8b93a3', fontSize: 11, position: 'insideTopRight' }} />
              <Tooltip contentStyle={{ background: '#151a22', border: '1px solid #2a3140' }} formatter={(v) => [`${v}%`, 'Se mexendo']} labelFormatter={(i) => pts[i - 1]?.map} />
              <Line type="monotone" dataKey="v" stroke="#ff7a33" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : <p className="status-text">Aparece com 2 ou mais partidas.</p>}
        <p className="hint-line">Quanto menor, melhor: menos mortes chegando em movimento num inimigo que já estava parado mirando.</p>
      </div>
    </div>
  )
}

export default function Overview() {
  const [fonte, setFonte] = useState('todas')
  const [ultimas, setUltimas] = useState(0)
  const [st, setSt] = useState(null)
  const [tab, setTab] = useTab('geral', 'duelos')
  useEffect(() => { api(`/overview?fonte=${fonte}&ultimas=${ultimas}`).then(setSt).catch(() => {}) }, [fonte, ultimas])

  return (
    <div className="page">
      <div className="topbar">
        <div>
          <h1>Geral</h1>
          <div className="sub">Todas as suas partidas analisadas juntas{st?.na_fila ? ` · ${st.na_fila} ainda na fila de análise` : ''}</div>
        </div>
        <div className="topbar-right">
          <Chips value={fonte} set={setFonte} opts={FONTES} />
          <Chips value={ultimas} set={setUltimas} opts={ULTIMAS} />
        </div>
      </div>
      {!st && <div className="loading"><div><div className="spinner" />Carregando…</div></div>}
      {st && !st.me && <div className="card empty"><b>Escolha quem é você</b>Abra uma partida e clique no seu nome.</div>}
      {st?.me && !st.total && <div className="card empty"><b>Nada analisado ainda neste filtro</b>As partidas aparecem aqui assim que a análise termina.</div>}
      {st?.total && (
        <div className="ov">
          <Tiles t={st.total} />
          <Tabs value={tab} set={setTab} opts={[['duelos', 'Como você morre'], ['comparar', 'FACEIT x Premier'],
            ['mapas', 'Lados e mapas'], ['mortes', 'Mortes'], ['evolucao', 'Evolução']]} />
          {(tab === 'duelos' || !['comparar', 'mapas', 'mortes', 'evolucao'].includes(tab)) && <Duels d={st.duelos} />}
          {tab === 'comparar' && <Compare fontes={st.fontes} />}
          {tab === 'mapas' && (
            <div className="ov-two">
              <Sides lados={st.lados} />
              <Maps mapas={st.mapas} />
            </div>
          )}
          {tab === 'mortes' && <Deaths d={st.mortes} />}
          {tab === 'evolucao' && (st.tendencia.length > 1 ? <Trend pts={st.tendencia} />
            : <div className="card empty">A evolução aparece com 2 ou mais partidas neste filtro.</div>)}
        </div>
      )}
    </div>
  )
}
