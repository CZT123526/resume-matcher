import { useCallback, useEffect, useRef, useState } from 'react'
import {
  uploadResume, listResumes, deleteResume, resumeFileUrl, searchResumes,
} from '../api'
import ResumeDetailModal from '../components/ResumeDetailModal'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const PAGE_SIZE = 20  // 列表分页：一页 20 份，页面不至于拉太长（用户定）

export default function Resumes() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [corpus, setCorpus] = useState('all')       // 语料筛选：all/business/rewrite/semispec
  const [corpusCounts, setCorpusCounts] = useState(null)
  const [detailId, setDetailId] = useState(null)  // 详情弹窗：只存 id，取数与动作都封装在弹窗组件里
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshedAt, setRefreshedAt] = useState('')
  const [loaded, setLoaded] = useState(false)   // 首载骨架屏开关（T40）
  const [msg, setMsg] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [searchInfo, setSearchInfo] = useState(null) // {q, total}
  const fileRef = useRef(null)

  // 语料筛选切换时 refresh 重建 → 挂载效应自动重拉第 1 页，无需在 onChange 里手动请求
  const refresh = useCallback(async (nextPage = 1) => {
    setRefreshing(true)
    try {
      let d = await listResumes(nextPage, PAGE_SIZE, corpus)
      // 翻到超出总页数的空页（如末页最后一条刚被删）时回退一页
      if (!(d.items || []).length && nextPage > 1) {
        d = await listResumes(nextPage - 1, PAGE_SIZE, corpus)
        nextPage -= 1
      }
      setItems(d.items || [])
      setTotal(d.total || 0)
      setCorpusCounts(d.corpus_counts || null)
      setPage(nextPage)
      setSearchInfo(null)
      setSearchQ('')
      setRefreshedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    } finally {
      setRefreshing(false)
      setLoaded(true)
    }
  }, [corpus])

  useEffect(() => { refresh(1) }, [refresh])

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
          failed.push(`${files[i].name}，${e.message}`)
        }
      }
      setMsg(`已受理 ${okCount}/${files.length} 份，后台解析中，最多 2 路并行`
        + (failed.length ? `；失败：${failed.join('、')}` : ''))
      await refresh()
      setTimeout(() => refresh(), 3000)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const openDetail = (id) => setDetailId(id)

  const openFile = (id) => {
    window.open(resumeFileUrl(id), '_blank')
  }

  const onDelete = async (id) => {
    if (!window.confirm(`确认删除简历 ${id}？`)) return
    try {
      await deleteResume(id)
      setDetailId(null)
      await refresh(page)
    } catch (e) {
      setMsg(`删除失败：${e.message}`)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // T32 起评测种子语料（resume_ 前缀）已整体移出业务库，列表不再分组；
  // 搜索结果与全量列表共用同一张表。

  const renderTable = (rows, isSearch) => (
    <table>
      <thead>
        <tr><th>ID</th><th>文件名</th><th>解析状态</th><th>{isSearch ? '命中片段' : '上传时间'}</th><th>操作</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.resume_id} className="clickable" onClick={() => openDetail(r.resume_id)}>
            <td>{r.resume_id}</td>
            <td>
              <a className="file-link" onClick={(e) => { e.stopPropagation(); openFile(r.resume_id) }}
                title="打开简历原件">{r.file_name}</a>
            </td>
            <td><span className={`badge ${r.parse_status}`}>{STATUS_TEXT[r.parse_status] || r.parse_status}</span></td>
            {isSearch
              ? <td className="muted snippet-cell">{r.snippet || '—'}</td>
              : <td className="muted">{r.created_at}</td>}
            <td>
              <button className="btn danger" onClick={(e) => { e.stopPropagation(); onDelete(r.resume_id) }}>删除</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <div>
      <div className="card">
        <h3 title="支持 PDF / DOCX 格式，单个文件 ≤10MB，可一次选择多份">上传简历</h3>
        <div className="row">
          <input ref={fileRef} type="file" accept=".pdf,.docx" multiple disabled={busy}
            style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files)} />
          <button className="btn" disabled={busy} title="支持 PDF / DOCX，单个 ≤10MB，支持多选"
            onClick={() => fileRef.current?.click()}>
            {busy ? '上传中…' : '选择文件上传'}
          </button>
          <button className="btn ghost" disabled={refreshing} onClick={() => refresh(page)}>
            {refreshing ? '刷新中…' : '刷新列表'}
          </button>
          {refreshedAt && <span className="muted">已刷新 {refreshedAt}</span>}
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>{searchInfo
          ? `搜索「${searchInfo.q}」· 命中 ${searchInfo.total} 份`
          : `简历列表 · 共 ${total} 份`}</h3>
        <div className="row" style={{ marginBottom: 8 }}>
          <input style={{ width: 260 }} placeholder="全文搜索：技能/公司/学校/任意原文片段"
            value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSearch()} />
          <button className="btn ghost" disabled={refreshing} onClick={onSearch}>搜索</button>
          {searchInfo && (
            <button className="btn ghost" onClick={() => refresh(1)}>返回全部</button>
          )}
          {!searchInfo && (
            <select value={corpus} disabled={refreshing} onChange={(e) => setCorpus(e.target.value)}
              title="按批次筛选简历，数字为各类份数">
              <option value="all">全部简历{corpusCounts ? ` · ${corpusCounts.all}` : ''}</option>
              <option value="business">正式简历{corpusCounts ? ` · ${corpusCounts.business}` : ''}</option>
              <option value="rewrite">改写简历{corpusCounts ? ` · ${corpusCounts.rewrite}` : ''}</option>
              <option value="semispec">半规范简历{corpusCounts ? ` · ${corpusCounts.semispec}` : ''}</option>
            </select>
          )}
        </div>
        {!searchInfo && <div className="muted" style={{ marginBottom: 8 }}>点击文件名打开原件 · 点击行查看解析详情</div>}
        {!loaded ? (
          <div>
            {[92, 84, 76, 68, 60].map((w, i) => (
              <div key={i} className="skeleton" style={{ height: 18, width: `${w}%`, marginBottom: 14 }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="empty">{searchInfo ? '没有命中的简历，换个关键词试试' : '还没有简历，先上传一份试试'}</div>
        ) : (
          renderTable(items, !!searchInfo)
        )}
        {!searchInfo && totalPages > 1 && (
          <div className="pager">
            <button className="btn ghost" disabled={page <= 1 || refreshing} onClick={() => refresh(page - 1)}>
              上一页
            </button>
            <span className="pager-jump">
              第
              <select value={page} disabled={refreshing} onChange={(e) => refresh(Number(e.target.value))}>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              / {totalPages} 页
            </span>
            <button className="btn ghost" disabled={page >= totalPages || refreshing} onClick={() => refresh(page + 1)}>
              下一页
            </button>
          </div>
        )}
      </div>

      {detailId != null && (
        <ResumeDetailModal resumeId={detailId} onClose={() => setDetailId(null)} />
      )}
    </div>
  )
}
