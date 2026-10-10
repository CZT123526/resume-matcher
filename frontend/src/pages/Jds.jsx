import { useCallback, useEffect, useState } from 'react'
import { createJd, listJds, getJd } from '../api'

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

  const onCreate = async () => {
    if (!title.trim() || !content.trim()) {
      setMsg('岗位名称和 JD 原文都要填')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const data = await createJd(title.trim(), content.trim())
      setMsg(`已创建 JD #${data.jd_id}，结构化要求由系统自动抽取`)
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

  return (
    <div>
      <div className="card">
        <h3>新建岗位 JD（结构化要求由规则+模型自动抽取）</h3>
        <div className="field-label">岗位名称</div>
        <input style={{ width: '100%' }} value={title} maxLength={100}
          placeholder="如：Python后端工程师" onChange={(e) => setTitle(e.target.value)} />
        <div className="field-label">JD 原文</div>
        <textarea value={content} maxLength={5000}
          placeholder={'粘贴 JD 全文，例如：\n负责后端服务开发。要求：3年以上Python经验，熟悉FastAPI，本科及以上。'}
          onChange={(e) => setContent(e.target.value)} />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={busy} onClick={onCreate}>{busy ? '创建中…' : '创建 JD'}</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>JD 列表（共 {items.length} 条）</h3>
        {items.length === 0 ? (
          <div className="empty">还没有 JD，先创建一条</div>
        ) : (
          <table>
            <thead>
              <tr><th>ID</th><th>岗位名称</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.jd_id} className="clickable" onClick={() => openDetail(j.jd_id)}>
                  <td>{j.jd_id}</td>
                  <td>{j.title}</td>
                  <td className="muted">{j.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="card">
          <h3>JD 详情 · {detail.title}</h3>
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
          <div className="field-label">原文</div>
          <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{detail.content}</div>
        </div>
      )}
    </div>
  )
}
