import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadResume, listResumes, getResume, deleteResume } from '../api'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const FIELD_TEXT = {
  name: '姓名', degree: '学历', school: '院校', skill: '技能',
  years: '年限', company: '公司', title: '职位',
}

export default function Resumes() {
  const [items, setItems] = useState([])
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const fileRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const data = await listResumes()
      setItems(data.items || [])
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const onUpload = async (file) => {
    if (!file) return
    setBusy(true)
    setMsg('')
    try {
      const data = await uploadResume(file)
      setMsg(`已受理：${data.file_name}（后台解析中，稍候刷新）`)
      await refresh()
    } catch (e) {
      setMsg(`上传失败：${e.message}`)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const openDetail = async (id) => {
    setDetail(null)
    try {
      setDetail(await getResume(id))
    } catch (e) {
      setMsg(`详情失败：${e.message}`)
    }
  }

  const onDelete = async (id) => {
    if (!window.confirm(`确认删除简历 #${id}？`)) return
    try {
      await deleteResume(id)
      setDetail(null)
      await refresh()
    } catch (e) {
      setMsg(`删除失败：${e.message}`)
    }
  }

  return (
    <div>
      <div className="card">
        <h3>上传简历（PDF / DOCX，≤10MB）</h3>
        <div className="row">
          <input ref={fileRef} type="file" accept=".pdf,.docx" disabled={busy}
            onChange={(e) => onUpload(e.target.files[0])} />
          <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? '上传中…' : '选择文件上传'}
          </button>
          <button className="btn ghost" onClick={refresh}>刷新列表</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>简历列表（共 {items.length} 份）</h3>
        {items.length === 0 ? (
          <div className="empty">还没有简历，先上传一份试试</div>
        ) : (
          <table>
            <thead>
              <tr><th>ID</th><th>文件名</th><th>解析状态</th><th>上传时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.resume_id} className="clickable" onClick={() => openDetail(r.resume_id)}>
                  <td>{r.resume_id}</td>
                  <td>{r.file_name}</td>
                  <td><span className={`badge ${r.parse_status}`}>{STATUS_TEXT[r.parse_status] || r.parse_status}</span></td>
                  <td className="muted">{r.created_at}</td>
                  <td>
                    <button className="btn danger" onClick={(e) => { e.stopPropagation(); onDelete(r.resume_id) }}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="card">
          <h3>简历详情 · {detail.file_name} <span className={`badge ${detail.parse_status}`}>{STATUS_TEXT[detail.parse_status]}</span></h3>
          <div className="field-label">抽取实体（来源：{detail.entities?.[0]?.source || '—'}）</div>
          <div>
            {detail.entities?.length
              ? detail.entities.map((e, i) => (
                <span key={i} className="chip">{FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value}</span>
              ))
              : <span className="muted">（暂无实体）</span>}
          </div>
          <div className="field-label">原文预览</div>
          <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{detail.raw_text || '（无）'}</div>
        </div>
      )}
    </div>
  )
}
