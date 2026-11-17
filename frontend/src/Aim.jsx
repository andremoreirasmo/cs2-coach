import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Tabs, api, mapInfo, useTab, when } from './lib.jsx'

const FONTES = [['todas', 'Todas'], ['faceit', 'FACEIT'], ['valve', 'Premier / Comp.']]
const ULTIMAS = [[10, 'Últimas 10'], [20, 'Últimas 20'], [0, 'Todas']]
const BASES = [['lobby', 'vs Lobby'], ['geral', 'vs Geral']]
// validadas no fundo escuro (dataviz): você = âmbar, lobby = azul tracejado
const YOU = '#c08224'
const LOBBY = '#4a90da'
const GRID = '#242a35'
const AXIS = { fill: '#8a93a4', fontSize: 11 }
const TIP = { background: '#1e232d', border: '1px solid #242a35', borderRadius: 10 }

export function Chips({ value, set, opts }) {
  return (
    <div className="chips">
      {opts.map(([v, l]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => set(v)}>{l}</button>)}
    </div>
  )
}

const pct = (v) => (v == null ? '—' : `${Math.round(v)}%`)

// [chave, rótulo, formato, maior é melhor?, explicação]
const TILES = [
  ['precisao', 'Precisão', pct, true, 'Tiros que acertaram alguém'],
  ['primeiro', '1ª bala', pct, true, 'Acerto do primeiro tiro de cada rajada'],
  ['hs', 'HS dos acertos', pct, true, 'Dos tiros que acertaram, quantos na cabeça'],
  ['andando', 'Tiros andando', pct, false, 'Tiros de rifle, sniper e Deagle com você em movimento (acima de 34% da velocidade da arma). SMG, pistola e escopeta ficam fora: com elas atirar andando é normal'],
  ['spray_meio', 'Spray 4ª-7ª bala', pct, true, 'Acerto da 4ª à 7ª bala da rajada (armas automáticas)'],
  ['ajuste', 'Ajuste antes do tiro', (v) => (v == null ? '—' : `${v.toFixed(1)}°`), false, 'Quanto a mira se mexeu nos 0,3 s antes do primeiro tiro que acertou. Menor = mira já estava no lugar'],
]

export function Tiles({ v, l, who = 'lobby' }) {
  return (
    <div className="aim-tiles">
      {TILES.map(([k, label, f, up, help]) => {
        const a = v[k], b = l[k]
        const better = a != null && b != null && Math.abs(a - b) >= (k === 'ajuste' ? 0.3 : 2) ? (up ? a > b : a < b) : null
        return (
          <div key={k} className="tile aim-tile" title={help}>
            <div className="v" style={{ color: better == null ? undefined : better ? 'var(--win)' : 'var(--loss)' }}>{f(a)}</div>
            <div className="l">{label}</div>
            <div className="lob">{who} {f(b)}</div>
          </div>
        )
      })}
    </div>
  )
}

export function Verdicts({ list, label = 'lobby' }) {
  const good = list.filter((x) => x.tipo === 'bom')
  const bad = list.filter((x) => x.tipo === 'melhorar')
  const Col = ({ items, kind, title, empty }) => (
    <div className={`card verdict ${kind}`}>
      <h2><span className="vd-ico">{kind === 'bom' ? '✓' : '!'}</span>{title}</h2>
      {!items.length && <p className="hint-line">{empty}</p>}
      {items.map((x) => (
        <div key={x.titulo} className="vd">
          <b>{x.titulo}</b>
          <p>{x.texto}</p>
          {x.treino && <p className="vd-train"><span>Como treinar:</span> {x.treino}</p>}
        </div>
      ))}
    </div>
  )
  return (
    <div className="ov-two">
      <Col items={bad} kind="melhorar" title="O que melhorar" empty="Nada fora da média do lobby. Boa!" />
      <Col items={good} kind="bom" title="O que está bom" empty="Nenhum ponto claramente acima da média ainda." />
    </div>
  )
}

