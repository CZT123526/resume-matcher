import { useCallback, useEffect, useRef, useState } from 'react'
import {
  uploadResume, listResumes, getResume, deleteResume, resumeFileUrl,
  searchResumes, reparseResume, getResumeData,
} from '../api'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const FIELD_TEXT = {
  name: '姓名', degree: '学历', school: '院校', skill: '技能',
  years: '年限', company: '公司', title: '职位',
}

export default function Resumes() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [detail, setDetail] = useState(null)
  const [data, setData] = useState(null)        // 解析数据视图（API-16）
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshedAt, setRefreshedAt] = useState('')
  const [msg, setMsg] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [searchInfo, setSearchInfo] = useState(null) // {q, total}
  const fileRef = useRef(null)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const d = await listResumes()
      setItems(d.items || [])
      setTotal(d.total || 0)
      setSearchInfo(null)
      setSearchQ('')
      setRefreshedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const onSearch = async () => {
    const q = searchQ.trim()
    if (!q) { await refresh(); return }
    setRefreshing(true)
    try {
      const d = await searchResumes(q)
      setItems(d.items || [])
      setSearchInfo({ q, total: d.total || 0 })
    } catch (e) {
      setMsg(`搜索失败：${e.message}`)
    } finally {
      setRefreshing(false)
    }
  }

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
      setMsg(`已受理 ${okCount}/${files.length} 份，后台解析中（最多 2 路并行）`
        + (failed.length ? `；失败：${failed.join('、')}` : ''))
      await refresh()
      setTimeout(refresh, 3000)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const openDetail = async (id) => {
    setDetail(null)
    setData(null)
    try {
      setDetail(await getResume(id))
    } catch (e) {
      setMsg(`详情失败：${e.message}`)
    }
  }

  const openData = async (id) => {
    setData(null)
    try {
      setData(await getResumeData(id))
    } catch (e) {
      setMsg(`数据视图失败：${e.message}`)
    }
  }

  const onReparse = async (id) => {
    try {
      await reparseResume(id)
      setMsg('已重新排队解析')
      await openDetail(id)
      setTimeout(() => openDetail(id), 3000)
    } catch (e) {
      setMsg(`重解析失败：${e.message}`)
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
      setData(null)
      await refresh()
    } catch (e) {
      setMsg(`删除失败：${e.message}`)
    }
  }

  const q = detail?.quality || {}
  const lowQuality = detail?.parse_status === 'done' && (!q.like_resume || q.entity_count === 0)

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
        <h3>{searchInfo ? `搜索「${searchInfo.q}」· 命中 ${searchInfo.total} 份` : `简历列表（共 ${total} 份）`}</h3>
        <div className="row" style={{ marginBottom: 8 }}>
          <input style={{ width: 260 }} placeholder="全文搜索：技能/公司/学校/任意原文片段"
            value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSearch()} />
          <button className="btn ghost" disabled={refreshing} onClick={onSearch}>搜索</button>
          {searchInfo && (
            <button className="btn ghost" onClick={refresh}>返回全部</button>
          )}
        </div>
        {!searchInfo && <div className="muted" style={{ marginBottom: 8 }}>点击文件名打开原件 · 点击行查看解析详情</div>}
        {items.length === 0 ? (
          <div className="empty">{searchInfo ? '没有命中的简历，换个关键词试试' : '还没有简历，先上传一份试试'}</div>
        ) : (
          <table>
            <thead>
              <tr><th>ID</th><th>文件名</th><th>解析状态</th><th>{searchInfo ? '命中片段' : '上传时间'}</th><th>操作</th></tr>
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
                  {searchInfo
                    ? <td className="muted snippet-cell">{r.snippet || '—'}</td>
                    : <td className="muted">{r.created_at}</td>}
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
            <button className="btn ghost" style={{ marginLeft: 12 }} onClick={() => openFile(detail.resume_id)}>查看原件</button>
            <button className="btn ghost" style={{ marginLeft: 8 }} onClick={() => openData(detail.resume_id)}>查看解析数据</button>
            <button className="btn ghost" style={{ marginLeft: 8 }} onClick={() => onReparse(detail.resume_id)}>重新解析</button>
          </h3>
          {detail.parse_status === 'failed' && (
            <div className="error-text">解析失败：{detail.parse_error || '未知原因'}</div>
          )}
          {lowQuality && (
            <div className="warn-text">解析质量提示：正文 {q.text_chars} 字、实体 {q.entity_count} 条
              {q.like_resume ? '' : '，且内容不像简历'}——可能是扫描件/图片型文件，建议重新解析或换文件</div>
          )}
          <div className="field-label">抽取实体（来源：{detail.entities?.[0]?.source || '—'}）</div>
          <div>
            {detail.entities?.length
              ? detail.entities.map((e, i) => (
                <span key={i} className="chip">{FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value}</span>
              ))
              : <span className="muted">（暂无实体）</span>}
          </div>
          <div className="field-label">原文预览（前 500 字）</div>
          <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{detail.raw_text || '（无）'}</div>
        </div>
      )}

      {data && (
        <div className="card">
          <h3>解析数据 · {data.file_name}</h3>
          <div className="row">
            <span className="chip">正文 {data.stats.text_chars} 字</span>
            <span className="chip">实体 {data.stats.entity_count} 条</span>
            <span className="chip ok">BERT {data.stats.bert_count}</span>
            <span className="chip unknown">规则 {data.stats.rule_count}</span>
            <span className="chip">向量 {data.matching.vector_dim} 维</span>
            <span className="chip">模长 {data.matching.vector_norm}</span>
          </div>
          <div className="field-label">匹配输入（structured_text，语义编码真正的对象）</div>
          <div className="mono-text">{data.matching.structured_text}</div>
          <div className="field-label">向量预览（前 8 维 / 共 {data.matching.vector_dim} 维）</div>
          <div className="mono-text">[{data.matching.vector_preview.join(', ')}]</div>
          <div className="field-label">实体明细（含来源）</div>
          {data.entities.length
            ? data.entities.map((e, i) => (
              <span key={i} className={`chip ${e.source === 'bert' ? 'ok' : 'unknown'}`}>
                {FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value} · {e.source}
              </span>
            ))
            : <span className="muted">（暂无实体）</span>}
          <div className="field-label">解析全文（{data.stats.text_chars} 字）</div>
          <details>
            <summary className="muted" style={{ cursor: 'pointer' }}>展开/收起全文</summary>
            <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{data.raw_text}</div>
          </details>
        </div>
      )}
    </div>
  )
}
