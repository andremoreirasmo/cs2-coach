import '@fontsource-variable/inter'
import '@fontsource/barlow-condensed/600.css'
import '@fontsource/barlow-condensed/700.css'
import './styles.css'
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Home from './Home.jsx'
import Aim from './Aim.jsx'
import Compare from './Compare.jsx'
import Maps from './Maps.jsx'
import Match from './Match.jsx'
import Overview from './Overview.jsx'
import Round from './Round.jsx'
import Settings from './Settings.jsx'
import { Avatar, Icon, api } from './lib.jsx'

function useHash() {
  const [h, setH] = useState(location.hash)
  useEffect(() => {
    const f = () => setH(location.hash)
    addEventListener('hashchange', f)
    return () => removeEventListener('hashchange', f)
  }, [])
  return h
}

function App() {
  const hash = useHash()
  const [live, setLive] = useState(false)
  const [fila, setFila] = useState(null)
  const [me, setMe] = useState(null)
  useEffect(() => { api('/me').then(setMe).catch(() => {}) }, [hash.startsWith('#/partida')])
  useEffect(() => {
    let build = null
    const f = () => api('/status').then((s) => {
      setLive(s.em_partida); setFila(s.fila)
      // interface nova compilada: recarrega a janela (mantém a página atual pelo #)
      if (s.build) { if (build && s.build !== build) location.reload(); build = s.build }
    }).catch(() => {})
    f()
    const t = setInterval(f, 4000)
    return () => clearInterval(t)
  }, [])

  const m = hash.match(/^#\/partida\/(\d+)/)
  const rm = hash.match(/^#\/partida\/(\d+)\/round\/(\d+)(?:\/t\/(\d+))?/)
  const cfg = hash.startsWith('#/config')
  const geral = hash.startsWith('#/geral')
  const mapas = hash.startsWith('#/mapas')
  const mira = hash.startsWith('#/mira')
  const comparar = hash.startsWith('#/comparar')
  const go = (h) => { location.hash = h; document.querySelector('.main')?.scrollTo(0, 0) }

  return (
    <div className="app">
      <nav className="side">
        <div className="logo">C</div>
        <button className={`nav-btn ${!m && !cfg && !geral && !mapas && !mira && !comparar ? 'active' : ''}`} onClick={() => go('#/')}>
          <Icon.home /><span className="tip">Início</span>
        </button>
        <button className={`nav-btn ${geral ? 'active' : ''}`} onClick={() => go('#/geral')}>
          <Icon.chart /><span className="tip">Geral</span>
        </button>
        <button className={`nav-btn ${mapas ? 'active' : ''}`} onClick={() => go('#/mapas')}>
          <Icon.map /><span className="tip">Mapas</span>
        </button>
        <button className={`nav-btn ${mira ? 'active' : ''}`} onClick={() => go('#/mira')}>
          <Icon.aim /><span className="tip">Mira</span>
        </button>
        <button className={`nav-btn ${comparar ? 'active' : ''}`} onClick={() => go('#/comparar')}>
          <Icon.versus /><span className="tip">Comparar</span>
        </button>
        <div className="nav-spacer" />
        {me?.steamid && (
          <div className="nav-me" title={me.steam_name || ''}>
            <Avatar p={{ ...me, name: me.steam_name }} size={34} />
          </div>
        )}
        <button className={`nav-btn ${cfg ? 'active' : ''}`} onClick={() => go('#/config')}>
          <Icon.gear /><span className="tip">Configurações</span>
        </button>
      </nav>
      <main className="main">
        {cfg ? <Settings />
          : geral ? <Overview />
          : mapas ? <Maps go={go} />
          : mira ? <Aim go={go} />
          : comparar ? <Compare />
          : rm ? <Round key={hash} mid={+rm[1]} rn={+rm[2]} at={rm[3] ? +rm[3] : null} go={go} />
          : m ? <Match id={m[1]} back={() => go('#/')} go={go} />
          : <Home open={(id) => go(`#/partida/${id}`)} live={live} fila={fila} go={go} />}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
