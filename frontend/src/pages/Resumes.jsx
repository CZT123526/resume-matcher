import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadResume, listResumes, getResume, deleteResume, resumeFileUrl } from '../api'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const FIELD_TEXT = {
  name: '姓名', degree: '学历', school: '院校', skill: '技能',
  years: '年限', company: '公司', title: '职位',
}

export default function Resumes() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshedAt, setRefreshedAt] = useState('')
  const [msg, setMsg] = useState('')
  const fileRef = useRef(null)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const data = await listResumes()
      setItems(data.items || [])
      setTotal(data.total || 0)
      setRefreshedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // 批量上传：逐份调用受理接口，失败的单独点名，不打断其余文件
  const onUpload = async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setBusy(true)
    setMsg('')
    let okCount = 0
    const failed = []
    try {
      for (let i = 0; i < files.length; i++) {
        setMsg(`上传中 ${i + 1}/${files.length}：${files[i].name}`)
        try {
          await uploadResume(files[i])
          okCount++
        } catch (e) {
          failed.push(`${files[i].name}（${e.message}）`)
        }
      }
      setMsg(`已受理 ${okCount}/${files.length} 份，后台解析中`
        + (failed.length ? `；失败：${failed.join('、')}` : ''))
      await refresh()
      // 解析异步进行，几秒后再刷一次让状态徽章到位
      setTimeout(refresh, 3000)
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

  const openFile = (id) => {
    window.open(resumeFileUrl(id), '_blank')
  }

  const onDelete = async (id) => {
    if (!window.confirm(`确认删除简历 ${id}？`)) return
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
        <h3>上传简历（PDF / DOCX，≤10MB，支持多选）</h3>
        <div className="row">
          <input ref={fileRef} type="file" accept=".pdf,.docx" multiple disabled={busy}
            style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files)} />
          <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? '上传中…' : '选择文件上传'}
          </button>
          <button className="btn ghost" disabled={refreshing} onClick={refresh}>
            {refreshing ? '刷新中…' : '刷新列表'}
          </button>
          {refreshedAt && <span className="muted">已刷新 {refreshedAt}</span>}
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>简历列表（共 {total} 份）</h3>
        <div className="muted" style={{ marginBottom: 8 }}>点击文件名打开原件 · 点击行查看解析详情</div>
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
                  <td>
                    <a className="file-link" onClick={(e) => { e.stopPropagation(); openFile(r.resume_id) }}
                      title="打开简历原件">{r.file_name}</a>
                  </td>
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
          <h3>
            简历详情 · {detail.file_name}{' '}
            <span className={`badge ${detail.parse_status}`}>{STATUS_TEXT[detail.parse_status]}</span>
            <button className="btn ghost" style={{ marginLeft: 12 }} onClick={() => openFile(detail.resume_id)}>
              查看原件
            </button>
          </h3>
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
