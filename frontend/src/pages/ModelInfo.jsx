import { lazy, Suspense, useEffect, useState } from 'react'
import { getModelInfo } from '../api'

// 图表懒加载（T40）：echarts 只在本页按需拉取，主包保持轻量
const Chart = lazy(() => import('../components/Chart'))

// 冻结评测口径（v4 主测试集 8142 对/46 查询，NDCG@10；T39 自适应 α 为三池验证后默认值）。
// 数据来源：docs/eval/eval_report.json、adaptive_alpha_report.json、semispec_report.json、
// stress_report.json（2026-10-19 冻结）。前端只做展示，评测一律以 docs/eval/ 产物为准。
// 展示纪律：界面文案不写括号注解——归类信息用「·」分隔进条形图标签，细节进脚注分句（用户要求）
const EVAL_MAIN = [
  { name: '对比微调 bert_pair *', v: 1.0, kind: 'ablation' },
  { name: 'TF-IDF · 词面对照', v: 0.9898, kind: 'baseline' },
  { name: 'DeepSeek · 大模型对照', v: 0.9783, kind: 'baseline' },
  { name: '本文方法 · 自适应 α', v: 0.9522, kind: 'ours' },
  { name: '本文方法 · 固定 α=0.7', v: 0.9305, kind: 'ours' },
  { name: '纯语义 DAPT · 消融', v: 0.7483, kind: 'ablation' },
  { name: '底座 BERT · 消融', v: 0.6968, kind: 'ablation' },
]
const KIND_COLOR = { ours: '#2563eb', baseline: '#64748b', ablation: '#cbd5e1' }

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
        label: { show: true, position: 'right', color: '#374151', fontSize: 12, formatter: ({ value }) => value.toFixed(4) },
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
            <tr><td>模型</td><td>{info.model_name}</td></tr>
            <tr><td>版本</td><td>{info.version}</td></tr>
            <tr>
              <td>实体级 F1</td>
              <td>{info.f1 > 0 ? `${(info.f1 * 100).toFixed(1)}%` : '未微调 · 训练完成后自动展示'}</td>
            </tr>
            <tr><td>训练样本数</td><td>{info.train_samples || '—'}</td></tr>
            <tr><td>更新时间</td><td>{info.updated_at || '—'}</td></tr>
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>
          说明：实体抽取 = 微调 BERT + 规则锚定兜底——显式字段行强锚定，来源标注 bert/rule；
          语义匹配 = DAPT 领域预训练编码 + 关键词重排；自适应 α 默认开启，词面证据稀薄时自动退向纯语义。
        </p>
      </div>

      <div className="card">
        <h3>评测成绩单 · 冻结口径 NDCG@10</h3>
        <div className="muted" style={{ marginBottom: 8 }}>
          主测试集：金标准 8142 对 / 46 查询 / 1062 简历 / 55 JD；蓝色为本文方法，深灰为外部对照，浅灰为消融
        </div>
        <Suspense fallback={<div className="skeleton" style={{ height: 300 }} />}>
          <Chart option={buildEvalOption()} height={300} />
        </Suspense>
        <p className="muted" style={{ marginBottom: 0 }}>
          * 转导口径：角色标签与测试集同源，仅作消融展示；留出法 0.9929，背题 &lt;1pp，泛化已实证。
          两批加试简历：改写简历上 bert_pair 0.9799 首超 TF-IDF 0.9633；半规范简历上语义编码 DAPT 0.9807——
          伤系统的是内容缺失而非排版花哨。数字一律以 docs/eval/ 下 JSON 报告为准。
        </p>
      </div>
    </>
  )
}