function Spray({ curvas }) {
  const [i, setI] = useState(0)
  if (!curvas.length) return null
  const c = curvas[Math.min(i, curvas.length - 1)]
  const data = c.voce.map((p, k) => ({ bala: String(p.bala), voce: p.n >= 8 ? p.precisao : null, lobby: c.lobby[k].n >= 8 ? c.lobby[k].precisao : null, n: p.n }))
  return (
    <div className="card">
      <div className="strip-head">
        <h2>Spray: acerto por bala <span className="hint">da 1ª bala da rajada até a 12ª ou mais</span></h2>
        {curvas.length > 1 && <Chips value={i} set={setI} opts={curvas.map((x, k) => [k, x.nome])} />}
      </div>
      <div style={{ height: 240, marginLeft: -18 }}>
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="bala" tick={AXIS} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} unit="%" domain={[0, 'auto']} />
            <Tooltip contentStyle={TIP} labelFormatter={(b) => `${b}ª bala`}
              formatter={(v, name) => [v == null ? '—' : `${v.toFixed(0)}%`, name]} />
            <Legend wrapperStyle={{ fontSize: 12, color: '#8a93a4' }} />
            <Line type="monotone" dataKey="voce" name="Você" stroke={YOU} strokeWidth={2} dot={{ r: 4, fill: YOU, strokeWidth: 0 }} connectNulls />
            <Line type="monotone" dataKey="lobby" name="Lobby" stroke={LOBBY} strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="hint-line">Com spray bom a linha cai devagar. Se a sua cai bem antes da do lobby, o controle do recoil está escapando.</p>
    </div>
  )
}

function Weapons({ armas, bare }) {
  if (!armas.length) return null
  const cell = (a, b, up = true) => {
    const better = a != null && b != null && Math.abs(a - b) >= 2 ? (up ? a > b : a < b) : null
    return <td style={{ color: better == null ? undefined : better ? 'var(--win)' : 'var(--loss)' }} title={`lobby ${pct(b)}`}>{pct(a)}</td>
  }
  const table = (
      <table className="tbl">
        <thead><tr><th>Arma</th><th>Tiros</th><th>Abates</th><th>Precisão</th><th>1ª bala</th><th>HS</th><th>Andando</th><th>Spray 4ª-7ª</th></tr></thead>
        <tbody>
          {armas.map((a) => (
            <tr key={a.arma}>
              <td><b>{a.nome}</b></td><td className="dim">{a.tiros}</td><td className="dim">{a.abates}</td>
              {cell(a.precisao, a.lobby.precisao)}{cell(a.primeiro, a.lobby.primeiro)}{cell(a.hs, a.lobby.hs)}
              {cell(a.andando, a.lobby.andando, false)}{a.spray_meio == null ? <td className="dim">—</td> : cell(a.spray_meio, a.lobby.spray_meio)}
            </tr>
          ))}
        </tbody>
      </table>
  )
  if (bare) return table
  return (
    <div className="card">
      <h2>Por arma <span className="hint">verde = acima do lobby, vermelho = abaixo (passe o mouse para ver o lobby)</span></h2>
      {table}
    </div>
  )
}

// counter-strafe no 1º tiro de cada rajada: o que aconteceu com as teclas e a velocidade
const CS = [
  ['ok_cs', 'Parou com a tecla contrária', 'O certo: soltou, tocou a tecla do lado oposto e atirou já parado.', 'good'],
  ['ok_solto', 'Só soltou a tecla', 'Parou sem a tecla contrária. Funciona, mas demora mais.', 'good'],
  ['cedo', 'Atirou antes de parar', 'Apertou a tecla contrária, mas atirou ainda em movimento.', 'bad'],
  ['demais', 'Segurou a tecla contrária demais', 'Quando atirou, já andava para o outro lado.', 'bad'],
  ['andando', 'Não freou', 'Atirou com a tecla de movimento apertada.', 'bad'],
]
export function Strafe({ s, compact, labels = ['Você', 'Lobby'], title = 'Counter-strafe' }) {
  if (!s?.voce || !s.lobby) return null
  const v = s.voce, l = s.lobby
  return (
    <div className={compact ? 'cs-box' : 'card cs-box'}>
      <h2>{title} <span className="hint">1º tiro de rifle, sniper e Deagle · {v.freou} vezes em que você precisou frear{compact ? '' : ` · ${v.parado}% dos 1ºs tiros você já estava parado`}</span></h2>
      <div className="cs-legend"><span><i style={{ background: YOU }} />{labels[0]}</span><span><i style={{ background: LOBBY }} />{labels[1]}</span></div>
      {CS.map(([k, t, tip, kind]) => (
        <div key={k} className={`cs-row ${kind}`} title={tip}>
          <span className="t">{t}</span>
          <div className="bars">
            <div className="b"><i style={{ width: `${v[k]}%`, background: YOU }} /><b>{pct(v[k])}</b></div>
            <div className="b"><i style={{ width: `${l[k]}%`, background: LOBBY }} /><b>{pct(l[k])}</b></div>
          </div>
        </div>
      ))}
      <div className="cs-times">
        {v.ms_cedo != null && <span>Quando atira cedo, faltam <b>{v.ms_cedo} ms</b> para parar ({labels[1].toLowerCase()} {l.ms_cedo ?? '—'} ms)</span>}
        {v.ms_espera != null && <span>Depois de parar, você espera <b>{v.ms_espera} ms</b> para atirar ({labels[1].toLowerCase()} {l.ms_espera ?? '—'} ms)</span>}
        {v.ms_demais != null && <span>Quando passa do ponto, segura a tecla contrária <b>{v.ms_demais} ms</b></span>}
      </div>
      <p className="hint-line">Medido nas teclas e na posição gravadas na demo, nos 0,4 s antes de cada 1º tiro. "Parado" = abaixo de 34% da velocidade máxima da arma, quando o tiro sai preciso. 1 tick = 16 ms.</p>
    </div>
  )
}

