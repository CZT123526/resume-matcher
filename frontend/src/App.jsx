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

export default function App() {
  const [tab, setTab] = useState('resumes')
  const Active = TABS.find((t) => t.key === tab).comp

  return (
    <div>
      <header className="app-header">
        <h1>简历智能解析与人才推荐系统</h1>
        <p>BERT NER 抽取 · 语义匹配 · 证据链可解释 · 运行时全本地</p>
      </header>
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="page">
        <Active />
      </main>
    </div>
  )
}
