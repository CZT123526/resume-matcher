// 简历详情弹窗（T44，从 Resumes 页抽出）：简历页与匹配页共用同一份预览能力。
// 给 resumeId 自取详情；查看原件 / 解析数据 / 重新解析 / 推荐岗位都在弹窗内闭环；
// × 或点遮罩或 Esc 关闭；打开时主页面滚动由全局 body:has(.modal-overlay) 锁住。
import { useEffect, useRef, useState } from 'react'
import {
  getResume, getResumeData, reparseResume, getJdRecommendations, resumeFileUrl,
} from '../api'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const FIELD_TEXT = {
  name: '姓名', degree: '学历', school: '院校', skill: '技能',
  years: '年限', company: '公司', title: '职位',
}

export default function ResumeDetailModal({ resumeId, onClose }) {
  const [detail, setDetail] = useState(null)
  const [data, setData] = useState(null)        // 解析数据视图（API-16）
  const [recs, setRecs] = useState(null)        // 反向推荐（API-17，T39）
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')          // 重新解析等动作的即时反馈
  const timerRef = useRef(null)

  useEffect(() => {
    setDetail(null)
    setData(null)
    setRecs(null)
    setErr('')
    setNote('')
    getResume(resumeId).then(setDetail).catch((e) => setErr(`详情加载失败：${e.message}`))
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      clearTimeout(timerRef.current)
    }
  }, [resumeId, onClose])

  const openFile = () => window.open(resumeFileUrl(resumeId), '_blank')

  const openData = async () => {
    setData(null)
    try {
      setData(await getResumeData(resumeId))
    } catch (e) {
      setErr(`数据视图失败：${e.message}`)
    }
  }

  // 反向推荐（T39）：done 简历可一键看 Top-3 岗位（校准融合分 + 证据链）
  const openRecs = async () => {
    setRecs({ loading: true })
    try {
      const d = await getJdRecommendations(resumeId, 3)
      setRecs({ loading: false, items: d.items })
    } catch (e) {
      setRecs({ loading: false, error: e.message })
    }
  }

  const onReparse = async () => {
    try {
      await reparseResume(resumeId)
      setNote('已重新排队解析')
      setDetail(null)
      getResume(resumeId).then(setDetail).catch(() => {})
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        getResume(resumeId).then(setDetail).catch(() => {})
      }, 3000)
    } catch (e) {
      setErr(`重解析失败：${e.message}`)
    }
  }

  const d = detail
  const q = d?.quality || {}
  const lowQuality = d?.parse_status === 'done' && (!q.like_resume || q.entity_count === 0)

  return (
    <>
      {d && (
        <div className="modal-overlay" onClick={onClose}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>
                简历详情 · {d.file_name}{' '}
                <span className={`badge ${d.parse_status}`}>{STATUS_TEXT[d.parse_status]}</span>
              </h3>
              <button className="modal-close" title="关闭 · Esc" onClick={onClose}>×</button>
            </div>
            <div className="modal-body">
            <div className="row" style={{ marginBottom: 10 }}>
              <button className="btn ghost" onClick={openFile}>查看原件</button>
              <button className="btn ghost" onClick={openData}>查看解析数据</button>
              <button className="btn ghost" onClick={onReparse}>重新解析</button>
              {d.parse_status === 'done' && (
                <button className="btn ghost" onClick={openRecs}>推荐岗位</button>
              )}
            </div>
            {note && <div className="muted" style={{ marginBottom: 10 }}>{note}</div>}
            {err && <div className="error-text" style={{ marginBottom: 10 }}>{err}</div>}
            {recs && (
              <div style={{ marginBottom: 12 }}>
                <div className="field-label">推荐岗位 Top-3 · 校准融合分：α 加权语义百分位，其余权重给词面命中率</div>
                {recs.loading && <span className="muted">计算中，首次需先构建岗位向量…</span>}
                {recs.error && <span className="error-text">推荐失败：{recs.error}</span>}
                {recs.items?.map((it, i) => (
                  <div key={it.jd_id} className="rec-item">
                    <div className="rec-head">
                      <span className="rec-title">#{i + 1} {it.title}</span>
                      <span className="rec-score">{it.score}</span>
                    </div>
                    <div className="bar"><div style={{ width: `${Math.round(it.score * 100)}%` }} /></div>
                    <div className="rec-meta">
                      语义百分位 {it.semantic_percentile} · 词面命中 {it.keyword_hit}/{it.n_keywords} 词
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>{it.evidence.join('；') || '暂无证据项'}</div>
                  </div>
                ))}
              </div>
            )}
            {d.parse_status === 'failed' && (
              <div className="error-text">解析失败：{d.parse_error || '未知原因'}</div>
            )}
            {lowQuality && (
              <div className="warn-text">解析质量提示：正文 {q.text_chars} 字、实体 {q.entity_count} 条
                {q.like_resume ? '' : '，且内容不像简历'}——可能是扫描件/图片型文件，建议重新解析或换文件</div>
            )}
            <div className="field-label">抽取实体 · 来源 {d.entities?.[0]?.source || '—'}</div>
            <div>
              {d.entities?.length
                ? d.entities.map((e, i) => (
                  <span key={i} className="chip">{FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value}</span>
                ))
                : <span className="muted">暂无实体</span>}
            </div>
            <div className="field-label">简历原文 · 全文 {d.quality?.text_chars ?? (d.raw_text || '').length} 字，弹窗内可滚动</div>
            <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{d.raw_text || '无'}</div>
            </div>
          </div>
        </div>
      )}

      {data && (
        <div className="modal-overlay" onClick={onClose}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>解析数据 · {data.file_name}</h3>
              <button className="btn ghost" onClick={() => setData(null)}>返回详情</button>
              <button className="modal-close" title="关闭 · Esc" onClick={onClose}>×</button>
            </div>
            <div className="modal-body">
            <div className="row">
              <span className="chip">正文 {data.stats.text_chars} 字</span>
              <span className="chip">实体 {data.stats.entity_count} 条</span>
              <span className="chip ok">BERT {data.stats.bert_count}</span>
              <span className="chip unknown">规则 {data.stats.rule_count}</span>
              <span className="chip">向量 {data.matching.vector_dim} 维</span>
              <span className="chip">模长 {data.matching.vector_norm}</span>
            </div>
            <div className="field-label">匹配输入 · structured_text，语义编码真正的对象</div>
            <div className="mono-text">{data.matching.structured_text}</div>
            <div className="field-label">向量预览 · 前 8 维，共 {data.matching.vector_dim} 维</div>
            <div className="mono-text">[{data.matching.vector_preview.join(', ')}]</div>
            <div className="field-label">实体明细 · 每条标注来源</div>
            {data.entities.length
              ? data.entities.map((e, i) => (
                <span key={i} className={`chip ${e.source === 'bert' ? 'ok' : 'unknown'}`}>
                  {FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value} · {e.source}
                </span>
              ))
              : <span className="muted">暂无实体</span>}
            <div className="field-label">解析全文 · 共 {data.stats.text_chars} 字</div>
            <details>
              <summary className="muted" style={{ cursor: 'pointer' }}>展开/收起全文</summary>
              <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{data.raw_text}</div>
            </details>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
