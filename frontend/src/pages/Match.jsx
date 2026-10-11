import { useEffect, useRef, useState } from 'react'
import { listJds, createMatchTask, getMatchTask, getMatchResults } from '../api'

// 证据链文案 → 颜色（契约文案格式见 docs/算法设计.md §4）
const chipKind = (text) => {
  if (/满足|重叠/.test(text)) return 'ok'
  if (/缺少|不满足|不足/.test(text)) return 'bad'
  return 'unknown'
}

export default function Match() {
  const [jds, setJds] = useState([])
  const [jdId, setJdId] = useState('')
  const [topK, setTopK] = useState(10)
  const [task, setTask] = useState(null)      // {task_id, status, progress}
  const [results, setResults] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const timerRef = useRef(null)

  useEffect(() => {
    listJds().then((d) => {
      setJds(d.items || [])
      if (d.items?.length) setJdId(String(d.items[0].jd_id))
    }).catch((e) => setMsg(`加载 JD 失败：${e.message}`))
    return () => clearInterval(timerRef.current)
  }, [])

  const startPolling = (taskId) => {
    clearInterval(timerRef.current)
    timerRef.current = setInterval(async () => {
      try {
        const t = await getMatchTask(taskId)
        setTask(t)
        if (t.status === 'done') {
          clearInterval(timerRef.current)
          setResults(await getMatchResults(taskId))
        } else if (t.status === 'failed') {
          clearInterval(timerRef.current)
          setMsg(`任务失败：${t.error || '未知原因'}`)
        }
      } catch (e) {
        clearInterval(timerRef.current)
        setMsg(`轮询失败：${e.message}`)
      }
    }, 2000)
  }

  const onRun = async () => {
    if (!jdId) {
      setMsg('请先在「岗位 JD」页创建一条 JD')
      return
    }
    setBusy(true)
    setMsg('')
    setResults(null)
    setTask(null)
    try {
      const t = await createMatchTask(Number(jdId), Number(topK))
      setTask(t)
      startPolling(t.task_id)
    } catch (e) {
      setMsg(`发起失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card">
        <h3>发起人才匹配（岗位 → 候选人 Top-K 排名）</h3>
        <div className="row">
          <select value={jdId} onChange={(e) => setJdId(e.target.value)}>
            {jds.length === 0 && <option value="">（暂无 JD，请先创建）</option>}
            {jds.map((j) => <option key={j.jd_id} value={j.jd_id}>{j.jd_id} {j.title}</option>)}
          </select>
          <label className="muted">召回人数</label>
          <input type="number" min={1} max={50} value={topK}
            onChange={(e) => setTopK(e.target.value)} style={{ width: 80 }} />
          <button className="btn" disabled={busy} onClick={onRun}>{busy ? '发起中…' : '开始匹配'}</button>
        </div>
        {msg && <div className="error-text" style={{ marginTop: 8 }}>{msg}</div>}
        {task && task.status !== 'done' && (
          <div style={{ marginTop: 12 }}>
            <div className="muted">任务 {task.task_id} · {task.status} · {task.progress}%</div>
            <div className="progress-line"><div style={{ width: `${task.progress}%` }} /></div>
          </div>
        )}
      </div>

      {results && (
        <div className="card">
          <h3>匹配结果 · {results.jd_title}（共 {results.items.length} 人）</h3>
          {results.items.length === 0
            ? <div className="empty">没有候选人可匹配，先去上传简历</div>
            : results.items.map((item) => (
              <div key={item.rank} className="rank-card">
                <div className={`rank-num ${item.rank === 1 ? 'top' : ''}`}>{item.rank}</div>
                <div className="candidate">
                  <div className="name">{item.candidate_name}</div>
                  <div className="meta">简历 {item.resume_id}</div>
                  <div style={{ marginTop: 8 }}>
                    {item.evidence.map((e, i) => (
                      <span key={i} className={`chip ${chipKind(e)}`}>{e}</span>
                    ))}
                  </div>
                </div>
                <div className="score-wrap">
                  <div className="score-num">{Math.round(item.score * 100)}</div>
                  <div className="muted">匹配度 / 100</div>
                  <div className="bar"><div style={{ width: `${Math.round(item.score * 100)}%` }} /></div>
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
