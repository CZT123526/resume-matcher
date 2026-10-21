import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import {
  listJds, createMatchTask, getMatchTask, getMatchResults, getMatchScoreDistribution,
  listMatchTasks,
} from '../api'
import ResumeDetailModal from '../components/ResumeDetailModal'

// 图表懒加载（T40）：echarts 只在出结果后按需拉取，主包保持轻量
const Chart = lazy(() => import('../components/Chart'))

// 证据链文案 → 颜色（契约文案格式见 docs/算法设计.md §4；T50 起每条 JD 要求一个标签）
// 注意顺序：先判「不符合」再判「符合」（"不符合"二字里含"符合"）；
// 旧任务的历史文案（技能重叠/学历满足/缺少技能…）为存档原样，保持兼容着色
const chipKind = (text) => {
  if (/不符合|不满足|不足|缺少/.test(text)) return 'bad'
  if (/符合|满足|重叠/.test(text)) return 'ok'
  return 'unknown'
}

// 全量融合分直方图（T40）：降序分数按分值等宽分桶，前 topN 名单独堆一列（橙色）
// ——候选人与非候选人一眼看出分层；数据与排名列表同源（API-18）。
// T43：binScores 单独导出 binOf 映射，点柱子时按下标反查该桶的候选人（与画图同一分箱，永不错位）
function binScores(scores, topN) {
  const n = scores.length
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const nBins = 24
  const span = max - min || Math.max(max * 0.001, 0.0001)
  const inTop = new Array(nBins).fill(0)
  const rest = new Array(nBins).fill(0)
  const binOf = new Array(n).fill(0)
  scores.forEach((s, i) => {
    const b = Math.min(nBins - 1, Math.floor(((s - min) / span) * nBins))
    binOf[i] = b
    if (i < topN) inTop[b]++
    else rest[b]++
  })
  const labels = inTop.map((_, i) => (min + (span * (i + 0.5)) / nBins).toFixed(2))
  return { min, span, nBins, labels, inTop, rest, binOf }
}

