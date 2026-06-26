import React, { useState } from 'react';
import { ArrowRight, LogOut, Home, Mail, MessageCircle, UserRoundKey, Sparkles, AlertCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useAppDispatch, useAppSelector } from '../../store';
import { loginUser, logout, clearError } from '../../store/authSlice';

const Signin: React.FC = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const dispatch = useAppDispatch();
  const { isLoading: isSubmitting, error, isAuthenticated, user } = useAppSelector(
    (state) => state.auth
  );

  React.useEffect(() => {
    if (isAuthenticated && user) {
      navigate('/select-role', { replace: true });
    }
  }, [isAuthenticated, user, navigate]);

  const handleSubmit = (e: React.SyntheticEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    dispatch(loginUser({ email, password }));
  };

  const handleLogout = () => {
    dispatch(logout());
    setEmail('');
    setPassword('');
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-8 px-4 sm:px-6">
      <main className="w-full max-w-xl transition-all duration-700 ease-out">

        {/* Conditional Render: Authenticated Dashboard vs Sign In Form */}
        {isAuthenticated && user ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 text-center">
            {/* Header */}
            <div className="flex flex-col items-center mb-8">
              <div className="relative mb-3">
                <div className="bg-primary/10 p-3 rounded-full relative">
                  <Sparkles className="w-8 h-8 text-primary" />
                </div>
                <span className="absolute bottom-0 right-0 w-3 h-3 bg-green-500 border-2 border-background rounded-full animate-pulse"></span>
              </div>
              <h2 className="text-[28px] leading-tight font-bold mb-2 font-serif text-foreground">
                Active Session Detected
              </h2>
              <p className="text-muted-foreground text-sm max-w-[300px]">
                You are already logged in. Access granted to synchronization pipeline.
              </p>
            </div>

            {/* Dashboard Card */}
            <div className="bg-card rounded-lg border border-border p-4 md:p-6 lg:p-8 shadow-sm text-left space-y-4">

              {/* User Session Info */}
              <div className="bg-background/60 border border-border/50 rounded-lg p-4 space-y-1">
                <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Active operator</span>
                <p className="text-sm font-medium font-mono text-foreground break-all">{user.email}</p>
              </div>

              {/* Message */}
              <div className="space-y-4">
                <div className="flex items-center gap-3 text-sm">
                  <MessageCircle className="w-5 h-5 text-gray-500 shrink-0" />
                  <div>
                    <p className="font-medium text-foreground">If you want to switch accounts, Please logout from here.</p>
                  </div>
                </div>
              </div>

              {/* Logout Button */}
              <div className="flex gap-2 items-center w-full">
                <Button
                  variant="primary"
                  className="w-full flex items-center justify-center gap-2"
                  onClick={handleLogout}
                  icon={<LogOut className="w-[16px] h-[16px]" />}
                >
                  Logout
                </Button>
                <Button
                  variant="outline"
                  className="w-full flex items-center justify-center gap-2"
                  onClick={() => navigate('/select-role')}
                  icon={<Home className="w-[16px] h-[16px]" />}
                >
                  Home
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="animate-in fade-in duration-500">
            {/* RoleSync Logo Header */}
            <div className="flex flex-col items-center mb-4 md:mb-6 lg:mb-8 text-center">
              <h2 className="text-[28px] leading-tight font-bold mb-2 font-serif text-foreground">
                Sign in to RoleSync AI
              </h2>
              <p className="text-muted-foreground text-sm max-w-[300px]">
                Access your enterprise AI synchronization engine.
              </p>
            </div>

            {/* Authentication Card */}
            <div className="bg-card rounded-lg border border-border p-4 md:p-6 lg:p-8 shadow-sm">

              {/* Redux State Error Alert Banner */}
              {error && (
                <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-4 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  <div className="grow">
                    <p className="font-semibold">Authentication Error</p>
                    <p className="opacity-90">{error}</p>
                  </div>
                  <button
                    onClick={() => dispatch(clearError())}
                    className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                    aria-label="Clear error banner"
                  >
                    &times;
                  </button>
                </div>
              )}

              <form className="space-y-4" onSubmit={handleSubmit}>
                {/* Work Email */}
                <Input
                  label="Work Email"
                  id="email"
                  type="email"
                  placeholder="name@company.com"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  leftElement={<Mail className="w-[16px] h-[16px]" />}
                  required
                />

                {/* Password */}
                <Input
                  label="Password"
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  leftElement={<UserRoundKey className="w-[16px] h-[16px]" />}
                  required
                  rightElement={
                    <a
                      className="text-primary text-xs font-semibold hover:underline transition-all cursor-pointer"
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        navigate('/forgot-password');
                      }}
                    >
                      Forgot password?
                    </a>
                  }
                />

                {/* Submit Button */}
                <Button
                  type="submit"
                  isLoading={isSubmitting}
                  loadingText="Authenticating..."
                  icon={<ArrowRight className="w-[18px] h-[18px]" />}
                  className="mt-2"
                >
                  Sign In
                </Button>
              </form>

              {/* Divider */}
              <div className="relative my-8 flex items-center">
                <div className="grow border-t border-border"></div>
                <span className="shrink mx-4 text-[10px] font-mono uppercase tracking-widest text-muted-foreground bg-card px-2 select-none">
                  or continue with
                </span>
                <div className="grow border-t border-border"></div>
              </div>

              {/* Social Providers */}
              <div className="grid grid-cols-2 gap-4 mb-8">
                <Button
                  variant="outline"
                  onClick={() => alert('Google auth clicked')}
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    <path
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                      fill="#4285F4"
                    ></path>
                    <path
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      fill="#34A853"
                    ></path>
                    <path
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"
                      fill="#FBBC05"
                    ></path>
                    <path
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      fill="#EA4335"
                    ></path>
                  </svg>
                  Google
                </Button>
                <Button
                  variant="outline"
                  onClick={() => alert('Facebook auth clicked')}
                >
                  <svg className="w-4 h-4" fill="#1877F2" viewBox="0 0 24 24">
                    <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"></path>
                  </svg>
                  Facebook
                </Button>
              </div>

              {/* Register Prompt */}
              <div className="pt-6 border-t border-border text-center">
                <p className="text-sm text-muted-foreground">
                  Don't have an account?{' '}
                  <a
                    className="text-primary font-semibold hover:underline transition-all cursor-pointer"
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      navigate('/register');
                    }}
                  >
                    Register
                  </a>
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Technical Footnote */}
        <div className="mt-8 text-center space-y-3 select-none">
          <p className="font-mono text-[12px] text-muted-foreground/90">
            © {new Date().getFullYear()} RoleSync AI.
          </p>
        </div>

      </main>
    </div>
  );
};

export default Signin;
