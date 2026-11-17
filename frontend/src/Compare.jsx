import { useEffect, useState } from 'react'
import { Chips, Strafe, Tiles } from './Aim.jsx'
import { syncText, useFaceitSync } from './FaceitSync.jsx'
import { api } from './lib.jsx'

const N = [[10, '10 partidas'], [30, '30 partidas']]
const one = (v) => (v == null ? '—' : v.toFixed(1))
const two = (v) => (v == null ? '—' : v.toFixed(2))
const pc = (v) => (v == null ? '—' : `${Math.round(v)}%`)

// [chave, rótulo, formato, maior é melhor?, explicação]
const ROWS = [
  ['nota', 'Nota', two, true, 'Rating médio por partida'],
  ['adr', 'ADR', one, true, 'Dano por round'],
  ['kast', 'KAST', pc, true, 'Rounds em que matou, deu assistência, sobreviveu ou foi trocado'],
  ['kd', 'K/D', two, true, 'Abates por morte'],
  ['hs', 'HS', pc, true, 'Abates com headshot'],
  ['kpr', 'Abates por round', two, true, ''],
  ['dpr', 'Mortes por round', two, false, ''],
  ['abertura', 'Duelos de abertura ganhos', pc, true, 'Dos primeiros duelos do round em que entrou, quantos ganhou'],
  ['aberturas_tentadas', 'Rounds com duelo de abertura', pc, null, 'Quanto entra no primeiro duelo do round'],
  ['trocadas', 'Mortes trocadas', pc, true, 'Das suas mortes, quantas um colega vingou em seguida'],
  ['util', 'Dano de utilitária por round', one, true, 'HE e molotov'],
  ['winrate', 'Vitórias', pc, true, ''],
]

function Totals({ eu, ele, nick }) {
  return (
    <div className="card cmp-table">
      <div className="cmp-row head"><span /><b>Você</b><b>{nick}</b></div>
      {ROWS.map(([k, label, f, up, help]) => {
        const a = eu?.[k], b = ele?.[k]
        const diff = a != null && b != null && up != null && Math.abs(a - b) > Math.abs(b) * 0.03 ? (up ? a > b : a < b) : null
        return (
          <div key={k} className="cmp-row" title={help}>
            <span>{label}</span>
            <b style={{ color: diff == null ? undefined : diff ? 'var(--win)' : 'var(--loss)' }}>{f(a)}</b>
            <b>{f(b)}</b>
          </div>
        )
      })}
      <div className="cmp-row"><span>Clutches ganhos</span><b>{eu?.clutch ?? '—'}</b><b>{ele?.clutch ?? '—'}</b></div>
    </div>
  )
}

export default function Compare() {
  const f = useFaceitSync()
  const [list, setList] = useState(null)
  const [nick, setNick] = useState('')
  const [n, setN] = useState(10)
  const [sel, setSel] = useState(null)
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)

  const loadList = () => api('/comparar').then((r) => { setList(r); if (!sel && r.jogadores[0]) setSel(r.jogadores[0].nick) }).catch(() => {})
  useEffect(() => { loadList() }, [])
  useEffect(() => {
    if (!sel) { setD(null); return }
    api(`/comparar/${encodeURIComponent(sel)}`).then(setD).catch(() => setD(null))
  }, [sel, f.st?.baixadas, f.st?.rodando])
  useEffect(() => { if (f.st && !f.st.rodando) loadList() }, [f.st?.rodando])

  const start = () => {
    setErr(null)
    fetch('/api/comparar', { method: 'POST', headers: { 'X-Coach': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ nick: nick.trim(), partidas: n }) })
      .then(async (r) => { if (!r.ok) throw new Error((await r.json()).detail || r.status); setSel(nick.trim()) })
      .catch((e) => setErr(e.message))
  }
  const remove = (who) => fetch(`/api/comparar/${encodeURIComponent(who)}`, { method: 'DELETE', headers: { 'X-Coach': '1' } })
    .then(() => { if (sel === who) setSel(null); loadList() })

  const running = f.st?.rodando && f.st?.alvo
  const status = f.st?.alvo ? syncText(f.st) : null
  const ele = d?.ele, eu = d?.eu
  const mv = eu?.mira?.voce, mo = ele?.mira?.voce

  return (
    <div className="page">
      <div className="topbar">
        <div>
          <h1>Comparar com outro jogador</h1>
          <div className="sub">Baixa as últimas partidas dele na FACEIT, tira os números e apaga as demos. Nada disso entra nas suas partidas.</div>
        </div>
      </div>

      <div className="card cmp-form">
        <input className="input" value={nick} onChange={(e) => setNick(e.target.value)} placeholder="Nick na FACEIT" onKeyDown={(e) => e.key === 'Enter' && nick.trim() && !f.st?.rodando && start()} />
        <Chips value={n} set={setN} opts={N} />
        {running
          ? <button className="btn-ghost" onClick={f.stop}>Parar</button>
          : <button className="btn-primary" disabled={!nick.trim() || f.st?.rodando || list?.disponivel === false} onClick={start}>Comparar</button>}
        <p className="hint-line">Uma partida por vez, com pausa entre elas (10 partidas ≈ 8 min). Só partidas dos últimos 30 dias têm demo.</p>
      </div>
      {(err || status) && <div className={`toast ${err || f.st?.erro ? 'bad' : 'good'}`}>
        {err || (f.st?.alvo ? `${f.st.alvo}: ` : '') + status}
        {(f.st?.erro || '').includes('logado') && <> <button className="link-btn" onClick={f.login}>Entrar na FACEIT</button></>}
      </div>}

      {list?.jogadores?.length > 0 && (
        <div className="chips cmp-players">
          {list.jogadores.map((j) => (
            <span key={j.nick} className={`cmp-chip ${sel === j.nick ? 'on' : ''}`}>
              <button onClick={() => setSel(j.nick)}>{j.nick} <i>{j.partidas}</i></button>
              <button className="x" title="Apagar os números deste jogador" onClick={() => remove(j.nick)}>×</button>
            </span>
          ))}
        </div>
      )}

      {ele && (
        <>
          <h2 className="cmp-h">Você (últimas {d.partidas} na FACEIT) × {ele.nick} ({ele.total?.partidas ?? 0} partidas)</h2>
          <Totals eu={eu?.total} ele={ele.total} nick={ele.nick} />
          {mv && mo && <>
            <h2 className="cmp-h">Mira</h2>
            <Tiles v={mv} l={mo} who={ele.nick} />
          </>}
          {eu?.mira?.strafe && ele.mira?.strafe && (
            <Strafe s={{ voce: eu.mira.strafe, lobby: ele.mira.strafe }} labels={['Você', ele.nick]} title="Counter-strafe" />
          )}
        </>
      )}
      {list && !list.jogadores.length && !running && (
        <div className="card empty"><b>Ninguém comparado ainda</b>Digite o nick de um jogador da FACEIT e clique em Comparar.</div>
      )}
    </div>
  )
}
