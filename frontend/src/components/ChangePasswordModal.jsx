import { useEffect, useState } from 'react'
import { changePassword } from '../api'

// 修改自己的密码（T56）：所有登录用户可用，入口在侧边栏底部
// 成功后当前会话保留不跳转；该用户其他浏览器的登录会话全部失效
export default function ChangePasswordModal({ onClose }) {
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const onSubmit = async () => {
    if (!oldPw || !newPw) {
      setMsg('当前密码和新密码都要填')
      return
    }
    if (newPw.length < 6) {
      setMsg('新密码至少 6 位')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      await changePassword(oldPw, newPw)
      setDone(true)
    } catch (e) {
      setMsg(e.message)  // 旧密码不正确等业务拒绝原样展示，注意不是 401 不会触发登出
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>修改密码</h3>
          <button className="modal-close" title="关闭（Esc）" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {done ? (
            <div>
              <div className="warn-text">密码已修改，其他登录会话已下线，当前登录保持不变</div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={onClose}>好的</button>
              </div>
            </div>
          ) : (
            <div>
              <div className="field-label">当前密码</div>
              <input style={{ width: '100%' }} value={oldPw} maxLength={128} type="password"
                autoComplete="current-password"
                onChange={(e) => setOldPw(e.target.value)} />
              <div className="field-label">新密码</div>
              <input style={{ width: '100%' }} value={newPw} maxLength={128} type="password"
                placeholder="至少 6 位" autoComplete="new-password"
                onChange={(e) => setNewPw(e.target.value)} />
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={busy} onClick={onSubmit}>
                  {busy ? '提交中…' : '确认修改'}
                </button>
                {msg && <span className="error-text">{msg}</span>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
