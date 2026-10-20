import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { listJds, createMatchTask, getMatchTask, getMatchResults, getMatchScoreDistribution } from '../api'

// 图表懒加载（T40）：echarts 只在出结果后按需拉取，主包保持轻量
const Chart = lazy(() => import('../components/Chart'))

// 证据链文案 → 颜色（契约文案格式见 docs/算法设计.md §4）
const chipKind = (text) => {
  if (/满足|重叠/.test(text)) return 'ok'
  if (/缺少|不满足|不足/.test(text)) return 'bad'
  return 'unknown'
}

// 全量融合分直方图（T40）：降序分数按分值等宽分桶，前 topN 名单独堆一列（橙色）
// ——候选人与非候选人一眼看出分层；数据与排名列表同源（API-18）。
function buildDistOption(scores, topN) {
  const n = scores.length
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const nBins = 24
  const span = max - min || Math.max(max * 0.001, 0.0001)
  const inTop = new Array(nBins).fill(0)
  const rest = new Array(nBins).fill(0)
  scores.forEach((s, i) => {
    const b = Math.min(nBins - 1, Math.floor(((s - min) / span) * nBins))
    if (i < topN) inTop[b]++
    else rest[b]++
  })
  const labels = inTop.map((_, i) => (min + (span * (i + 0.5)) / nBins).toFixed(2))
  return {
    grid: { left: 44, right: 12, top: 34, bottom: 26 },
    tooltip: { trigger: 'axis' },
    legend: { top: 2, right: 4, itemWidth: 12, itemHeight: 8, textStyle: { color: '#6b7280', fontSize: 12 } },
    xAxis: {
      type: 'category', data: labels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: { color: '#6b7280', fontSize: 11 },
      name: '融合分', nameTextStyle: { color: '#9ca3af', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280', fontSize: 11 },
      splitLine: { lineStyle: { color: '#f3f4f6' } },
    },
    series: [
      {
        name: `Top-${topN} 候选`, type: 'bar', stack: 'dist', data: inTop,
        itemStyle: { color: '#d97706', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 24,
      },
      {
        name: '其他候选人', type: 'bar', stack: 'dist', data: rest,
        itemStyle: { color: '#93c5fd', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 24,
      },
    ],
  }
}

export default function Match() {
  const [jds, setJds] = useState([])
  const [jdId, setJdId] = useState('')
  const [topK, setTopK] = useState(10)
  const [task, setTask] = useState(null)      // {task_id, status, progress}
  const [results, setResults] = useState(null)
  const [dist, setDist] = useState(null)      // 全量分数分布（API-18，T40）
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const timerRef = useRef(null)

  useEffect(() => {
    // 下拉是岗位全量选项，显式拉到后端单页上限 100（列表页的分页默认值 20 与此无关）
    listJds(1, 100).then((d) => {
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
          // 分布图失败不挡结果列表：历史任务（无存档）返回空列表，静默隐藏
          getMatchScoreDistribution(taskId)
            .then((d) => setDist(d.scores?.length ? d : null))
            .catch(() => setDist(null))
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
    setDist(null)
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

      {dist && results && results.items.length > 0 && (
        <div className="card">
          <h3>全库匹配分分布 · {dist.n_candidates} 人</h3>
          <div className="muted" style={{ marginBottom: 8 }}>
            与下方排名同一批融合分（Top-K 截断前的全量），橙色为本次召回的 Top-{results.items.length}
          </div>
          <Suspense fallback={<div className="skeleton" style={{ height: 240 }} />}>
            <Chart option={buildDistOption(dist.scores, results.items.length)} height={240} />
          </Suspense>
        </div>
      )}

      {results && (
        <div className="card">
          <h3>匹配结果 · {results.jd_title}（共 {results.items.length} 人）</h3>
          {results.items.length === 0
            ? <div className="empty">没有候选人可匹配，先去上传简历</div>
            : results.items.map((item) => (
              <div key={item.rank} className="rank-card">
                <div className={`rank-num ${item.rank <= 3 ? `top${item.rank}` : ''}`}>{item.rank}</div>
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