function buildDistOption(scores, topN) {
  const { labels, inTop, rest } = binScores(scores, topN)
  const totals = inTop.map((v, i) => v + rest[i])
  const maxTotal = Math.max(...totals)
  return {
    grid: { left: 44, right: 12, top: 34, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      // 垫底层只是热区，不进提示框
      formatter: (ps) => ps.filter((p) => p.seriesName !== '_hit')
        .map((p, i) => (i === 0 ? `${p.axisValueLabel}<br/>` : '') + `${p.marker}${p.seriesName}：${p.value}`)
        .join('<br/>'),
    },
    legend: {
      top: 2, right: 4, itemWidth: 12, itemHeight: 8,
      textStyle: { color: '#6b7280', fontSize: 12 },
      data: [`Top-${topN} 候选`, '其他候选人'],
    },
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
        // 透明垫底层（T44）：占满整列高度，柱子少/矮时整根柱位都是点击热区
        name: '_hit', type: 'bar', barGap: '-100%', barMaxWidth: 56, z: 1, cursor: 'pointer',
        itemStyle: { color: 'rgba(147,197,253,0.10)' }, emphasis: { disabled: true },
        data: totals.map(() => maxTotal),
      },
      {
        name: `Top-${topN} 候选`, type: 'bar', stack: 'dist', data: inTop, cursor: 'pointer', z: 2,
        itemStyle: { color: '#d97706', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 56,
      },
      {
        name: '其他候选人', type: 'bar', stack: 'dist', data: rest, cursor: 'pointer', z: 2,
        itemStyle: { color: '#93c5fd', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 56,
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
  const [binSel, setBinSel] = useState(null)  // 点选的分布柱：{label, count, list}，null=展示默认 Top-K
  const [previewId, setPreviewId] = useState(null)  // 简历预览弹窗（与简历页共用组件）
  const [history, setHistory] = useState([])        // 历史任务面板（A4）：刷新后从这里回到结果
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const timerRef = useRef(null)

  // 校准分（T46）：min-max 归一化只动展示——把本轮全量融合分线性拉伸到 0~100，
  // 最低 0 最高 100。排序、存档、评测口径全部仍用原始融合分；历史任务无存档则退回原始分。
  // B7 已知边界：融合分头部普遍挤在 0.99+，Top-K 常常并列 100——界面如实提示并列，
  // 差距看原始融合分与名次
  const calRange = dist?.scores?.length
    ? (() => {
        let mn = Infinity
        let mx = -Infinity
        for (const s of dist.scores) {
          if (s < mn) mn = s
          if (s > mx) mx = s
        }
        return { mn, mx }
      })()
    : null
  const calOf = (s) => {
    if (!calRange) return null
    return Math.round((calRange.mx > calRange.mn
      ? (s - calRange.mn) / (calRange.mx - calRange.mn)
      : 1) * 100)
  }
  const calTip = calRange
    ? `校准分：把本轮 ${dist.n_candidates} 份候选人的融合分做 min-max 归一化，线性拉伸到 0 到 100，最低 0 分、最高 100 分，只用于横向对比本轮内的相对高低；推荐排序与原始融合分不受影响。头部候选人分数过近时校准分会并列 100，此时差距请看原始融合分`
    : ''

  // JD 下拉要岗位全量选项（B3 挑刺修复：后端单页上限 100，此前第 101 条起永远不可选）——循环拉到拉平
  const fetchAllJds = async () => {
    const first = await listJds(1, 100)
    const items = [...(first.items || [])]
    const pages = Math.ceil((first.total || items.length) / 100)
    for (let p = 2; p <= pages; p++) {
      items.push(...(await listJds(p, 100)).items)
    }
    return items
  }

  const loadHistory = () => {
    listMatchTasks(1, 8).then((d) => setHistory(d.items || [])).catch(() => {})
  }

  // 打开一个任务的结果（轮询完成与历史面板点开共用同一入口）
  const openResults = (taskId) => {
    setBinSel(null)
    getMatchResults(taskId)
      .then((r) => {
        setResults(r)
        // 分布图失败不挡结果列表：历史任务（无存档）返回空列表，静默隐藏
        getMatchScoreDistribution(taskId)
          .then((d) => setDist(d.scores?.length ? d : null))
          .catch(() => setDist(null))
      })
      .catch((e) => setMsg(`读取结果失败：${e.message}`))
  }

  useEffect(() => {
    fetchAllJds().then((items) => {
      setJds(items)
      if (items.length) setJdId(String(items[0].jd_id))
    }).catch((e) => setMsg(`加载 JD 失败：${e.message}`))
    loadHistory()
    return () => clearInterval(timerRef.current)
  }, [])

  // 轮询任务状态：立即探一次再进入 800ms 间隔——常态匹配亚秒级完成，
  // 原先 2s 首轮询会让快任务在前端白等（后端实测热路径 0.5s，冷启动首跑 20s 属一次性成本）
  const startPolling = (taskId) => {
    clearInterval(timerRef.current)
    const tick = async () => {
      try {
        const t = await getMatchTask(taskId)
        setTask(t)
        if (t.status === 'done') {
          clearInterval(timerRef.current)
          openResults(taskId)
          loadHistory()
        } else if (t.status === 'failed') {
          clearInterval(timerRef.current)
          setMsg(`任务失败：${t.error || '未知原因'}`)
        }
      } catch (e) {
        clearInterval(timerRef.current)
        setMsg(`轮询失败：${e.message}`)
      }
    }
    tick()
    timerRef.current = setInterval(tick, 800)
  }

  // 点柱子 → 反查该分数段的候选人（与画图同一分箱函数，永不错位）；历史任务无明细则忽略
  const onBinClick = (params) => {
    if (!dist?.scores?.length || !dist.items?.length) return
    const { min, span, nBins, binOf } = binScores(dist.scores, results.items.length)
    const b = params.dataIndex
    const list = dist.items.filter((_, i) => binOf[i] === b)
    if (!list.length) return
    const lo = (min + (span * b) / nBins).toFixed(3)
    const hi = (min + (span * (b + 1)) / nBins).toFixed(3)
    setBinSel({ label: `${lo} ~ ${hi}`, count: list.length, list })
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
    setBinSel(null)
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

  // 历史面板点开一个任务（A4）：done 直接回结果，failed 带出当时的原因
  const openHistoryTask = (h) => {
    clearInterval(timerRef.current)
    setMsg('')
    setTask({ task_id: h.task_id, status: h.status, progress: h.progress })
    if (h.status === 'done') {
      openResults(h.task_id)
    } else {
      setResults(null)
      setDist(null)
      setBinSel(null)
      if (h.status === 'failed') setMsg(`历史任务 ${h.task_id} 为失败状态`)
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

      {history.length > 0 && (
        <div className="card">
          <h3>历史任务 · 刷新后从这里回到结果</h3>
          <div className="muted" style={{ marginBottom: 8 }}>
            匹配结果按任务完整存档，点击任意历史任务重新打开其排名、分布与证据链
          </div>
          <table>
            <thead>
              <tr><th>任务</th><th>岗位</th><th>召回</th><th>状态</th><th>结果</th><th>发起时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.task_id} className="clickable" onClick={() => openHistoryTask(h)}>
                  <td>{h.task_id}</td>
                  <td>{h.jd_title}</td>
                  <td>Top-{h.top_k}</td>
                  <td>{h.status === 'done' ? '已完成' : h.status === 'failed' ? '失败' : h.status === 'running' ? '进行中' : '排队中'}</td>
                  <td>{h.n_results} 条</td>
                  <td className="muted">{(h.created_at || '').replace('T', ' ').slice(0, 19)}</td>
                  <td>{h.status === 'done' && <button className="btn ghost">查看结果</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dist && results && results.items.length > 0 && (
        <div className="card">
          <h3>全库匹配分分布 · {dist.n_candidates} 人</h3>
          <div className="muted" style={{ marginBottom: 8 }}>
            与下方排名同一批融合分 · Top-K 截断前的全量 · 橙色为本次召回的 Top-{results.items.length}
            {dist.items?.length ? ' · 点击柱子查看该分数段的候选人' : ''}
          </div>
          <Suspense fallback={<div className="skeleton" style={{ height: 240 }} />}>
            <Chart option={buildDistOption(dist.scores, results.items.length)} height={240} onClick={onBinClick} />
          </Suspense>
        </div>
      )}

      {results && binSel && (
        <div className="card">
          <h3>分数段 {binSel.label} · {binSel.count} 人</h3>
          <div className="row" style={{ marginBottom: 8 }}>
            <button className="btn ghost" onClick={() => setBinSel(null)}>
              返回 Top-{results.items.length} 结果
            </button>
            <span className="muted">该融合分区间内的全部候选人，按分数降序 · 点击行或「预览」查看简历详情，详情内可看原件</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th><th>姓名</th><th>简历</th><th>融合分</th>
                <th title={calTip}>校准分 ⓘ</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {binSel.list.map((x, i) => (
                <tr key={x.resume_id} className="clickable" onClick={() => setPreviewId(x.resume_id)}>
                  <td>{i + 1}</td>
                  <td>{x.name}</td>
                  <td className="muted">简历 {x.resume_id}</td>
                  <td>{x.score}</td>
                  <td>{calOf(x.score)}</td>
                  <td>
                    <button className="btn ghost"
                      onClick={(e) => { e.stopPropagation(); setPreviewId(x.resume_id) }}>预览</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {results && !binSel && (
        <div className="card">
          <h3>匹配结果 · {results.jd_title} · 共 {results.items.length} 人</h3>
          {results.items.length === 0 ? (
            <div className="empty">没有候选人可匹配，先去上传简历</div>
          ) : (
            <>
              <div className="muted" style={{ marginBottom: 8 }}>
                展示用校准分：把本轮融合分线性拉伸到 0 到 100，同领域文本原始分普遍偏高，拉伸后更容易看出差距 · 鼠标停在 ⓘ 上看算法说明
              </div>
              {(() => {
                const sat = results.items.filter((it) => calOf(it.score) === 100).length
                return sat >= 3 ? (
                  <div className="warn-text" style={{ marginBottom: 8 }}>
                    本轮前 {sat} 名校准分并列 100——头部融合分差距已小于校准分能表达的精度，比差距请看各卡下方的原始融合分与名次
                  </div>
                ) : null
              })()}
              {results.items.map((item) => {
                // 超过比例：用同一任务的全量分数分布（API-18）算相对位置，旧任务无存档则不显示
                const beat = dist?.scores?.length
                  ? Math.round(100 * dist.scores.filter((s) => s < item.score).length / dist.scores.length)
                  : null
                const cal = calOf(item.score)
                const shown = cal != null ? cal : Math.round(item.score * 100)
                return (
                  <div key={item.rank} className="rank-card">
                    <div className={`rank-num ${item.rank <= 3 ? `top${item.rank}` : ''}`}>{item.rank}</div>
                    <div className="candidate">
                      <div className="name">{item.candidate_name}</div>
                      <div className="meta file-link" title="预览简历详情"
                        onClick={() => setPreviewId(item.resume_id)}>简历 {item.resume_id}</div>
                      <div style={{ marginTop: 8 }}>
                        {item.evidence.map((e, i) => (
                          <span key={i} className={`chip ${chipKind(e)}`}>{e}</span>
                        ))}
                      </div>
                    </div>
                    <div className="score-wrap">
                      <div className="score-num">{shown}</div>
                      <div className="muted">
                        校准分 / 100
                        {cal != null && (
                          <span title={calTip} style={{ cursor: 'help', marginLeft: 4 }}>ⓘ</span>
                        )}
                      </div>
                      <div className="bar"><div style={{ width: `${shown}%` }} /></div>
                      {item.score_detail && (
                        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                          原始融合分 {item.score} · 语义 {item.score_detail.semantic} · 词面 {item.score_detail.lexical} · 权重 α {item.score_detail.alpha}
                        </div>
                      )}
                      {!item.score_detail && (
                        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>原始融合分 {item.score}</div>
                      )}
                      {beat != null && (
                        <div className="muted" style={{ fontSize: 12 }}>超过全库 {beat}% 候选人</div>
                      )}
                    </div>
                  </div>
                )
              })}
            </>
          )}
        </div>
      )}

      {previewId != null && (
        <ResumeDetailModal resumeId={previewId} onClose={() => setPreviewId(null)} />
      )}
    </div>
  )
}