// card compacto para a página da partida: você x os outros 9 jogadores desta partida
export function MatchAim({ mid, go }) {
  const [d, setD] = useState(null)
  useEffect(() => { api(`/mira?partida=${mid}`).then(setD).catch(() => setD({})) }, [mid])
  if (!d?.voce) return null
  const few = d.voce.tiros < 120
  return (
    <div className="card section match-aim">
      <div className="strip-head">
        <h2>Mira nesta partida <span className="hint">você x os outros 9 jogadores · {d.voce.tiros} tiros</span></h2>
        <button className="link-btn" onClick={() => go('#/mira')}>Ver mira em todas as partidas →</button>
      </div>
      <Tiles v={d.voce} l={d.lobby} />
      {few && <p className="hint-line">Poucos tiros nesta partida: os números variam bastante. A página Mira soma todas as partidas.</p>}
      {d.veredito.length > 0 && (
        <div className="vd-compact">
          {d.veredito.map((x) => (
            <div key={x.titulo} className={`vdc ${x.tipo}`}>
              <span className="vd-ico">{x.tipo === 'bom' ? '✓' : '!'}</span>
              <div><b>{x.titulo}</b><p>{x.texto}</p></div>
            </div>
          ))}
        </div>
      )}
      <Strafe s={d.strafe} compact />
      {d.armas.length > 0 && <Weapons armas={d.armas} bare />}
    </div>
  )
}

