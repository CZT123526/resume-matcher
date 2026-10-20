import { useCallback, useEffect, useRef, useState } from 'react'
import {
  uploadResume, listResumes, getResume, deleteResume, resumeFileUrl,
  searchResumes, reparseResume, getResumeData, getJdRecommendations,
} from '../api'

const STATUS_TEXT = { pending: '排队中', processing: '解析中', done: '已完成', failed: '失败' }
const PAGE_SIZE = 50  // 列表分页：后端单页上限 500，前端取 50 条一页，防止长列表拖卡
const FIELD_TEXT = {
  name: '姓名', degree: '学历', school: '院校', skill: '技能',
  years: '年限', company: '公司', title: '职位',
}

export default function Resumes() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [corpus, setCorpus] = useState('all')       // 语料筛选：all/business/rewrite/semispec
  const [corpusCounts, setCorpusCounts] = useState(null)
  const [detail, setDetail] = useState(null)
  const [data, setData] = useState(null)        // 解析数据视图（API-16）
  const [recs, setRecs] = useState(null)        // 反向推荐（API-17，T39）
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

  const openDetail = async (id) => {
    setDetail(null)
    setData(null)
    setRecs(null)
    try {
      setDetail(await getResume(id))
    } catch (e) {
      setMsg(`详情失败：${e.message}`)
    }
  }

  // 反向推荐（T39）：done 简历可一键看 Top-3 岗位（校准融合分 + 证据链）
  const openRecs = async (id) => {
    setRecs({ loading: true })
    try {
      const d = await getJdRecommendations(id, 3)
      setRecs({ loading: false, items: d.items })
    } catch (e) {
      setRecs({ loading: false, error: e.message })
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
      await refresh(page)
    } catch (e) {
      setMsg(`删除失败：${e.message}`)
    }
  }

  // 详情/解析数据用弹窗展示（T30）：× 或点遮罩或 Esc 关闭
  const closeModal = () => { setDetail(null); setData(null); setRecs(null) }
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') closeModal() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const q = detail?.quality || {}
  const lowQuality = detail?.parse_status === 'done' && (!q.like_resume || q.entity_count === 0)
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
              title="按语料批次筛选列表；数字为各类份数">
              <option value="all">全部语料{corpusCounts ? ` · ${corpusCounts.all}` : ''}</option>
              <option value="business">正式语料{corpusCounts ? ` · ${corpusCounts.business}` : ''}</option>
              <option value="rewrite">改写考卷{corpusCounts ? ` · ${corpusCounts.rewrite}` : ''}</option>
              <option value="semispec">半规范考卷{corpusCounts ? ` · ${corpusCounts.semispec}` : ''}</option>
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

      {detail && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>
                简历详情 · {detail.file_name}{' '}
                <span className={`badge ${detail.parse_status}`}>{STATUS_TEXT[detail.parse_status]}</span>
              </h3>
              <button className="modal-close" title="关闭 · Esc" onClick={closeModal}>×</button>
            </div>
            <div className="modal-body">
            <div className="row" style={{ marginBottom: 10 }}>
              <button className="btn ghost" onClick={() => openFile(detail.resume_id)}>查看原件</button>
              <button className="btn ghost" onClick={() => openData(detail.resume_id)}>查看解析数据</button>
              <button className="btn ghost" onClick={() => onReparse(detail.resume_id)}>重新解析</button>
              {detail.parse_status === 'done' && (
                <button className="btn ghost" onClick={() => openRecs(detail.resume_id)}>推荐岗位</button>
              )}
            </div>
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
            {detail.parse_status === 'failed' && (
              <div className="error-text">解析失败：{detail.parse_error || '未知原因'}</div>
            )}
            {lowQuality && (
              <div className="warn-text">解析质量提示：正文 {q.text_chars} 字、实体 {q.entity_count} 条
                {q.like_resume ? '' : '，且内容不像简历'}——可能是扫描件/图片型文件，建议重新解析或换文件</div>
            )}
            <div className="field-label">抽取实体 · 来源 {detail.entities?.[0]?.source || '—'}</div>
            <div>
              {detail.entities?.length
                ? detail.entities.map((e, i) => (
                  <span key={i} className="chip">{FIELD_TEXT[e.field_key] || e.field_key}：{e.field_value}</span>
                ))
                : <span className="muted">暂无实体</span>}
            </div>
            <div className="field-label">简历原文 · 全文 {detail.quality?.text_chars ?? (detail.raw_text || '').length} 字，弹窗内可滚动</div>
            <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{detail.raw_text || '无'}</div>
            </div>
          </div>
        </div>
      )}

      {data && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>解析数据 · {data.file_name}</h3>
              <button className="btn ghost" onClick={() => setData(null)}>返回详情</button>
              <button className="modal-close" title="关闭 · Esc" onClick={closeModal}>×</button>
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
    </div>
  )
}
