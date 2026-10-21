import { lazy, Suspense, useEffect, useState } from 'react'
import { getHomeStats } from '../api'

// 图表懒加载（T40 同款）：echarts 只在本页按需拉取，主包保持轻量
const Chart = lazy(() => import('../components/Chart'))

// 主页（T48，API-19）：库规模总览 + 两类排名。数字全部来自业务库实时聚合，
// 口径如实写在脚注；展示纪律与全站一致：中文先行、不写括号注解。
function rankOption(rows, color) {
  const data = [...rows].reverse() // 倒序放入 → 渲染后最大值在顶
  return {
    grid: { left: 160, right: 40, top: 8, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'value', minInterval: 1, // 份数为整数，坐标轴不出现小数刻度
      axisLabel: { color: '#6b7280', fontSize: 11 },
      splitLine: { lineStyle: { color: '#f3f4f6' } },
    },
    yAxis: {
      type: 'category', data: data.map((r) => r.title),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: { color: '#374151', fontSize: 12 },
    },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: data.map((r) => ({ value: r.n, itemStyle: { color, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: 'right', color: '#374151', fontSize: 12 },
    }],
  }
}

export default function Home() {
  const [stats, setStats] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getHomeStats().then(setStats).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="card error-text">加载失败：{err}</div>
  if (!stats) {
    return (
      <div>
        <div className="stat-row">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card stat-card"><div className="skeleton" style={{ height: 48 }} /></div>
          ))}
        </div>
        <div className="card"><div className="skeleton" style={{ height: 280, marginBottom: 18 }} /></div>
        <div className="card"><div className="skeleton" style={{ height: 280 }} /></div>
      </div>
    )
  }

  const c = stats.resumes
  return (
    <div>
      <div className="stat-row">
        <div className="card stat-card">
          <div className="stat-num">{c.all}</div>
          <div className="stat-label">简历总量</div>
          <div className="stat-sub">正式 {c.business} · 改写 {c.rewrite} · 半规范 {c.semispec} · 外校卷 {c.fresh}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-num">{stats.jd_count}</div>
          <div className="stat-label">岗位库</div>
          <div className="stat-sub">已跑过匹配 {stats.jd_covered} 个岗位</div>
        </div>
        <div className="card stat-card">
          <div className="stat-num">{stats.match_done}</div>
          <div className="stat-label">已完成匹配任务</div>
          <div className="stat-sub">每次对全库候选人排名</div>
        </div>
        <div className="card stat-card">
          <div className="stat-num">{stats.title_kinds}</div>
          <div className="stat-label">岗位方向</div>
          <div className="stat-sub">{stats.title_resumes} 份简历带岗位字段</div>
        </div>
      </div>

      <div className="card">
        <h3>简历应聘岗位排名 · 前十</h3>
        <div className="muted" style={{ marginBottom: 8 }}>
          口径为解析出的任职或应聘岗位名称，同一份简历可命中多个岗位名 · 未抽到岗位字段的简历不计入
        </div>
        {stats.title_rank.length ? (
          <Suspense fallback={<div className="skeleton" style={{ height: 280 }} />}>
            <Chart option={rankOption(stats.title_rank, '#2563eb')} height={280} />
          </Suspense>
        ) : (
          <div className="empty">还没有解析出岗位字段</div>
        )}
      </div>

      <div className="card">
        <h3>岗位人才储备排名 · 前十</h3>
        <div className="muted" style={{ marginBottom: 8 }}>
          每个岗位取最近一次完成的匹配任务，条上数字为该次召回的简历份数，由当次任务的召回设置决定 ·
          未跑过匹配的岗位不进榜，还有 {stats.jd_count - stats.jd_covered} 个岗位没跑过
        </div>
        {stats.jd_rank.length ? (
          <Suspense fallback={<div className="skeleton" style={{ height: 280 }} />}>
            <Chart option={rankOption(stats.jd_rank, '#d97706')} height={280} />
          </Suspense>
        ) : (
          <div className="empty">先去「人才匹配」页发起一次匹配，这里就会有数据</div>
        )}
      </div>
    </div>
  )
}
