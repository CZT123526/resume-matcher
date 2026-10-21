import { lazy, Suspense, useEffect, useState } from 'react'
import { getModelInfo } from '../api'

// 图表懒加载（T40）：echarts 只在本页按需拉取，主包保持轻量
const Chart = lazy(() => import('../components/Chart'))

// 冻结评测口径（v4 主测试集 8142 对 / 46 查询，排序得分 NDCG@10；T39 自动权重为三池验证后默认值）。
// 数据来源：docs/eval/eval_report.json、adaptive_alpha_report.json、semispec_report.json、
// stress_report.json、fresh_report.json（2026-10-19/21 冻结）。前端只做展示，评测以 docs/eval/ 产物为准。
// 展示纪律：界面文案不写括号注解；页面表达中文先行、少英文少符号，专业术语对照统一收进脚注（用户要求）
const EVAL_MAIN = [
  { name: '对比微调模型 *', v: 1.0, kind: 'ablation' },
  { name: '词面检索对照', v: 0.9898, kind: 'baseline' },
  { name: '大模型对照', v: 0.9783, kind: 'baseline' },
  { name: '本文方法 · 自动权重', v: 0.9522, kind: 'ours' },
  { name: '本文方法 · 固定权重', v: 0.9305, kind: 'ours' },
  { name: '纯语义 · 领域预训练', v: 0.7483, kind: 'ablation' },
  { name: '纯语义 · 原始底座', v: 0.6968, kind: 'ablation' },
]
const KIND_COLOR = { ours: '#2563eb', baseline: '#64748b', ablation: '#cbd5e1' }

// 模型标识 → 中文展示名（标识符本身是训练产物名，不修改数据）
const MODEL_DISPLAY = { 'bert-base-chinese-ner': '中文 BERT 实体抽取模型' }
const VERSION_DISPLAY = { v1: '第一轮', v2: '第二轮' }

// ECharts 横向条形图：本文方法高亮蓝，对照灰、消融浅灰，直读差距
function buildEvalOption() {
  const rows = [...EVAL_MAIN].reverse() // 倒序放入 → 渲染后最大值在顶
  return {
    grid: { left: 170, right: 46, top: 8, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'value', min: 0, max: 1,
      axisLabel: { color: '#6b7280', fontSize: 11 },
      splitLine: { lineStyle: { color: '#f3f4f6' } },
    },
    yAxis: {
      type: 'category', data: rows.map((r) => r.name),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: { color: '#374151', fontSize: 12 },
    },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: rows.map((r) => ({
        value: r.v,
        itemStyle: { color: KIND_COLOR[r.kind], borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: '#374151', fontSize: 12, formatter: ({ value }) => value.toFixed(2) },
      })),
    }],
  }
}

export default function ModelInfo() {
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getModelInfo().then(setInfo).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="card error-text">加载失败：{err}</div>
  if (!info) {
    return (
      <div className="card">
        <h3>模型状态</h3>
        {[88, 72, 60, 52].map((w, i) => (
          <div key={i} className="skeleton" style={{ height: 16, width: `${w}%`, marginBottom: 12 }} />
        ))}
      </div>
    )
  }

  return (
    <>
      <div className="card">
        <h3>模型状态</h3>
        <table>
          <tbody>
            <tr><td>模型</td><td>{MODEL_DISPLAY[info.model_name] || info.model_name}</td></tr>
            <tr><td>训练轮次</td><td>{VERSION_DISPLAY[info.version] || info.version}</td></tr>
            <tr>
              <td>实体抽取得分</td>
              <td>{info.f1 > 0 ? `${(info.f1 * 100).toFixed(1)}%` : '模型训练完成后自动展示'}</td>
            </tr>
            <tr><td>训练语料</td><td>{info.train_samples ? `${info.train_samples} 句` : '—'}</td></tr>
            <tr><td>更新时间</td><td>{(info.updated_at || '—').slice(0, 10)}</td></tr>
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>
          说明：简历解析由微调模型与规则双路合作——原文里明确写了字段行的直接采信，模型只挑有把握的词，没把握宁可漏掉也不乱标。
          岗位匹配先用领域语料继续预训练的语义模型打基础分，再用关键词核对做修正；两组证据的配比按岗位与简历的重合程度自动调节。
        </p>
      </div>

      <div className="card">
        <h3>评测成绩单 · 排序得分，满分 1 分</h3>
        <div className="muted" style={{ marginBottom: 8 }}>
          主测试集：1062 份简历、55 个岗位、46 条查询、金标准 8142 对；蓝色是本系统方法，深灰是外部对照，浅灰是拆解验证
        </div>
        <Suspense fallback={<div className="skeleton" style={{ height: 300 }} />}>
          <Chart option={buildEvalOption()} height={300} />
        </Suspense>
        <p className="muted" style={{ marginBottom: 0 }}>
          * 对比微调的满分是同类考卷上的同源成绩，仅作参照：把一成半简历完全藏起来不让模型见过，仍得 0.99，与满分差距不到一个百分点，说明不是死记硬背。
          三批加试进一步验证：改写卷把简历正文全部重写，对比微调 0.98 反超词面检索 0.96；半规范卷只换排版不换内容，语义编码 0.98——伤系统的是内容缺失，不是排版花哨；
          外校卷用 10 种全新岗位、50 份逐份手写的简历，对比微调仍有 0.97。
          术语对照：词面检索即 TF-IDF、大模型对照即 DeepSeek、对比微调即 bert_pair、领域预训练即 DAPT、原始底座即 BERT、排序得分即 NDCG@10、实体抽取得分即 F1。
          数值以项目评测报告存档为准，此处保留两位小数。
        </p>
      </div>
    </>
  )
}
