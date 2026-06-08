import { useState, useEffect, FormEvent } from 'react';
import { isAuthDisabled, useUser } from '../App';
import {
  fetchUsers, createUser, toggleUserActive,
  fetchBlockedIPs, blockIP, unblockIP,
  UserInfo, BlockedIP,
} from '../api';

function AdminPanel() {
  const { user } = useUser();
  const canAccess = isAuthDisabled() || user?.role === 'admin';
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [blockedIPs, setBlockedIPs] = useState<BlockedIP[]>([]);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('12345');
  const [newIP, setNewIP] = useState('');
  const [ipReason, setIpReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'users' | 'ips'>('users');

  useEffect(() => {
    if (canAccess) {
      loadData();
    }
  }, [canAccess]);

  const loadData = async () => {
    try {
      const [u, b] = await Promise.all([fetchUsers(), fetchBlockedIPs()]);
      setUsers(u.users);
      setBlockedIPs(b.blocked_ips);
    } catch {
      setError('데이터 로드 실패');
    }
  };

  if (!canAccess) {
    return (
      <div className="p-8 text-center text-gray-500">
        관리자만 접근할 수 있습니다.
      </div>
    );
  }

  const handleCreateUser = async (e: FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim()) return;
    setLoading(true);
    setError('');
    try {
      await createUser(newUsername, newPassword);
      setNewUsername('');
      setNewPassword('12345');
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '생성 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (userId: number) => {
    try {
      await toggleUserActive(userId);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '변경 실패');
    }
  };

  const handleBlockIP = async (e: FormEvent) => {
    e.preventDefault();
    if (!newIP.trim()) return;
    setLoading(true);
    try {
      await blockIP(newIP, undefined, ipReason);
      setNewIP('');
      setIpReason('');
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '차단 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleUnblock = async (id: number) => {
    try {
      await unblockIP(id);
      await loadData();
    } catch {
      setError('해제 실패');
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">사용자 관리</h1>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setTab('users')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === 'users' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          사용자 ({users.length})
        </button>
        <button
          onClick={() => setTab('ips')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === 'ips' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          IP 차단 ({blockedIPs.length})
        </button>
      </div>

      {tab === 'users' && (
        <>
          {/* Create User Form */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-bold text-gray-700 mb-4">새 사용자 추가</h3>
            <form onSubmit={handleCreateUser} className="flex gap-3 items-end">
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">아이디</label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="아이디"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">초기 비밀번호</label>
                <input
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="12345"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                추가
              </button>
            </form>
          </div>

          {/* Users Table */}
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">ID</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">아이디</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">역할</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">상태</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">생성일</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600">관리</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b last:border-0 hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-500">{u.id}</td>
                    <td className="px-4 py-3 font-medium">{u.username}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        u.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                      }`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                      }`}>
                        {u.is_active ? '활성' : '비활성'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {u.created_at?.slice(0, 10)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {u.role !== 'admin' && (
                        <button
                          onClick={() => handleToggle(u.id)}
                          className={`px-3 py-1 rounded-lg text-xs font-medium ${
                            u.is_active
                              ? 'bg-red-50 text-red-600 hover:bg-red-100'
                              : 'bg-green-50 text-green-600 hover:bg-green-100'
                          }`}
                        >
                          {u.is_active ? '비활성화' : '활성화'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'ips' && (
        <>
          {/* Block IP Form */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-bold text-gray-700 mb-4">IP 차단</h3>
            <form onSubmit={handleBlockIP} className="flex gap-3 items-end">
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">IP 주소</label>
                <input
                  type="text"
                  value={newIP}
                  onChange={(e) => setNewIP(e.target.value)}
                  placeholder="123.456.789.0"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">사유</label>
                <input
                  type="text"
                  value={ipReason}
                  onChange={(e) => setIpReason(e.target.value)}
                  placeholder="차단 사유"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
              >
                차단
              </button>
            </form>
          </div>

          {/* Blocked IPs Table */}
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            {blockedIPs.length === 0 ? (
              <div className="p-8 text-center text-gray-400 text-sm">차단된 IP가 없습니다.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">IP 주소</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">사유</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">차단일</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">관리</th>
                  </tr>
                </thead>
                <tbody>
                  {blockedIPs.map((b) => (
                    <tr key={b.id} className="border-b last:border-0 hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono">{b.ip_address}</td>
                      <td className="px-4 py-3 text-gray-500">{b.reason || '-'}</td>
                      <td className="px-4 py-3 text-gray-500">{b.created_at?.slice(0, 10)}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleUnblock(b.id)}
                          className="px-3 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-200"
                        >
                          해제
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default AdminPanel;
