import { useEffect, useState } from 'react'
import { SOURCE, api, mapInfo, post, when } from './lib.jsx'

const fmt$ = (n) => `$${Math.round(n || 0).toLocaleString('pt-BR')}`

// ---------- ver o lance no CS2 ----------
// mostra os comandos numa linha de detalhe embaixo do lance clicado (clicar de novo fecha)
export function useOpenCS2(mid) {
  const [msg, setMsg] = useState(null)
  const toggle = async (tick, key, matchId, steamid) => {
    if (msg?.key === key) { setMsg(null); return }
    setMsg({ key, loading: true })
    try { setMsg({ key, ...(await post('/cs2/demo', { match_id: +(matchId || mid), tick, steamid })) }) } catch (e) { setMsg({ key, ok: false, erro: String(e.message || e) }) }
  }
  const isOpen = (key) => msg?.key === key
  const detail = (key) => (msg?.key === key ? <CS2Help msg={msg} /> : null)
  return { toggle, isOpen, detail }
}

export function CopyLine({ text }) {
  const [ok, setOk] = useState(false)
  const copy = () => { navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500) }).catch(() => {}) }
  return (
    <div className="cmd-line"><code>{text}</code><button className="link-btn" onClick={copy}>{ok ? 'Copiado ✓' : 'Copiar'}</button></div>
  )
}

function CS2Help({ msg }) {
  if (msg.loading) return <div className="cs2-detail"><span className="dim-txt">Montando os comandos…</span></div>
  if (!msg.ok) return <div className="cs2-detail"><span className="err">{msg.erro}</span></div>
  return (
    <div className="cs2-detail">
      <span className="cs2-how">No console do CS2 (tecla <kbd>'</kbd>), cole um de cada vez:</span>
      <div className="cs2-steps">
        <span className="n">1</span><CopyLine text={msg.play} />
        <span className="n">2</span><CopyLine text={msg.goto} />
      </div>
      <span className="hint-line">O 1 carrega a demo (já está copiado). Depois que ela carregar, o 2 volta 8 s antes do lance e põe a câmera no jogador.</span>
    </div>
  )
}

// ---------- botão + modal: abrir a demo da partida no CS2 ----------
// Não abre nem mexe no jogo: mostra os comandos para colar no console. rounds: [{round_num, start_tick}]
export function CS2Button({ mid, rounds, round, className = 'btn-ghost' }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button className={className} onClick={() => setOpen(true)}>▶ Abrir no CS2</button>
      {open && <CS2Modal mid={mid} rounds={rounds} round={round} onClose={() => setOpen(false)} />}
    </>
  )
}

function CS2Modal({ mid, rounds, round, onClose }) {
  const [rn, setRn] = useState(round || 0)
  const [msg, setMsg] = useState({ loading: true })
  const tick = rn ? (rounds.find((r) => r.round_num === rn)?.start_tick || 0) : 0
  useEffect(() => {
    setMsg({ loading: true })
    post('/cs2/demo', { match_id: +mid, tick }).then(setMsg).catch((e) => setMsg({ ok: false, erro: String(e.message || e) }))
  }, [mid, tick])
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Abrir a demo no CS2">
        <div className="modal-head">
          <h2>Abrir a demo no CS2</h2>
          <button className="x" onClick={onClose} aria-label="Fechar">×</button>
        </div>
        {msg.loading ? <p className="dim-txt">Montando os comandos…</p>
          : !msg.ok ? <p className="err">{msg.erro}</p> : (
            <>
              <ol className="modal-steps">
                <li>Abra o CS2 e o console (tecla <kbd>'</kbd>). Se o console não abrir, ative em Configurações → Jogo → <i>Ativar console do desenvolvedor</i>.</li>
                <li>Cole o comando que carrega a demo (já está na sua área de transferência):<CopyLine text={msg.play} /></li>
                {rounds?.length > 0 && (
                  <li>
                    <span>Depois que ela carregar, pule para o round</span>{' '}
                    <select value={rn} onChange={(e) => setRn(+e.target.value)}>
                      <option value={0}>início da partida</option>
                      {rounds.map((r) => <option key={r.round_num} value={r.round_num}>round {r.round_num}</option>)}
                    </select>
                    <CopyLine text={msg.goto} />
                  </li>
                )}
              </ol>
              <p className="hint-line">O app não abre nem mexe no jogo: você mesmo cola os comandos. O segundo também põe a câmera em você.
                Durante a demo, <kbd>Shift</kbd>+<kbd>F2</kbd> abre os controles de reprodução.</p>
            </>
          )}
      </div>
    </div>
  )
}

