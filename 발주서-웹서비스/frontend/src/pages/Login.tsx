import { useState, FormEvent, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GoogleOAuthProvider, useGoogleLogin } from '@react-oauth/google';
import { login, fetchMe, loginWithKakao, loginWithGoogle, getOAuthConfig, OAuthConfig } from '../api';
import { useUser } from '../App';

/* ── Kakao SDK type shim ─────────────────────────────────────────────────── */
declare global {
  interface Window {
    Kakao?: {
      isInitialized: () => boolean;
      init: (key: string) => void;
      Auth: {
        login: (opts: {
          success: (res: { access_token: string }) => void;
          fail: (err: unknown) => void;
          scope?: string;
        }) => void;
      };
    };
  }
}

/* ── Helper: handle successful OAuth token → store + navigate ─────────── */
function useOAuthSuccess() {
  const navigate = useNavigate();
  const { setUser } = useUser();
  return useCallback(async (accessToken: string) => {
    localStorage.setItem('token', accessToken);
    const me = await fetchMe();
    setUser(me);
    navigate('/');
  }, [navigate, setUser]);
}

/* ── Inner login form ────────────────────────────────────────────────────── */
function LoginForm({ oauthCfg }: { oauthCfg: OAuthConfig }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [socialLoading, setSocialLoading] = useState<'kakao' | 'google' | null>(null);
  const navigate = useNavigate();
  const { setUser } = useUser();
  const onOAuthSuccess = useOAuthSuccess();

  const hasKakao = !!oauthCfg.kakao_client_id;
  const hasGoogle = !!oauthCfg.google_client_id;
  const hasSocial = hasKakao || hasGoogle;

  /* Kakao SDK init on mount */
  useEffect(() => {
    if (hasKakao && window.Kakao && !window.Kakao.isInitialized()) {
      window.Kakao.init(oauthCfg.kakao_client_id);
    }
  }, [hasKakao, oauthCfg.kakao_client_id]);

  /* ── Email/password ─────────────────────────────────────────────────── */
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('아이디와 비밀번호를 입력해주세요.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const data = await login(username, password);
      localStorage.setItem('token', data.access_token);
      const me = await fetchMe();
      setUser(me);
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  /* ── Kakao ──────────────────────────────────────────────────────────── */
  const handleKakaoLogin = () => {
    if (!window.Kakao?.Auth) {
      setError('카카오 SDK가 로드되지 않았습니다. 잠시 후 다시 시도해주세요.');
      return;
    }
    setSocialLoading('kakao');
    setError('');
    window.Kakao.Auth.login({
      success: async ({ access_token }) => {
        try {
          const data = await loginWithKakao(access_token);
          await onOAuthSuccess(data.access_token);
        } catch (err) {
          setError(err instanceof Error ? err.message : '카카오 로그인 실패');
          setSocialLoading(null);
        }
      },
      fail: () => {
        setError('카카오 로그인이 취소되었습니다.');
        setSocialLoading(null);
      },
    });
  };

  /* ── Google ─────────────────────────────────────────────────────────── */
  const googleLogin = useGoogleLogin({
    onSuccess: async (res) => {
      try {
        // useGoogleLogin returns access_token; send it for userinfo lookup
        const data = await loginWithGoogle(res.access_token);
        await onOAuthSuccess(data.access_token);
      } catch (err) {
        setError(err instanceof Error ? err.message : '구글 로그인 실패');
        setSocialLoading(null);
      }
    },
    onError: () => {
      setError('구글 로그인이 취소되었습니다.');
      setSocialLoading(null);
    },
    onNonOAuthError: () => setSocialLoading(null),
  });

  const handleGoogleLogin = () => {
    setSocialLoading('google');
    setError('');
    googleLogin();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-100 via-white to-blue-100 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-indigo-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg shadow-indigo-200">
            <span className="text-white font-bold text-xl">RJ</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">RJ Systems</h1>
          <p className="text-gray-500 mt-1">발주서 관리</p>
        </div>

        <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-8">
          <h2 className="text-lg font-bold text-gray-900 mb-1">로그인</h2>
          <p className="text-sm text-gray-500 mb-5">아이디와 비밀번호를 입력해주세요</p>

          {/* ── Social Buttons ─────────────────────────────────────────── */}
          {hasSocial && (
            <div className="flex flex-col gap-2 mb-5">
              {hasKakao && (
                <button
                  type="button"
                  onClick={handleKakaoLogin}
                  disabled={!!socialLoading || loading}
                  className="w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl
                             bg-[#FEE500] text-[#3C1E1E] text-sm font-semibold
                             hover:bg-[#F5DC00] active:bg-[#EDD300]
                             disabled:opacity-60 disabled:cursor-not-allowed transition-all"
                >
                  {socialLoading === 'kakao' ? <Spinner className="text-[#3C1E1E]" /> : <KakaoIcon />}
                  카카오로 시작하기
                </button>
              )}

              {hasGoogle && (
                <button
                  type="button"
                  onClick={handleGoogleLogin}
                  disabled={!!socialLoading || loading}
                  className="w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl
                             bg-white border border-gray-300 text-gray-700 text-sm font-semibold
                             hover:bg-gray-50 active:bg-gray-100
                             disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-sm"
                >
                  {socialLoading === 'google' ? <Spinner className="text-gray-500" /> : <GoogleIcon />}
                  구글로 시작하기
                </button>
              )}
            </div>
          )}

          {/* Divider */}
          {hasSocial && (
            <div className="flex items-center gap-3 mb-5">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="text-xs text-gray-400">또는</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
          )}

          {/* ── Email / Password ──────────────────────────────────────── */}
          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1.5">
                아이디
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => { setUsername(e.target.value); setError(''); }}
                placeholder="아이디를 입력하세요"
                className="w-full px-4 py-3 border border-gray-300 rounded-xl text-sm
                           focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500
                           outline-none transition-all placeholder:text-gray-400"
                autoFocus
              />
            </div>

            <div className="mb-4">
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">
                비밀번호
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(''); }}
                  placeholder="비밀번호를 입력하세요"
                  className="w-full px-4 py-3 border border-gray-300 rounded-xl text-sm
                             focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500
                             outline-none transition-all placeholder:text-gray-400"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl">
                <p className="text-sm text-red-600 font-medium">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !!socialLoading}
              className="w-full bg-indigo-600 text-white py-3 rounded-xl font-semibold text-sm
                         hover:bg-indigo-700 active:bg-indigo-800
                         focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
                         disabled:opacity-60 disabled:cursor-not-allowed
                         transition-all duration-200 flex items-center justify-center gap-2"
            >
              {loading ? <><Spinner className="text-white" />로그인 중...</> : '로그인'}
            </button>
          </form>

          <div className="mt-6 text-center text-sm text-slate-500">
            계정이 없으신가요?{' '}
            <Link to="/signup" className="text-indigo-600 hover:underline font-medium">가입하기</Link>
          </div>
          <div className="mt-2 text-center text-xs text-slate-400">
            <Link to="/pricing" className="hover:underline">요금제 보기</Link>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Root: fetch OAuth config, then render with GoogleOAuthProvider ──────── */
const EMPTY_OAUTH: OAuthConfig = { kakao_client_id: '', google_client_id: '' };

function Login() {
  const [oauthCfg, setOauthCfg] = useState<OAuthConfig>(EMPTY_OAUTH);

  useEffect(() => {
    getOAuthConfig()
      .then(setOauthCfg)
      .catch(() => { /* OAuth keys not configured — silently skip social buttons */ });
  }, []);

  return (
    <GoogleOAuthProvider clientId={oauthCfg.google_client_id || 'placeholder'}>
      <LoginForm oauthCfg={oauthCfg} />
    </GoogleOAuthProvider>
  );
}

export default Login;

/* ── SVG Icons & Spinner ─────────────────────────────────────────────────── */
function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg className={`animate-spin w-4 h-4 ${className}`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function KakaoIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd"
        d="M9 1C4.58 1 1 3.91 1 7.5c0 2.28 1.44 4.28 3.6 5.46l-.74 2.74a.3.3 0 00.44.33L7.9 13.9A9.4 9.4 0 009 14c4.42 0 8-2.91 8-6.5S13.42 1 9 1z"
        fill="#3C1E1E" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
      <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
    </svg>
  );
}
