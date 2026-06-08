import React, { useState, useEffect } from 'react';
import { Mail, ArrowRight, ArrowLeft, AlertCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useAppDispatch, useAppSelector } from '../../store';
import { resetPassword, clearResetState } from '../../store/authSlice';

const Passwordreset: React.FC = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent'>('idle');

  const dispatch = useAppDispatch();
  const { isResetLoading, resetSuccess, resetError } = useAppSelector(
    (state) => state.auth
  );

  // Clear password reset state when page is mounted or unmounted
  useEffect(() => {
    dispatch(clearResetState());
    return () => {
      dispatch(clearResetState());
    };
  }, [dispatch]);

  // Handle local resend visual state feedback matching EmailSent.html flow
  useEffect(() => {
    if (isResetLoading) {
      setResendStatus('sending');
    } else if (resendStatus === 'sending' && resetSuccess) {
      setResendStatus('sent');
      const timer = setTimeout(() => {
        setResendStatus('idle');
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [isResetLoading, resetSuccess, resendStatus]);

  const handleSubmit = (e: React.SyntheticEvent) => {
    e.preventDefault();
    if (!email) return;
    dispatch(resetPassword({ email }));
  };

  const handleBackToSignIn = () => {
    dispatch(clearResetState());
    navigate('/signin');
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-8 px-4 sm:px-6 relative overflow-hidden">
      {/* Atmospheric Background Decoration */}
      <div className="fixed inset-0 bg-pattern pointer-events-none"></div>
      <div className="fixed -top-40 -right-40 w-80 h-80 bg-primary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>
      <div className="fixed -bottom-40 -left-40 w-80 h-80 bg-secondary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>

      <main className="relative z-10 w-full max-w-[480px] transition-all duration-700 ease-out">
        {/* Identity Logo Section */}
        <div className="flex justify-center mb-8"></div>

        {resetSuccess ? (
          <div className="animate-in fade-in duration-500">
            {/* Confirmation Card */}
            <div className="bg-card border border-border/80 rounded-[12px] shadow-[0_10px_30px_-10px_rgba(75,52,42,0.08),0_4px_10px_-5px_rgba(75,52,42,0.04)] p-4 md:p-6 lg:p-8 flex flex-col items-center text-center w-full">

              {/* Content */}
              <h1 className="font-serif text-[30px] leading-[38px] text-foreground font-normal mb-4 animate-in slide-in-from-top-2 duration-500">
                Check Your Email
              </h1>
              <p className="text-base text-muted-foreground max-w-[320px] mb-4">
                We've sent a password reset link to <br /><span className="font-bold text-foreground break-all">{email}</span>.<br /> Please check your inbox and follow the instructions.
              </p>

              {/* Actions */}
              <div className="w-full flex flex-col gap-4">
                <Button
                  variant="primary"
                  className="btn-hover w-full rounded-[12px] py-3.5 flex items-center justify-center cursor-pointer transition-all duration-200 active:scale-[0.98]"
                  onClick={handleBackToSignIn}
                >
                  Return to Sign In
                </Button>

                <div className="pt-4 flex flex-col gap-2">
                  <p className="text-sm text-muted-foreground">
                    Didn't receive the email?
                  </p>
                  <button
                    onClick={() => dispatch(resetPassword({ email }))}
                    disabled={isResetLoading || resendStatus === 'sending' || resendStatus === 'sent'}
                    className={`font-semibold text-sm hover:opacity-85 underline decoration-primary/30 underline-offset-4 transition-colors cursor-pointer disabled:opacity-75 ${resendStatus === 'sent' ? 'text-[#1d4ed8] font-bold' : 'text-[#644a40]'
                      }`}
                  >
                    {resendStatus === 'sending' && 'Sending...'}
                    {resendStatus === 'sent' && 'Link resent!'}
                    {resendStatus === 'idle' && 'Resend password link'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="animate-in fade-in duration-500">
            {/* Header */}
            <div className="flex flex-col items-center mb-4 md:mb-6 lg:mb-8 text-center animate-in slide-in-from-top-2 duration-500">
              <h2 className="text-[28px] leading-tight font-bold mb-2 font-serif text-foreground">
                Forgot Password?
              </h2>
              <p className="text-muted-foreground text-sm max-w-[300px]">
                Enter your email address and we'll send you a link to reset your password.
              </p>
            </div>

            {/* Form Card */}
            <div className="bg-card rounded-[12px] border border-border p-4 md:p-6 lg:p-8 shadow-[0_4px_6px_-1px_rgba(0,0,0,0.05),0_2px_4px_-2px_rgba(0,0,0,0.05),0_20px_25px_-5px_rgba(0,0,0,0.02)]">

              {/* Error Banner */}
              {resetError && (
                <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-4 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  <div className="grow text-left">
                    <p className="font-semibold">Reset Password Error</p>
                    <p className="opacity-90">{resetError}</p>
                  </div>
                  <button
                    onClick={() => dispatch(clearResetState())}
                    className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                    aria-label="Clear error banner"
                  >
                    &times;
                  </button>
                </div>
              )}

              <form className="space-y-4 text-left" onSubmit={handleSubmit}>
                <Input
                  label="Your current email"
                  id="email"
                  type="email"
                  placeholder="name@company.com"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  leftElement={<Mail className="w-[16px] h-[16px]" />}
                  required
                />

                <Button
                  type="submit"
                  isLoading={isResetLoading}
                  loadingText="Processing..."
                  icon={<ArrowRight className="w-[18px] h-[18px] group-hover:translate-x-0.5 transition-transform" />}
                  className="mt-2 group animate-in duration-300"
                >
                  Send Reset Link
                </Button>
              </form>

              {/* Navigation Back */}
              <div className="mt-8 pt-6 border-t border-border text-center">
                <a
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-primary transition-colors duration-200 group"
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    handleBackToSignIn();
                  }}
                >
                  <ArrowLeft className="w-[16px] h-[16px] group-hover:-translate-x-0.5 transition-transform" />
                  Back to Sign In
                </a>
              </div>

            </div>
          </div>
        )}

        {/* Footer info */}
        <div className="mt-8 text-center space-y-3 select-none">
          <p className="font-mono text-[12px] text-muted-foreground/90">
            © {new Date().getFullYear()} RoleSync AI.
          </p>
        </div>

      </main>
    </div>
  );
};

export default Passwordreset;
