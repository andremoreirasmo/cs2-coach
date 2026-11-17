import { useEffect, useState } from 'react'
import { api, post } from './lib.jsx'

const open = (name) => post(`/open/${name}`).catch(() => {})

function LinkBtn({ name, children }) {
  return (
    <button className="link-btn" onClick={() => open(name)}>
      {children}
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
    </button>
  )
}

function Field({ label, value, onChange, saved, secret, placeholder, mono }) {
  const [show, setShow] = useState(false)
  return (
    <label className="field">
      <span className="field-label">{label}{saved && <em>salvo: {saved}</em>}</span>
      <div className="field-box">
        <input type={secret && !show ? 'password' : 'text'} value={value} onChange={(e) => onChange(e.target.value)}
          placeholder={saved ? 'Deixe em branco para manter o valor salvo' : placeholder} spellCheck={false}
          className={mono ? 'mono' : ''} autoComplete="off" />
        {secret && <button type="button" className="eye" onClick={() => setShow(!show)}>{show ? 'ocultar' : 'mostrar'}</button>}
      </div>
    </label>
  )
}

function Section({ icon, title, desc, ok, optional, children }) {
  return (
    <section className="card cfg">
      <div className="cfg-head">
        <div className="cfg-icon">{icon}</div>
        <div className="cfg-title">
          <h2>{title}</h2>
          <p>{desc}</p>
        </div>
        <span className={`status-chip ${ok ? 'on' : ''}`}>{ok ? 'Conectado' : optional ? 'Opcional' : 'Não configurado'}</span>
      </div>
      {children}
    </section>
  )
}

function Steps({ children }) {
  return <ol className="steps">{children}</ol>
}

function useSave(fn, after) {
  const [state, setState] = useState({ busy: false, msg: null, err: false })
  const run = async (...args) => {
    setState({ busy: true, msg: null, err: false })
    try {
      const s = await fn(...args)
      after(s)
      setState({ busy: false, msg: 'Salvo e testado com sucesso.', err: false })
    } catch (e) {
      setState({ busy: false, msg: e.message, err: true })
    }
  }
  return [state, run]
}

function Result({ s }) {
  if (s.busy) return <span className="result">Testando…</span>
  if (!s.msg) return null
  return <span className={`result ${s.err ? 'bad' : 'good'}`}>{s.err ? '✕ ' : '✓ '}{s.msg}</span>
}

