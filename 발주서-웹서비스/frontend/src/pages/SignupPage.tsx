import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GoogleOAuthProvider, useGoogleLogin } from '@react-oauth/google';
import { fetchMe, getOAuthConfig, loginWithGoogle, OAuthConfig, signup } from '../api';
import { useUser } from '../App';

const EMPTY_OAUTH: OAuthConfig = { kakao_client_id: '', google_client_id: '' };

function SignupForm({ oauthCfg }: { oauthCfg: OAuthConfig }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const navigate = useNavigate();
  const { setUser } = useUser();
  const hasGoogle = !!oauthCfg.google_client_id;

  const finishAuth = useCallback(async (accessToken: string) => {
    localStorage.setItem('token', accessToken);
    const me = await fetchMe();
    setUser(me);
    navigate('/my/products');
  }, [navigate, setUser]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);

    if (password !== passwordConfirm) {
      setErr('비밀번호가 일치하지 않습니다.');
      return;
    }
    if (password.length < 8) {
      setErr('비밀번호는 8자 이상이어야 합니다.');
      return;
    }

    setBusy(true);
    try {
      const res = await signup(username.trim(), email.trim().toLowerCase(), password);
      await finishAuth(res.access_token);
    } catch (e: any) {
      setErr(e?.message || '가입 실패');
    } finally {
      setBusy(false);
    }
  }

  const googleSignup = useGoogleLogin({
    onSuccess: async (res) => {
      try {
        const data = await loginWithGoogle(res.access_token);
        await finishAuth(data.access_token);
      } catch (e: any) {
        setErr(e?.message || '구글 가입에 실패했습니다.');
        setGoogleBusy(false);
      }
    },
    onError: () => {
      setErr('구글 가입이 취소되었습니다.');
      setGoogleBusy(false);
    },
    onNonOAuthError: () => setGoogleBusy(false),
  });

  const handleGoogleSignup = () => {
    setErr(null);
    setGoogleBusy(true);
    googleSignup();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm p-8">
        <h1 className="text-2xl font-bold text-slate-900 mb-2">회원가입</h1>
        <p className="text-sm text-slate-500 mb-6">
          가입 후 상품·옵션·거래처 양식을 등록하면 내 업무에 맞는 발주 자동화를 바로 만들 수 있습니다.
        </p>

        {hasGoogle && (
          <>
            <button
              type="button"
              onClick={handleGoogleSignup}
              disabled={busy || googleBusy}
              className="mb-5 flex w-full items-center justify-center gap-2.5 rounded-xl border border-gray-300 bg-white py-2.5 text-sm font-semibold text-gray-700 shadow-sm transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {googleBusy ? <Spinner /> : <GoogleIcon />}
              구글 계정으로 가입
            </button>
            <div className="mb-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-slate-200" />
              <span className="text-xs text-slate-400">또는</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>
          </>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">아이디</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              maxLength={32}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">이메일</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">비밀번호 (8자 이상)</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">비밀번호 확인</label>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              required
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {err && <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">{err}</div>}

          <button
            type="submit"
            disabled={busy || googleBusy}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2.5 rounded-lg transition"
          >
            {busy ? '가입 중…' : '가입하기'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-slate-500">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="text-indigo-600 hover:underline font-medium">로그인</Link>
        </div>
      </div>
    </div>
  );
}

export default function SignupPage() {
  const [oauthCfg, setOauthCfg] = useState<OAuthConfig>(EMPTY_OAUTH);

  useEffect(() => {
    getOAuthConfig()
      .then(setOauthCfg)
      .catch(() => { /* OAuth keys not configured */ });
  }, []);

  return (
    <GoogleOAuthProvider clientId={oauthCfg.google_client_id || 'placeholder'}>
      <SignupForm oauthCfg={oauthCfg} />
    </GoogleOAuthProvider>
  );
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin text-gray-500" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4" />
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853" />
      <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05" />
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335" />
    </svg>
  );
}
