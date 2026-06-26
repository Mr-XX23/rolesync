import React, { useState, useEffect } from 'react';
import { Mail, ShieldCheck, ArrowLeft, AlertCircle, CheckCircle2, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { useAppDispatch, useAppSelector } from '../../store';
import { 
  sendPhoneVerification, 
  sendEmailVerification, 
  clearSendPhoneState, 
  clearSendEmailState,
  abortRegistrationFlow,
  setRegistrationStep
} from '../../store/authSlice';
import api from '../../api/axiosInstance';

const VerifyEmail: React.FC = () => {
  const navigate = useNavigate();
  const { tempUser } = useAppSelector((state) => state.auth);
  const registeredEmail = tempUser?.email;
  const registeredPhone = tempUser?.phone;
  const userId = tempUser?.userId;

  const [localError, setLocalError] = useState<string | null>(null);
  const [localSuccess, setLocalSuccess] = useState<string | null>(null);
  const [resendCountdown, setResendCountdown] = useState(0);
  const [isChecking, setIsChecking] = useState(false);

  const dispatch = useAppDispatch();
  const { 
    isSendPhoneLoading, 
    sendPhoneSuccess, 
    sendPhoneError,
    isSendEmailLoading,
    sendEmailSuccess,
    sendEmailError 
  } = useAppSelector((state) => state.auth);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCountdown > 0) {
      const timer = setTimeout(() => setResendCountdown(resendCountdown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [resendCountdown]);

  // Clear states on mount and unmount
  useEffect(() => {
    dispatch(clearSendPhoneState());
    dispatch(clearSendEmailState());
    return () => {
      dispatch(clearSendPhoneState());
      dispatch(clearSendEmailState());
    };
  }, [dispatch]);

  // Subscribe to real-time verification status updates via SSE
  useEffect(() => {
    if (!userId) return;

    const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api/v1';
    const eventSource = new EventSource(`${apiBaseUrl}/auth/verification-events/${userId}`);

    eventSource.addEventListener('connected', (event) => {
      console.log('SSE connection established:', event.data);
    });

    eventSource.addEventListener('email-verified', (event: MessageEvent) => {
      console.log('Email verified event received via SSE:', event.data);
      try {
        const data = JSON.parse(event.data);
        
        setLocalSuccess('Your email has been verified successfully! Triggering phone verification...');
        setLocalError(null);
 
        // Trigger phone OTP sending automatically when email is verified
        setTimeout(() => {
          if (data.hasPhone) {
            dispatch(setRegistrationStep('phone'));
            navigate('/verify-phone');
          } else {
            dispatch(abortRegistrationFlow());
            navigate('/signin');
          }
        }, 1500);
      } catch (err) {
        console.error('Failed to parse SSE email-verified payload:', err);
      }
    });

    eventSource.onerror = (err) => {
      console.error('SSE connection error:', err);
    };

    return () => {
      eventSource.close();
    };
  }, [userId, registeredPhone, navigate]);

  // Handle successful phone verification send -> Redirect to /verify-phone
  useEffect(() => {
    if (sendPhoneSuccess) {
      dispatch(clearSendPhoneState());
      navigate('/verify-phone');
    }
  }, [sendPhoneSuccess, navigate, dispatch]);

  // Handle errors from sending phone verification (indicates email not verified yet)
  useEffect(() => {
    if (sendPhoneError) {
      setLocalError(sendPhoneError);
    }
  }, [sendPhoneError]);

  // Handle email verification resend success
  useEffect(() => {
    if (sendEmailSuccess) {
      setLocalSuccess('Verification email resent successfully! Please check your inbox.');
      setResendCountdown(60);
      dispatch(clearSendEmailState());
    }
  }, [sendEmailSuccess, dispatch]);

  // Handle email verification resend error
  useEffect(() => {
    if (sendEmailError) {
      setLocalError(sendEmailError);
      dispatch(clearSendEmailState());
    }
  }, [sendEmailError]);

  // Dynamic interactive background glow matching other premium auth pages
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const container = document.getElementById('interactive-bg');
      if (container) {
        const x = (e.clientX / window.innerWidth) * 100;
        const y = (e.clientY / window.innerHeight) * 100;
        container.style.backgroundImage = `
          radial-gradient(at ${x}% ${y}%, rgba(222, 187, 174, 0.12) 0px, transparent 50%),
          radial-gradient(at 0% 0%, rgba(222, 187, 174, 0.15) 0px, transparent 50%),
          radial-gradient(at 100% 100%, rgba(113, 91, 58, 0.08) 0px, transparent 50%)
        `;
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
    };
  }, []);

  const handleProceed = async () => {
    setLocalError(null);
    setLocalSuccess(null);

    if (!userId) {
      setLocalError('User identification is missing. Please register again.');
      return;
    }

    setIsChecking(true);
    try {
      // Query backend check user verification status endpoint
      const response = await api.get(`/auth/users/verify/${userId}`);
      const data = response.data;

      if (data.emailVerified) {
        if (registeredPhone) {
          setLocalSuccess('Email verified! Redirecting to phone verification...');
          dispatch(setRegistrationStep('phone'));
          // Dispatch phone verification send in background. If cooldown is active,
          // user already has the code, so we proceed directly without blocking.
          dispatch(sendPhoneVerification({ userId }));
          setTimeout(() => {
            navigate('/verify-phone');
          }, 1000);
        } else {
          setLocalSuccess('Your email has been verified successfully! Redirecting...');
          dispatch(abortRegistrationFlow());
          setTimeout(() => {
            navigate('/signin');
          }, 2000);
        }
      } else {
        setLocalError('Email is not verified yet. Please check your inbox and click the verification link.');
      }
    } catch (err: any) {
      console.error('Error verifying user status:', err);
      setLocalError(err.response?.data?.message || err.message || 'Failed to check verification status.');
    } finally {
      setIsChecking(false);
    }
  };

  const handleResendEmail = () => {
    setLocalError(null);
    setLocalSuccess(null);

    if (!userId) {
      setLocalError('User identification is missing. Please register again.');
      return;
    }

    dispatch(sendEmailVerification({ userId }));
  };

  const displayEmail = registeredEmail || 'your email address';

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-8 px-4 sm:px-6 relative overflow-hidden">
      {/* Decorative Atmospheric Glows */}
      <div className="fixed inset-0 bg-pattern pointer-events-none"></div>
      <div
        id="interactive-bg"
        className="fixed inset-0 pointer-events-none transition-all duration-300 bg-cover bg-no-repeat"
        style={{
          backgroundImage: `
            radial-gradient(at 0% 0%, rgba(222, 187, 174, 0.15) 0px, transparent 50%),
            radial-gradient(at 100% 100%, rgba(113, 91, 58, 0.1) 0px, transparent 50%)
          `,
        }}
      ></div>
      <div className="fixed -top-40 -right-40 w-80 h-80 bg-primary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>
      <div className="fixed -bottom-40 -left-40 w-80 h-80 bg-secondary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>

      <main className="relative z-10 w-full max-w-4xl transition-all duration-700 ease-out">
        <div className="animate-in fade-in duration-500 w-full">
          {/* Split Panel verification container */}
          <div className="bg-card shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-xl overflow-hidden border border-border">
            <div className="grid grid-cols-1 md:grid-cols-2">
              {/* Left Panel: Steps */}
              <div className="bg-muted/15 p-4 md:p-6 lg:p-8 flex flex-col justify-start border-r border-border">
                <h3 className="text-[32px] font-serif font-normal text-foreground mb-3">Verify your identity</h3>
                <p className="text-muted-foreground mb-4 text-base">Follow these steps to activate your workspace profile.</p>

                <div className="space-y-8 text-left">
                  {/* Step 1 */}
                  <div className="flex items-start gap-5">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <Mail className="w-[20px] h-[20px]" />
                    </div>
                    <div>
                      <h4 className="text-lg font-bold text-foreground mb-1">Step 1: Check Your Email</h4>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        We've sent a verification link to your email address. Click the link to verify your email.
                      </p>
                    </div>
                  </div>

                  {/* Step 2 */}
                  <div className="flex items-start gap-5">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <ShieldCheck className="w-[20px] h-[20px]" />
                    </div>
                    <div>
                      <h4 className="text-lg font-bold text-foreground mb-1">
                        {registeredPhone ? 'Step 2: Auto-Redirect to Phone Verify' : 'Step 2: Access Dashboard'}
                      </h4>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {registeredPhone 
                          ? "Once email is verified, you'll be redirected automatically. If not, click 'Proceed' below."
                          : "Once email is verified, you'll be redirected to sign in. If not, click 'Check Status'."}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Panel: Action inputs */}
              <div className="p-4 md:p-6 lg:p-8 flex flex-col justify-center bg-card">
                <h1 className="text-[32px] font-serif font-normal text-foreground mb-4">Email Verification</h1>
                
                <p className="text-muted-foreground mb-4 text-base leading-relaxed text-left">
                  A verification link was sent to <span className="font-semibold text-primary">{displayEmail}</span>.
                </p>

                {/* Error Alert Banner */}
                {localError && (
                  <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-6 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                    <div className="grow text-left">
                      <p className="font-semibold">Email Verification Pending</p>
                      <p className="opacity-90">{localError}</p>
                    </div>
                    <button
                      onClick={() => setLocalError(null)}
                      className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                      aria-label="Clear error banner"
                    >
                      &times;
                    </button>
                  </div>
                )}

                {/* Success Alert Banner */}
                {localSuccess && (
                  <div className="bg-[#10b981]/10 border border-[#10b981]/20 text-[#10b981] text-xs py-2.5 px-3 rounded-lg mb-6 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                    <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-[#10b981]" />
                    <div className="grow text-left">
                      <p className="font-semibold">Success</p>
                      <p className="opacity-90">{localSuccess}</p>
                    </div>
                    <button
                      onClick={() => setLocalSuccess(null)}
                      className="text-[#10b981] hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                      aria-label="Clear success banner"
                    >
                      &times;
                    </button>
                  </div>
                )}

                <div className="space-y-4">
                  {/* Proceed to Phone Verify Button */}
                  {/* Proceed to Phone Verify Button */}
                  <Button
                    onClick={handleProceed}
                    isLoading={isChecking || isSendPhoneLoading}
                    loadingText="Checking status..."
                    className="w-full rounded-lg group"
                    icon={<ArrowRight className="w-[18px] h-[18px] group-hover:translate-x-0.5 transition-transform" />}
                  >
                    {registeredPhone ? 'Proceed to Phone Verification' : 'Check Verification Status'}
                  </Button>

                  {/* Resend Link and countdown */}
                  <div className="text-center pt-4 select-none">
                    <p className="text-muted-foreground text-sm font-normal">
                      Didn't receive the email?{' '}
                      <button
                        onClick={handleResendEmail}
                        disabled={resendCountdown > 0 || isSendEmailLoading}
                        className={`font-bold transition-opacity ${resendCountdown > 0 || isSendEmailLoading
                            ? 'text-muted-foreground/60 cursor-not-allowed'
                            : 'text-primary hover:underline underline-offset-4 cursor-pointer'
                          }`}
                      >
                        {isSendEmailLoading ? 'Sending...' : 'Resend Email'}
                      </button>
                      {resendCountdown > 0 && (
                        <span className="text-xs opacity-60 ml-1">({resendCountdown}s)</span>
                      )}
                    </p>
                  </div>

                  {/* Back to register link */}
                  <div className="text-center mt-6 select-none border-t border-border/40 pt-4">
                    <a
                      className="text-sm font-medium text-muted-foreground hover:text-primary transition-colors flex items-center justify-center gap-2 group cursor-pointer"
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        dispatch(abortRegistrationFlow());
                        navigate('/register');
                      }}
                    >
                      <ArrowLeft className="w-[16px] h-[16px] transition-transform group-hover:-translate-x-1" />
                      Back to Register
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Technical Footer */}
          <div className="mt-8 text-center space-y-3 select-none">
            <p className="font-mono text-[12px] text-muted-foreground/90">
              © {new Date().getFullYear()} RoleSync AI.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
};

export default VerifyEmail;