const gb = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1).replace('.', ',')} GB` : `${Math.round(b / 1e6)} MB`)

export default function Settings() {
  const [st, setSt] = useState(null)
  const [fk, setFk] = useState('')
  const [nick, setNick] = useState('')
  const [sk, setSk] = useState('')
  const [auth, setAuth] = useState('')
  const [code, setCode] = useState('')

  useEffect(() => { api('/settings').then((s) => { setSt(s); setNick(s.faceit.nickname || '') }) }, [])

  const [fs, saveFaceit] = useSave(() => post('/settings/faceit', { key: fk, nickname: nick }), (s) => { setSt(s); setFk('') })
  const [ss, saveSteam] = useSave(() => post('/settings/steam', { key: sk, auth, sharecode: code }),
    (s) => { setSt(s); setSk(''); setAuth(''); setCode('') })
  const clear = (what) => post(`/settings/${what}`, { clear: true }).then(setSt)
  const startup = (on) => post('/settings/startup', { on }).then(setSt)
  const originals = (on) => post('/settings/originais', { on }).then(setSt)
  const pauseInGame = (on) => post('/settings/pausar', { on }).then(setSt)
  const [cleaning, setCleaning] = useState(null)
  const cleanOriginals = () => {
    setCleaning('…')
    post('/settings/originais/limpar', {}).then((s) => { setSt(s); setCleaning(`${s.limpou.n} arquivo(s) apagado(s), ${gb(s.limpou.bytes)} liberados.`) })
      .catch(() => setCleaning('Não deu para apagar agora. Tente de novo.'))
  }

  if (!st) return <div className="loading"><div><div className="spinner" />Carregando…</div></div>

  return (
    <div className="page cfg-page">
      <div className="topbar">
        <div>
          <h1>Configurações</h1>
          <div className="sub">Conecte suas contas. Cada chave é testada na hora em que você salva.</div>
        </div>
      </div>

      <div className="privacy">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
        <span>As chaves ficam guardadas no <b>Gerenciador de Credenciais do Windows</b>, criptografadas, e só são usadas para falar com o próprio serviço delas. Esta tela mostra apenas os últimos 4 caracteres.</span>
      </div>

      {/* ---------------- FACEIT ---------------- */}
      <Section ok={st.faceit.ok} title="FACEIT" desc="Não precisa de chave nem de aprovação. Só o seu nick, para o app abrir suas partidas na FACEIT com um clique."
        icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M21.5 2.5 9 9.4h12.5V2.5zM2.5 21.5h5.6L21.5 12H9z" opacity=".9" /></svg>}>
        <Steps>
          <li>Escreva seu nick <b>exatamente</b> como aparece na FACEIT e salve.</li>
          <li>Depois de cada partida, clique em <b>Partidas na FACEIT</b> na tela inicial, abra a partida e clique em <b>Assistir demo</b>.</li>
          <li>Pronto: o arquivo cai na pasta Downloads e o app importa e analisa sozinho. Se baixar em outro lugar, use <b>+ Adicionar demo</b>.</li>
        </Steps>
        <div className="field-row">
          <Field label="Seu nick na FACEIT" value={nick} onChange={setNick} placeholder="Ex.: SeuNick" />
        </div>
        <details className="more">
          <summary>Avançado (opcional): data real das partidas e aviso automático, com chave de desenvolvedor</summary>
          <p>A demo não guarda quando a partida foi jogada, só quando você baixou. Com uma chave do FACEIT Developers
            (sai na hora, <b>não precisa de aprovação</b>), o app mostra a data e a hora reais de cada partida e já coloca
            a partida na lista assim que ela termina. Sem a chave, a análise funciona igual.</p>
          <Steps>
            <li>Entre no FACEIT Developers com a sua conta. <LinkBtn name="faceit_dev">Abrir FACEIT Developers</LinkBtn></li>
            <li><b>App Studio</b> → <b>Create App</b> → aba <b>API Keys</b> → crie uma chave <b>Server side</b> e cole abaixo.</li>
          </Steps>
          <Field label="Chave Server side" secret mono value={fk} onChange={setFk} saved={st.faceit.key} placeholder="opcional" />
        </details>
        <div className="cfg-actions">
          <button className="btn-primary" disabled={fs.busy || !nick} onClick={saveFaceit}>Salvar</button>
          {st.faceit.ok && <button className="btn-ghost" onClick={() => clear('faceit')}>Remover</button>}
          <Result s={fs} />
        </div>
      </Section>

      {/* ---------------- Steam ---------------- */}
      <Section ok={st.steam.ok} optional title="Premier e Competitivo" desc="Não precisa configurar nada. Depois da partida, no CS: Assistir → Suas partidas → baixar. O app importa e analisa sozinho."
        icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="15.5" cy="8.5" r="3.5" /><circle cx="8" cy="16" r="2.5" /><path d="M10.2 14.8 13 11.5M2 12.5l4.2 1.8" /></svg>}>
        <details className="more">
        <summary>Avançado (opcional): lembrete de partida na lista, com a API da Steam</summary>
        <p>A API da Steam só avisa que uma partida terminou, para ela aparecer na lista como "aguardando demo". Não baixa a demo nem muda a análise.</p>
        <Steps>
          <li>Pegue sua <b>chave Web API</b>: na página abaixo, em <b>Domain Name</b> escreva <code>localhost</code>, aceite os termos, clique em <b>Register</b> e copie a <b>Key</b>. <LinkBtn name="steam_apikey">Abrir chave Web API</LinkBtn></li>
          <li>Abra a página de <b>histórico de partidas do CS2</b> no Suporte Steam. Clique em <b>Criar código de autenticação</b> e copie o código (formato <code>AAAA-AAAAA-AAAA</code>). <LinkBtn name="steam_authcode">Abrir histórico de partidas</LinkBtn></li>
          <li>Na mesma página aparece <b>seu código de partida mais recente</b> (começa com <code>CSGO-</code>). Copie também.</li>
          <li>Cole os três abaixo e salve. Depois de cada partida, baixe a demo no CS: <b>Assistir → Suas partidas → baixar</b>.</li>
        </Steps>
        <div className="field-row three">
          <Field label="Chave Web API" secret mono value={sk} onChange={setSk} saved={st.steam.key} placeholder="32 caracteres" />
          <Field label="Código de autenticação" secret mono value={auth} onChange={setAuth} saved={st.steam.auth} placeholder="AAAA-AAAAA-AAAA" />
          <Field label="Último share code" mono value={code} onChange={setCode} saved={st.steam.sharecode} placeholder="CSGO-xxxxx-xxxxx-..." />
        </div>
        <div className="hint-line">SteamID: {st.steam.steamid ? <b>{st.steam.steamid}</b> : 'abra uma partida e escolha qual jogador é você'}</div>
        <div className="cfg-actions">
          <button className="btn-primary" disabled={ss.busy || ((!sk && !st.steam.key) || (!auth && !st.steam.auth))} onClick={saveSteam}>Salvar e testar</button>
          {st.steam.ok && <button className="btn-ghost" onClick={() => clear('steam')}>Remover</button>}
          <Result s={ss} />
        </div>
        </details>
      </Section>

      {/* ---------------- App ---------------- */}
      <section className="card cfg">
        <div className="cfg-head">
          <div className="cfg-title">
            <h2>Iniciar com o Windows</h2>
            <p>Abre o app escondido na bandeja quando o PC liga, para não perder nenhuma partida.</p>
          </div>
          <button className={`toggle ${st.app.startup ? 'on' : ''}`} onClick={() => startup(!st.app.startup)} aria-label="Iniciar com o Windows"><i /></button>
        </div>
      </section>

      <section className="card cfg">
        <div className="cfg-head">
          <div className="cfg-title">
            <h2>Pausar a análise com o CS aberto</h2>
            <p>Desligado, as demos são processadas mesmo com o CS na frente. Ligue se notar queda de FPS enquanto uma demo é analisada.</p>
          </div>
          <button className={`toggle ${st.app.pausar_no_jogo ? 'on' : ''}`} onClick={() => pauseInGame(!st.app.pausar_no_jogo)} aria-label="Pausar a análise com o CS aberto"><i /></button>
        </div>
      </section>

      <section className="card cfg">
        <div className="cfg-head">
          <div className="cfg-title">
            <h2>Apagar a demo original depois de importar</h2>
            <p>O app guarda a própria cópia de cada demo, então o arquivo baixado (Downloads ou pasta de replays do CS2) vira repetido.
              Com isto ligado, ele é apagado assim que a cópia é conferida. Só a demo importada é apagada.</p>
          </div>
          <button className={`toggle ${st.app.apagar_originais ? 'on' : ''}`} onClick={() => originals(!st.app.apagar_originais)} aria-label="Apagar a demo original depois de importar"><i /></button>
        </div>
        {st.app.originais.n > 0 ? (
          <div className="cfg-row-action">
            <span>{st.app.originais.n} demo(s) já importada(s) ainda estão no PC ocupando <b>{gb(st.app.originais.bytes)}</b>.</span>
            <button className="btn-ghost" disabled={cleaning === '…'} onClick={cleanOriginals}>{cleaning === '…' ? 'Apagando…' : 'Apagar esses originais'}</button>
          </div>
        ) : cleaning ? <p className="hint-line">{cleaning}</p> : null}
        <p className="hint-line">Demos da pasta de replays somem da lista "Assistir" do CS2, mas continuam no app (2D, destaques e Ver no CS2).</p>
      </section>
    </div>
  )
}