// ---------- destaques ----------
const TIPO = {
  multi: ['Multi-kill', '#c08224'], clutch: ['Clutch', '#8b6cf0'], especial: ['Abate especial', '#4a90da'],
  abertura: ['Abertura', '#3ddc84'], primeira_morte: ['Morreu primeiro', '#ff5d62'],
  bomba: ['Bomba', '#f4b23e'], eco: ['Eco ganho', '#3ddc84'],
}
const FILTROS = [['seus', 'Seus lances'], ['bons', 'Lances bons'], ['erros', 'Seus erros'], ['todos', 'Todos os jogadores']]

export function Highlights({ mid, go }) {
  const [d, setD] = useState(null)
  const [f, setF] = useState('seus')
  const cs2 = useOpenCS2(mid)
  useEffect(() => { api(`/matches/${mid}/destaques`).then(setD).catch(() => setD({ itens: [] })) }, [mid])
  if (!d) return <div className="card empty">Carregando…</div>
  let items = d.itens
  if (f === 'seus') items = items.filter((x) => x.seu)
  if (f === 'todos') items = items.filter((x) => x.bom && (x.seu || ['multi', 'clutch', 'bomba'].includes(x.tipo)))
  if (f === 'bons') items = items.filter((x) => x.seu && x.bom)
  if (f === 'erros') items = items.filter((x) => x.seu && !x.bom)
  const bons = d.itens.filter((x) => x.seu && x.bom).length, ruins = d.itens.filter((x) => x.seu && !x.bom).length
  return (
    <div className="card section">
      <div className="strip-head">
        <h2>Destaques <span className="hint">{bons} lance(s) bons e {ruins} erro(s) seus nesta partida</span></h2>
        <div className="chips">{FILTROS.map(([v, l]) => <button key={v} className={f === v ? 'on' : ''} onClick={() => setF(v)}>{l}</button>)}</div>
      </div>
      {!items.length && <p className="hint-line">Nada neste filtro.</p>}
      <div className="hl-list">
        {items.map((x, i) => {
          const [tl, col] = TIPO[x.tipo] || [x.tipo, '#888']
          return (
            <div key={i} className={`hl ${x.bom ? '' : 'bad'}`}>
              <span className="hl-round">R{x.round}</span>
              <span className="hl-tag" style={{ color: col, borderColor: col }}>{tl}</span>
              <div className="hl-txt">
                <b>{x.titulo}{!x.seu && <span className="hl-who"> · {x.nome}</span>}</b>
                <span>{x.detalhe}</span>
              </div>
              <div className="hl-actions">
                <button className="btn-ghost sm" onClick={() => go(`#/partida/${mid}/round/${x.round}/t/${Math.max(0, x.tick - 64 * 8)}`)}>▶ Replay 2D</button>
                <button className={`btn-primary sm ${cs2.isOpen(`${x.round}-${i}`) ? 'on' : ''}`} onClick={() => cs2.toggle(x.replay_tick, `${x.round}-${i}`, null, x.steamid)} title="Mostra os comandos para ver este lance no console do CS2">{cs2.isOpen(`${x.round}-${i}`) ? 'Fechar' : 'Ver no CS2'}</button>
              </div>
              {cs2.detail(`${x.round}-${i}`)}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------- economia ----------
const BUY_TXT = { pistol: 'Pistol', eco: 'Eco', 'forçado': 'Forçado', completo: 'Completo', '?': '—' }
const BUY_COL = { pistol: '#8a93a4', eco: '#ff5d62', 'forçado': '#f4b23e', completo: '#3ddc84' }

export function Economy({ mid, go }) {
  const [d, setD] = useState(null)
  const cs2 = useOpenCS2(mid)
  useEffect(() => { api(`/matches/${mid}/economia`).then(setD).catch(() => setD({ rounds: [], erros: [] })) }, [mid])
  if (!d) return <div className="card empty">Carregando…</div>
  if (!d.rounds.length) return <div className="card empty">{d.sem_jogador ? 'Escolha quem é você na aba Placar.' : 'Sem dados de economia.'}</div>
  const r = d.resumo
  const errs = Object.fromEntries(d.erros.map((e) => [`${e.round}`, e]))
  const maxEq = Math.max(...d.rounds.map((x) => x.equip + x.sobrou), 1)
  return (
    <>
      <div className="card section">
        <h2>Economia <span className="hint">suas compras e as do time em cada round</span></h2>
        <div className="eco-tiles">
          <div className="tile"><div className="v" style={{ color: r.erros_seus ? 'var(--loss)' : 'var(--win)' }}>{r.erros_seus}</div><div className="l">Erros seus</div></div>
          <div className="tile"><div className="v">{r.erros_time}</div><div className="l">Forças do time que quebraram</div></div>
          <div className="tile"><div className="v">{fmt$(r.desperdicado)}</div><div className="l">Dinheiro que zerou sem usar</div></div>
          {['eco', 'forçado', 'completo'].map((k) => (
            <div key={k} className="tile"><div className="v">{r.por_compra[k].n ? `${r.por_compra[k].ganhos}/${r.por_compra[k].n}` : '—'}</div><div className="l">Rounds {BUY_TXT[k].toLowerCase()} ganhos</div></div>
          ))}
        </div>
        {d.erros.length ? (
          <div className="hl-list">
            {d.erros.map((e, i) => (
              <div key={i} className="hl bad">
                <span className="hl-round">R{e.round}</span>
                <span className="hl-tag" style={{ color: e.time ? '#f4b23e' : '#ff5d62', borderColor: e.time ? '#f4b23e' : '#ff5d62' }}>{e.time ? 'Time' : 'Você'}</span>
                <div className="hl-txt"><b>{e.titulo}</b><span>{e.texto}</span></div>
                <div className="hl-actions">
                  <button className="btn-ghost sm" onClick={() => go(`#/partida/${mid}/round/${e.round}`)}>▶ Replay 2D</button>
                  <button className={`btn-primary sm ${cs2.isOpen(`e${i}`) ? 'on' : ''}`} onClick={() => cs2.toggle(e.tick, `e${i}`)}>{cs2.isOpen(`e${i}`) ? 'Fechar' : 'Ver no CS2'}</button>
                </div>
                {cs2.detail(`e${i}`)}
              </div>
            ))}
          </div>
        ) : <p className="hint-line">Nenhum erro de economia encontrado nesta partida. Boa!</p>}
      </div>

      <div className="card section">
        <h2>Round a round <span className="hint">barra = seu equipamento · parte clara = dinheiro que sobrou</span></h2>
        <div className="eco-rows">
          {d.rounds.map((x) => {
            const e = errs[`${x.round}`]
            return (
              <div key={x.round} className={`eco-row ${e ? 'bad' : ''}`} title={e ? `${e.titulo}: ${e.texto}` : ''}>
                <span className="er-n">R{x.round}</span>
                <span className={`side-badge ${x.lado}`}>{x.lado === 'CT' ? 'CT' : 'TR'}</span>
                <span className="er-buy" style={{ color: BUY_COL[x.compra] }}>{BUY_TXT[x.compra]}</span>
                <span className="er-vs">vs <i style={{ color: BUY_COL[x.compra_inimigo] }}>{BUY_TXT[x.compra_inimigo]}</i></span>
                <div className="er-bar">
                  <i className="eq" style={{ width: `${(100 * x.equip) / maxEq}%` }} />
                  <i className="mo" style={{ width: `${(100 * x.sobrou) / maxEq}%` }} />
                </div>
                <span className="er-val">{fmt$(x.equip)} <em>+{fmt$(x.sobrou)}</em></span>
                <span className={`er-res ${x.ganhou ? 'w' : 'l'}`}>{x.ganhou ? 'Ganhou' : 'Perdeu'}</span>
                <span className="er-flag">{e ? '!' : ''}</span>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}

// ---------- melhores jogadas de todas as partidas ----------
const BEST_TIPOS = [['top', 'Melhores'], ['multi', 'Multi-kills'], ['clutch', 'Clutches'], ['especial', 'Abates especiais'],
  ['bomba', 'Bomba'], ['abertura', 'Aberturas']]

export function BestPlays({ go }) {
  const [fonte, setFonte] = useState('todas')
  const [tipo, setTipo] = useState('top')
  const [d, setD] = useState(null)
  const [mostrar, setMostrar] = useState(30)
  const cs2 = useOpenCS2(0)
  useEffect(() => { setD(null); api(`/destaques?fonte=${fonte}`).then(setD).catch(() => setD({ itens: [] })) }, [fonte])
  useEffect(() => setMostrar(30), [tipo, fonte])
  if (!d) return <div className="card empty">Carregando…</div>
  if (d.sem_jogador) return <div className="card empty">Escolha quem é você numa partida para ver suas jogadas.</div>
  // "Melhores" deixa de fora as aberturas simples, que são muitas
  const items = d.itens.filter((x) => (tipo === 'top' ? x.tipo !== 'abertura' : x.tipo === tipo))
  return (
    <div className="card section best">
      <div className="strip-head">
        <h2>Suas melhores jogadas <span className="hint">{d.total} lance(s) bons em {d.partidas} partida(s)</span></h2>
        <div className="chips">
          {[['todas', 'Todas'], ['faceit', 'FACEIT'], ['valve', 'Premier / Comp.']].map(([v, l]) => (
            <button key={v} className={fonte === v ? 'on' : ''} onClick={() => setFonte(v)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="chips best-tipos">
        {BEST_TIPOS.map(([v, l]) => {
          const n = v === 'top' ? d.total - (d.tipos?.abertura || 0) : d.tipos?.[v] || 0
          return <button key={v} className={tipo === v ? 'on' : ''} disabled={!n} onClick={() => setTipo(v)}>{l} <i>{n}</i></button>
        })}
      </div>
      {!items.length && <p className="hint-line">Nada neste filtro ainda.</p>}
      <div className="hl-list">
        {items.slice(0, mostrar).map((x, i) => {
          const [tl, col] = TIPO[x.tipo] || [x.tipo, '#888']
          const key = `${x.match_id}-${x.tick}-${i}`
          return (
            <div key={key} className="hl best-row">
              <span className="best-map" style={{ backgroundImage: `linear-gradient(135deg, ${mapInfo(x.mapa).g.join(', ')})` }}>{mapInfo(x.mapa).name}</span>
              <span className="hl-tag" style={{ color: col, borderColor: col }}>{tl}</span>
              <div className="hl-txt">
                <b>{x.titulo}</b>
                <span>{x.detalhe}</span>
                <span className="best-meta">
                  <button className="link-btn" onClick={() => go(`#/partida/${x.match_id}`)}>Round {x.round} · {SOURCE[x.fonte] || 'Partida'} · {x.placar}</button>
                  {x.quando ? <> · {when(x.quando)}</> : null}
                </span>
              </div>
              <div className="hl-actions">
                <button className="btn-ghost sm" onClick={() => go(`#/partida/${x.match_id}/round/${x.round}/t/${Math.max(0, x.tick - 64 * 8)}`)}>▶ Replay 2D</button>
                <button className={`btn-primary sm ${cs2.isOpen(key) ? 'on' : ''}`} onClick={() => cs2.toggle(x.replay_tick, key, x.match_id, x.steamid)}>{cs2.isOpen(key) ? 'Fechar' : 'Ver no CS2'}</button>
              </div>
              {cs2.detail(key)}
            </div>
          )
        })}
      </div>
      {items.length > mostrar && <button className="btn-ghost more" onClick={() => setMostrar(mostrar + 30)}>Mostrar mais ({items.length - mostrar})</button>}
    </div>
  )
}
