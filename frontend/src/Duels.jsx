import { useEffect, useState } from 'react'
import { api } from './lib.jsx'

// Como cada morte aconteceu, medido na demo (mesma regra de coach/duels.py)
export const TIPOS = {
  entrou: ['Entrou no ângulo dele', 'Você se mexendo e ele parado, com a mira pronta.'],
  correndo: ['Correndo no duelo', 'Você estava correndo quando ele te acertou.'],
  peek: ['Peek dele', 'Ele veio para cima de você parado.'],
  mira: ['Duelo de mira', 'Os dois parados e de frente.'],
  movimento: ['Os dois se mexendo', 'Encontro com os dois andando.'],
  lado: ['Pego de lado', 'Ele apareceu fora de onde você mirava.'],
  costas: ['Pego de costas', 'Ele te acertou por trás.'],
}
export const ORDEM = Object.keys(TIPOS)
const COR = { entrou: 'bad', correndo: 'bad', lado: 'warn', costas: 'warn', peek: 'neu', mira: 'neu', movimento: 'neu' }

export function duelType(vs, as, ang) {
  if (vs == null || as == null || ang == null) return null
  if (ang > 100) return 'costas'
  if (ang > 45) return 'lado'
  if (vs < 60) return as < 70 ? 'mira' : 'peek'
  if (as < 70) return 'entrou'
  return vs >= 100 ? 'correndo' : 'movimento'
}

export function TypeChip({ t }) {
  if (!t) return null
  return <span className={`duel-chip ${COR[t]}`} title={TIPOS[t][1]}>{TIPOS[t][0]}</span>
}

// "sua velocidade 165 · ele 13 · mira a 2°" em palavras simples
export function duelFacts(vs, as, ang) {
  if (vs == null) return []
  return [
    `Você: ${vs >= 100 ? 'correndo' : vs >= 60 ? 'andando' : 'parado'} (${vs} u/s)`,
    as != null && `Ele: ${as >= 70 ? 'veio no peek' : 'segurava o ângulo'} (${as} u/s)`,
    ang != null && `Sua mira estava a ${ang}° dele`,
  ].filter(Boolean)
}

// barras você x lobby (x pros) por tipo de morte
export function TypeBars({ voce, lobby, labels = ['Você', 'Lobby'] }) {
  const sets = [voce, lobby].map((s, i) => s && s.n ? [labels[i], s] : null).filter(Boolean)
  return (
    <div className="duel-bars">
      <div className="duel-legend">{sets.map(([l], i) => <span key={l}><i className={`s${i}`} />{l}</span>)}</div>
      {ORDEM.map((k) => (
        <div key={k} className="duel-row" title={TIPOS[k][1]}>
          <span className="t">{TIPOS[k][0]}</span>
          <div className="bars">
            {sets.map(([l, s], i) => (
              <div key={l} className="b"><i className={`s${i}`} style={{ width: `${s[k]}%` }} /><b>{s[k]}%</b></div>
            ))}
          </div>
        </div>
      ))}
      <p className="hint-line">Medido no 1º tiro que você levou de quem te matou: sua velocidade, a dele no 0,5 s antes e para onde você mirava.
        Lobby = os outros 9 jogadores das mesmas partidas. Sem IA.</p>
    </div>
  )
}

export function MatchDeaths({ mid, go }) {
  const [d, setD] = useState(null)
  useEffect(() => { api(`/matches/${mid}/mortes`).then(setD).catch(() => setD({ mortes: [] })) }, [mid])
  if (!d) return <div className="loading"><div><div className="spinner" />Carregando…</div></div>
  if (d.sem_jogador) return <div className="card empty">Escolha qual jogador é você no Placar.</div>
  if (!d.mortes.length) return <div className="card empty">Você não morreu nesta partida.</div>
  if (!d.resumo.n) return <div className="card empty">Esta partida foi analisada por uma versão antiga. Ela é reanalisada sozinha ao abrir o app.</div>
  const top = ORDEM.filter((k) => d.resumo[k] > 0).sort((a, b) => d.resumo[b] - d.resumo[a])[0]
  return (
    <>
      <div className="card">
        <h2>Como você morreu <span className="hint">{d.mortes.length} mortes</span></h2>
        <div className="duel-top">
          <p>Mais comum: <TypeChip t={top} /> em {d.resumo[top]}% das mortes (lobby: {d.lobby[top]}%).</p>
          {d.matadores.length > 0 && (
            <p>Quem mais te matou: {d.matadores.map((x, i) => (
              <span key={x.nome}>{i > 0 && ' · '}<b>{x.nome}</b> {x.n}x{x.de_onde.length ? ` (de ${x.de_onde.join(', ')})` : ''}</span>
            ))}</p>
          )}
        </div>
        <TypeBars voce={d.resumo} lobby={d.lobby} />
      </div>
      <div className="card">
        <h2>Morte a morte <span className="hint">clique para ver no replay</span></h2>
        <div className="duel-list">
          {d.mortes.map((x) => (
            <button key={x.n} className="duel-item" onClick={() => go(`#/partida/${mid}/round/${x.round}/t/${x.tick - 64 * 4}`)}>
              <span className="r">R{x.round}</span>
              <span className={`side-badge ${x.lado}`}>{x.lado === 'CT' ? 'CT' : 'TR'}</span>
              <span className="who"><b>{x.matador}</b> · {x.arma}{x.hs ? ' · HS' : ''}
                <em>{x.onde || '?'}{x.de_onde && x.de_onde !== x.onde ? ` ← ${x.de_onde}` : ''}{x.dist != null ? ` · ${x.dist} m` : ''}</em>
              </span>
              <TypeChip t={x.tipo} />
              <span className="nums">
                {x.sua_vel != null && <>você {x.sua_vel} · ele {x.vel_dele} · {x.angulo}°</>}
              </span>
              <span className="ctx">
                {x.trocada ? 'trocada' : x.aliado != null ? `aliado a ${x.aliado} m` : 'sem aliado vivo'}
                {' · '}{x.vivos[0] + 1}v{x.vivos[1]}
              </span>
            </button>
          ))}
        </div>
        <p className="hint-line">Velocidade em unidades/s: correndo de AK ≈ 215; o tiro só sai preciso abaixo de ~70.</p>
      </div>
    </>
  )
}
