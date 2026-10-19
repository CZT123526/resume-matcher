import { useState } from 'react'
import Resumes from './pages/Resumes.jsx'
import Jds from './pages/Jds.jsx'
import Match from './pages/Match.jsx'
import ModelInfo from './pages/ModelInfo.jsx'
import './styles.css'

const TABS = [
  { key: 'resumes', label: '简历库', comp: Resumes },
  { key: 'jds', label: '岗位 JD', comp: Jds },
  { key: 'match', label: '人才匹配', comp: Match },
  { key: 'model', label: '模型状态', comp: ModelInfo },
]

// T40v2：左侧边栏布局（用户要求导航放左手边），标题配色转沉稳石墨蓝
export default function App() {
  const [tab, setTab] = useState('resumes')
  const Active = TABS.find((t) => t.key === tab).comp

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">简</span>
          <div className="brand-text">
            <h1>简历智能解析与人才推荐系统</h1>
            <p>BERT NER · 语义匹配 · 全本地运行</p>
          </div>
        </div>
        <nav className="side-nav">
          {TABS.map((t) => (
            <button key={t.key} className={`side-item ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">运行时零外部 API · SQLite + NumPy</div>
      </aside>
      <main className="page">
        <Active />
      </main>
    </div>
  )
}
