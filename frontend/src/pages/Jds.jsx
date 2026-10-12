import { useCallback, useEffect, useState } from 'react'
import { createJd, listJds, getJd } from '../api'

// 评测查询语料（金标准 216 对引用 id 1~13 的 JD，T26 冻结协议，不可删改）——
// 前端折叠展示，同简历库的种子分组策略（T29.3）；新增招聘岗位 id 从 14 起
const EVAL_JD_MAX_ID = 13

export default function Jds() {
  const [items, setItems] = useState([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(async () => {
    try {
      const data = await listJds()
      setItems(data.items || [])
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // 详情弹窗（T31）：× 或点遮罩或 Esc 关闭，正文弹窗内滚动
  const closeModal = () => setDetail(null)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') closeModal() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onCreate = async () => {
    if (!title.trim() || !content.trim()) {
      setMsg('岗位名称和 JD 原文都要填')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const data = await createJd(title.trim(), content.trim())
      setMsg(`已创建 JD ${data.jd_id}，结构化要求由系统自动抽取`)
      setTitle('')
      setContent('')
      await refresh()
    } catch (e) {
      setMsg(`创建失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const openDetail = async (id) => {
    setDetail(null)
    try {
      setDetail(await getJd(id))
    } catch (e) {
      setMsg(`详情失败：${e.message}`)
    }
  }

  const mainItems = items.filter((j) => j.jd_id > EVAL_JD_MAX_ID)
  const evalItems = items.filter((j) => j.jd_id <= EVAL_JD_MAX_ID)

  const renderTable = (rows) => (
    <table>
      <thead>
        <tr><th>ID</th><th>岗位名称</th><th>创建时间</th></tr>
      </thead>
      <tbody>
        {rows.map((j) => (
          <tr key={j.jd_id} className="clickable" onClick={() => openDetail(j.jd_id)}>
            <td>{j.jd_id}</td>
            <td>{j.title}</td>
            <td className="muted">{j.created_at}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <div>
      <div className="card">
        <h3>新建岗位 JD（结构化要求由规则+模型自动抽取）</h3>
        <div className="field-label">岗位名称</div>
        <input style={{ width: '100%' }} value={title} maxLength={100}
          placeholder="如：Python后端开发工程师" onChange={(e) => setTitle(e.target.value)} />
        <div className="field-label">JD 原文</div>
        <textarea value={content} maxLength={5000}
          placeholder={'粘贴 JD 全文，例如：\n岗位职责：\n1.负责后端服务开发与性能优化\n任职要求：\n1.学历要求：本科及以上\n2.熟练掌握 Python/FastAPI，3年以上相关经验'}
          onChange={(e) => setContent(e.target.value)} />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={busy} onClick={onCreate}>{busy ? '创建中…' : '创建 JD'}</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>岗位列表（招聘岗位 {mainItems.length} 个 + 评测查询语料 {evalItems.length} 条）</h3>
        {items.length === 0 ? (
          <div className="empty">还没有 JD，先创建一条</div>
        ) : (
          <>
            {renderTable(mainItems)}
            {evalItems.length > 0 && (
              <details style={{ marginTop: 10 }}>
                <summary className="muted" style={{ cursor: 'pointer' }}>
                  评测查询语料（{evalItems.length} 条）· 对比实验专用 · 金标准 216 对引用 · 点开展开
                </summary>
                {renderTable(evalItems)}
              </details>
            )}
          </>
        )}
      </div>

      {detail && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>岗位详情 · {detail.title}</h3>
              <button className="modal-close" title="关闭（Esc）" onClick={closeModal}>×</button>
            </div>
            <div className="modal-body">
              <div className="field-label">结构化要求（自动抽取）</div>
              <div>
                {detail.req_json
                  ? <>
                    <span className="chip">学历：{detail.req_json.degree || '不限'}</span>
                    <span className="chip">经验：{detail.req_json.min_years != null ? `${detail.req_json.min_years}年以上` : '不限'}</span>
                    {(detail.req_json.skills || []).map((s) => <span key={s} className="chip">技能：{s}</span>)}
                  </>
                  : <span className="muted">（未抽取）</span>}
              </div>
              <div className="field-label">岗位 JD 原文（全文，弹窗内可滚动）</div>
              <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{detail.content}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