function Trend({ pts, open }) {
  if (pts.length < 2) return null
  const data = pts.map((p, i) => ({ i: i + 1, ...p }))
  return (
    <div className="card">
      <h2>Partida a partida <span className="hint">clique num ponto para abrir a partida</span></h2>
      <div style={{ height: 220, marginLeft: -18 }}>
        <ResponsiveContainer>
          <LineChart data={data} onClick={(e) => { const p = data[(e?.activeLabel || 0) - 1]; if (p) open(p.match_id) }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="i" tick={AXIS} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} unit="%" domain={[0, 'auto']} />
            <Tooltip contentStyle={TIP}
              labelFormatter={(i) => { const p = data[i - 1]; return p ? `${mapInfo(p.map).name} · ${when(p.quando)} · ${p.tiros} tiros` : '' }}
              formatter={(v, name) => [v == null ? '—' : `${v.toFixed(0)}%`, name]} />
            <Legend wrapperStyle={{ fontSize: 12, color: '#8a93a4' }} />
            <Line type="monotone" dataKey="precisao" name="Precisão" stroke={YOU} strokeWidth={2} dot={{ r: 4, fill: YOU, strokeWidth: 0 }} />
            <Line type="monotone" dataKey="andando" name="Tiros andando" stroke={LOBBY} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 4, fill: LOBBY, strokeWidth: 0 }} />
            <Line type="monotone" dataKey="cedo" name="Atirou antes de parar" stroke="#ff5d62" strokeWidth={2} dot={{ r: 3, fill: '#ff5d62', strokeWidth: 0 }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function Aim({ go }) {
  const [fonte, setFonte] = useState('todas')
  const [ultimas, setUltimas] = useState(20)
  const [d, setD] = useState(null)
  const [tab, setTab] = useTab('mira', 'resumo')
  const [base, setBase] = useState('lobby')
  const geral = base === 'geral' && ultimas > 0
  useEffect(() => {
    setD(null)
    api(`/mira?fonte=${fonte}&ultimas=${ultimas}${geral ? '&geral=1' : ''}`).then(setD).catch(() => setD({ partidas: 0 }))
  }, [fonte, ultimas, geral])
  const pickBase = (b) => { setBase(b); if (b === 'geral') setUltimas(10) }
  const pickUlt = (u) => { setUltimas(u); if (!u) setBase('lobby') }
  // comparação: o lobby das mesmas partidas, ou você mesmo em todas as partidas
  const cmpOn = geral && d?.geral
  const cmp = cmpOn ? d.geral.voce : d?.lobby
  const who = cmpOn ? 'geral' : 'lobby'
  const cs = cmpOn ? (d.strafe?.voce && d.geral.strafe ? { voce: d.strafe.voce, lobby: d.geral.strafe } : null) : d?.strafe

  return (
    <div className="page aim-page">
      <div className="topbar">
        <div>
          <h1>Mira</h1>
          <div className="sub">{geral ? `Suas últimas ${ultimas} partidas comparadas com o seu geral (${d?.geral?.partidas ?? '…'} partidas)` : 'Seus tiros comparados com os outros jogadores das suas partidas (o lobby)'}</div>
        </div>
        <div className="topbar-right">
          <Chips value={fonte} set={setFonte} opts={FONTES} />
          <Chips value={ultimas} set={pickUlt} opts={ULTIMAS} />
          <Chips value={geral ? 'geral' : 'lobby'} set={pickBase} opts={BASES} />
        </div>
      </div>
      {!d ? <div className="loading"><div><div className="spinner" />Calculando…</div></div>
        : !d.voce ? (
          <div className="card empty">
            <b>{d.sem_jogador ? 'Escolha qual jogador é você' : 'Sem tiros ainda'}</b>
            {d.faltam ? `Lendo os tiros de ${d.faltam} partida(s) antigas. Volte em alguns minutos.` : 'A mira aparece aqui quando houver partidas analisadas.'}
          </div>
        ) : (
          <>
            {d.faltam > 0 && <p className="hint-line">Ainda lendo os tiros de {d.faltam} partida(s) antigas; os números vão se completar.</p>}
            <Tiles v={d.voce} l={cmp} who={who} />
            <Tabs value={tab} set={setTab} opts={[['resumo', 'O que melhorar'], ['strafe', 'Counter-strafe'], ['spray', 'Spray'], ['armas', 'Por arma'], ['evolucao', 'Evolução']]} />
            {tab === 'strafe' && (cs ? <Strafe s={cs} labels={cmpOn ? [`Últimas ${ultimas}`, 'Geral'] : undefined} /> : <div className="card empty">Sem a medida ainda. Ela aparece quando as partidas forem reanalisadas.</div>)}
            {(tab === 'resumo' || !['strafe', 'spray', 'armas', 'evolucao'].includes(tab)) && <>
            <Verdicts list={d.veredito} />
            <div className="card aim-move">
              <h2>Parado x andando</h2>
              <div className="mv-bars">
                {[['Parado', d.voce.prec_parado, cmp.prec_parado], ['Andando', d.voce.prec_andando, cmp.prec_andando]].map(([l, a, b]) => (
                  <div key={l} className="mv">
                    <span>{l}</span>
                    <div className="mv-track"><i style={{ width: `${Math.min(100, (a || 0) * 2.5)}%`, background: YOU }} /></div>
                    <b>{pct(a)}</b>
                    <div className="mv-track"><i style={{ width: `${Math.min(100, (b || 0) * 2.5)}%`, background: LOBBY }} /></div>
                    <em>{who} {pct(b)}</em>
                  </div>
                ))}
              </div>
              <p className="hint-line">Precisão dos tiros de rifle, sniper e Deagle parado e andando (SMG, pistola e escopeta ficam fora). {d.voce.andando != null && `${pct(d.voce.andando)} dos seus tiros dessas armas saem andando (${who} ${pct(cmp.andando)}).`} No ar: {d.voce.no_ar ?? 0}%.</p>
            </div>
            </>}
            {tab === 'spray' && (d.curvas.length ? <Spray curvas={d.curvas} /> : <div className="card empty">Poucos tiros de armas automáticas neste filtro.</div>)}
            {tab === 'armas' && <Weapons armas={d.armas} />}
            {tab === 'evolucao' && (d.evolucao.length > 1 ? <Trend pts={d.evolucao} open={(id) => go(`#/partida/${id}`)} />
              : <div className="card empty">A evolução aparece com 2 ou mais partidas neste filtro.</div>)}
            <p className="hint-line">Calculado das demos, sem IA. "Acerto" = a bala causou dano num inimigo. Lobby = os outros 9 jogadores das mesmas partidas.</p>
          </>
        )}
    </div>
  )
}
