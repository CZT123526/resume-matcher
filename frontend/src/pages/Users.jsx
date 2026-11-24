import { useCallback, useEffect, useState } from 'react'
import { createUser, deleteUser, listUsers, resetUserPassword } from '../api'

// T56 账号管理（API-23，仅管理员）：建号/删号/重置密码；改自己的密码在侧边栏底部
// me 由 App 传入（登录响应或 /auth/me），未载入时先渲染占位防 null 闪崩
export default function Users({ me }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('hr')
  const [resetTarget, setResetTarget] = useState(null) // 用户名字符串，非 null 即弹重置窗
  const [newPassword, setNewPassword] = useState('')
  const [resetBusy, setResetBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const data = await listUsers()
      setItems(data.items || [])
      setTotal(data.total || 0)
    } catch (e) {
      setMsg(`加载失败：${e.message}`)
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const closeModal = () => { setResetTarget(null); setNewPassword('') }
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') closeModal() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onCreate = async () => {
    if (!username.trim() || !password) {
      setMsg('用户名和初始密码都要填')
      return
    }
    if (password.length < 6) {
      setMsg('初始密码至少 6 位')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const data = await createUser(username.trim(), password, role)
      setMsg(`已创建账号 ${data.username}，角色 ${data.role === 'admin' ? '管理员' : '普通用户'}`)
      setUsername('')
      setPassword('')
      setRole('hr')
      await refresh()
    } catch (e) {
      setMsg(`创建失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (u) => {
    if (!window.confirm(`确认删除用户「${u}」？该用户的登录会话将全部失效。`)) return
    try {
      const d = await deleteUser(u)
      setMsg(`已删除用户 ${u}，其 ${d.deleted_sessions} 个登录会话已下线`)
      await refresh()
    } catch (e) {
      setMsg(`删除失败：${e.message}`)
    }
  }

  const onResetSubmit = async () => {
    if (!resetTarget || !newPassword) return
    if (newPassword.length < 6) {
      setMsg('新密码至少 6 位')
      return
    }
    setResetBusy(true)
    setMsg('')
    try {
      await resetUserPassword(resetTarget, newPassword)
      setMsg(`已重置 ${resetTarget} 的密码，该用户需用新密码重新登录`)
      closeModal()
    } catch (e) {
      setMsg(`重置失败：${e.message}`)
    } finally {
      setResetBusy(false)
    }
  }

  if (!me) return <div className="card empty">身份加载中…</div>
  if (me.role !== 'admin') return <div className="card error-text">仅管理员可访问账号管理页</div>

  return (
    <div>
      <div className="card">
        <h3>新建账号</h3>
        <div className="row">
          <div style={{ flex: 1 }}>
            <div className="field-label">用户名</div>
            <input style={{ width: '100%' }} value={username} maxLength={32}
              placeholder="2~32 位，字母数字下划线点连字符，兼容中文"
              onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div style={{ flex: 1 }}>
            <div className="field-label">初始密码</div>
            <input style={{ width: '100%' }} value={password} maxLength={128} type="password"
              placeholder="至少 6 位，建议组合字母数字" onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div>
            <div className="field-label">角色</div>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="hr">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={busy} onClick={onCreate}>{busy ? '创建中…' : '创建账号'}</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </div>

      <div className="card">
        <h3>账号列表 · 共 {total} 个</h3>
        {!loaded ? (
          <div>
            {[88, 76, 64].map((w, i) => (
              <div key={i} className="skeleton" style={{ height: 18, width: `${w}%`, marginBottom: 14 }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="empty">还没有账号，先创建一个</div>
        ) : (
          <table>
            <thead>
              <tr><th>用户名</th><th>角色</th><th>创建时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const self = me && u.username === me.username
                return (
                  <tr key={u.username}>
                    <td>{u.username}</td>
                    <td>
                      {u.role === 'admin'
                        ? <span className="chip ok">管理员</span>
                        : <span className="chip">普通用户</span>}
                    </td>
                    <td className="muted">{u.created_at}</td>
                    <td>
                      {self ? (
                        <span className="muted">当前登录账号，改密请用左下角修改密码</span>
                      ) : (
                        <span className="row">
                          <button className="btn ghost btn-xs" onClick={() => { setResetTarget(u.username); setNewPassword('') }}>
                            重置密码
                          </button>
                          <button className="btn danger btn-xs" onClick={() => onDelete(u.username)}>
                            删除
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
          建号、删号、重置密码都会记入访问审计；删号与重置会让目标用户的登录会话全部失效
        </div>
      </div>

      {resetTarget && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>重置密码 · {resetTarget}</h3>
              <button className="modal-close" title="关闭（Esc）" onClick={closeModal}>×</button>
            </div>
            <div className="modal-body">
              <div className="field-label">新密码</div>
              <input style={{ width: '100%' }} value={newPassword} maxLength={128} type="password"
                placeholder="至少 6 位" onChange={(e) => setNewPassword(e.target.value)} />
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={resetBusy} onClick={onResetSubmit}>
                  {resetBusy ? '重置中…' : '确认重置'}
                </button>
                <span className="muted">重置后该用户的登录会话全部失效</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
