import { useEffect, useState } from 'react'
import Home from './pages/Home.jsx'
import Resumes from './pages/Resumes.jsx'
import Jds from './pages/Jds.jsx'
import Match from './pages/Match.jsx'
import ModelInfo from './pages/ModelInfo.jsx'
import Login from './pages/Login.jsx'
import { clearToken, getMe, getToken, logout, setToken } from './api'
import './styles.css'

const TABS = [
  { key: 'home', label: '主页', comp: Home },
  { key: 'resumes', label: '简历库', comp: Resumes },
  { key: 'jds', label: '岗位 JD', comp: Jds },
  { key: 'match', label: '人才匹配', comp: Match },
  { key: 'model', label: '模型状态', comp: ModelInfo },
]

// T40v2：左侧边栏布局（用户要求导航放左手边），标题配色转沉稳石墨蓝
// T48：新增主页总览，作为默认页
// T54：全站登录门——localStorage 无 token 渲染 Login；侧边栏底部显示当前用户并支持退出
export default function App() {
  const [token, setToken] = useState(() => getToken())
  const [me, setMe] = useState(null) // {username, role}；刷新后由 /auth/me 补回
  const [tab, setTab] = useState('home')

  useEffect(() => {
    if (token) getMe().then(setMe).catch(() => {})
  }, [token])

  if (!token) return <Login onLogin={(data) => { setMe(data); setToken(data.token) }} />

  const Active = TABS.find((t) => t.key === tab).comp

  const onLogout = async () => {
    try { await logout() } catch { /* 会话可能已失效，本地清理照常 */ }
    clearToken()
    setMe(null)
    setToken(null)
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">简</span>
          <div className="brand-text">
            <h1>简历解析与人才推荐</h1>
          </div>
        </div>
        <nav className="side-nav">
          {TABS.map((t) => (
            <button key={t.key} className={`side-item ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <span className="side-user">{me?.username || '已登录'}</span>
          <button className="btn ghost btn-xs" onClick={onLogout}>退出登录</button>
        </div>
      </aside>
      <main className="page">
        <Active />
      </main>
    </div>
  )
}
