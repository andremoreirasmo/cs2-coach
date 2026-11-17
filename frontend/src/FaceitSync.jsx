import { useEffect, useState } from 'react'
import { api, post } from './lib.jsx'

// Baixar as demos das suas partidas da FACEIT pelo site (janela da FACEIT dentro do app).
export function useFaceitSync() {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState(null)
  const load = () => api('/faceit-site').then(setSt).catch(() => {})
  useEffect(() => {
    load()
    const t = setInterval(load, st?.rodando ? 2000 : 10000)
    return () => clearInterval(t)
  }, [st?.rodando])
  const run = (path) => { setErr(null); post(path).then((s) => s && s.rodando !== undefined && setSt(s)).catch((e) => setErr(e.message)) }
  return {
    st, err,
    login: () => { setErr(null); post('/faceit-site/login').then(() => setTimeout(load, 1500)).catch((e) => setErr(e.message)) },
    sync: () => run('/faceit-site/sync'),
    stop: () => run('/faceit-site/stop'),
    setAuto: (on) => post('/faceit-site/auto', { on }).then(load).catch((e) => setErr(e.message)),
  }
}

export function syncText(st) {
  if (!st) return null
  if (st.rodando) {
    if (st.fase === 'baixando' && st.total) return `FACEIT: ${st.msg || ''} · ${st.baixadas} baixada(s)`
    return `FACEIT: ${st.fase || 'abrindo'}…`
  }
  if (st.erro) return st.erro
  if (st.msg === 'Pronto') {
    if (!st.total) return 'FACEIT: nenhuma partida nova com demo para baixar.'
    return `FACEIT: ${st.baixadas} demo(s) baixada(s)` + (st.sem_demo ? `, ${st.sem_demo} sem demo (expirada)` : '') + '.'
  }
  if (st.msg === 'Interrompido') return `FACEIT: parado. ${st.baixadas} demo(s) baixada(s).`
  return null
}

// Botão da tela inicial.
export function FaceitSyncButton({ f }) {
  if (!f.st || f.st.indisponivel) return null
  return f.st.rodando
    ? <button className="btn-ghost" onClick={f.stop}>Parar FACEIT</button>
    : <button className="btn-ghost" onClick={f.sync} title="Abre seu histórico da FACEIT e baixa as demos que faltam, uma por vez">Baixar da FACEIT</button>
}
