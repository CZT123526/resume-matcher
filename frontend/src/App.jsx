import { useEffect, useState } from 'react'

// 骨架默认页：请求后端 /api/health 展示联通状态，联调通过后替换为真实页面
export default function App() {
  const [health, setHealth] = useState('检测中...')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setHealth(d.status === 'ok' ? '✅ 后端联通正常' : '⚠️ 后端响应异常'))
      .catch(() => setHealth('❌ 无法连接后端（请先启动 backend，端口 8000）'))
  }, [])

  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 720, margin: '80px auto', textAlign: 'center' }}>
      <h1>简历智能解析与人才推荐系统</h1>
      <p>BERT NER · 语义匹配 · 多模型对比 · 骨架 v0.1.0</p>
      <p>{health}</p>
    </div>
  )
}
