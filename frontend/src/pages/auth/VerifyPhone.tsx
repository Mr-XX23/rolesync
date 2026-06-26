import React, { useState, useEffect, useRef } from 'react';
import { Phone, Hash, ShieldCheck, ArrowLeft, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { OtpInput } from '../../components/common/OtpInput';
import { useAppDispatch, useAppSelector } from '../../store';
import { verifyPhone, clearVerifyState, sendPhoneVerification, abortRegistrationFlow } from '../../store/authSlice';

const VerifyPhone: React.FC = () => {
  const navigate = useNavigate();
  const { tempUser } = useAppSelector((state) => state.auth);
  const registeredPhone = tempUser?.phone;
  const userId = tempUser?.userId;
  const [otp, setOtp] = useState<string[]>(Array(6).fill(''));
  const [countdown, setCountdown] = useState(60);
  const [localError, setLocalError] = useState<string | null>(null);

  const dispatch = useAppDispatch();
  const { isVerifyLoading, verifySuccess, verifyError } = useAppSelector(
    (state) => state.auth
  );

  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Clear verification state on mount and unmount
  useEffect(() => {
    dispatch(clearVerifyState());
    return () => {
      dispatch(clearVerifyState());
    };
  }, [dispatch]);

  // Countdown timer logic
  useEffect(() => {
    if (countdown > 0 && !verifySuccess) {
      const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [countdown, verifySuccess]);

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

  // Autofocus the first OTP field on mount
  useEffect(() => {
    if (inputRefs.current[0]) {
      inputRefs.current[0].focus();
    }
  }, []);

  // Handle digit changes with automatic focus shifts
  const handleChange = (value: string, index: number) => {
    // Only allow single numbers
    if (value && !/^\d$/.test(value)) return;

    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);
    setLocalError(null);

    // Focus next input if a number is typed
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  // Handle delete/backspace with focus shifts
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, index: number) => {
    if (e.key === 'Backspace') {
      const newOtp = [...otp];

      // If current field is filled, clear it and stay on it
      if (otp[index]) {
        newOtp[index] = '';
        setOtp(newOtp);
      }
      // If current field is empty, go to previous field and clear it
      else if (index > 0) {
        newOtp[index - 1] = '';
        setOtp(newOtp);
        inputRefs.current[index - 1]?.focus();
      }
    }

    // Left arrow moves focus left
    if (e.key === 'ArrowLeft' && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }

    // Right arrow moves focus right
    if (e.key === 'ArrowRight' && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  // Support copy-paste for full 6-digit codes
  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData('text').trim();

    // Check if pasted value is exactly 6 digits
    if (/^\d{6}$/.test(pastedData)) {
      const digits = pastedData.split('');
      setOtp(digits);
      setLocalError(null);
      // Focus last input field after pasting
      inputRefs.current[5]?.focus();
    }
  };

  const handleSubmit = (e: React.SyntheticEvent) => {
    e.preventDefault();
    setLocalError(null);

    const code = otp.join('');
    if (code.length !== 6) {
      setLocalError('Please enter all 6 digits of the verification code.');
      return;
    }

    if (!userId) {
      setLocalError('User identification is missing. Please register again.');
      return;
    }

    dispatch(verifyPhone({ code, userId }));
  };

  const handleResendCode = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (countdown > 0) return;

    if (!userId) {
      setLocalError('User identification is missing. Please register again.');
      return;
    }

    setOtp(Array(6).fill(''));
    setLocalError(null);
    dispatch(clearVerifyState());
    
    try {
      await dispatch(sendPhoneVerification({ userId })).unwrap();
      setCountdown(60);
      if (inputRefs.current[0]) {
        inputRefs.current[0].focus();
      }
    } catch (err: any) {
      setLocalError(err || 'Failed to resend verification code.');
    }
  };

  const handleGoToSignIn = () => {
    dispatch(clearVerifyState());
    navigate('/signin');
  };

  const displayPhone = registeredPhone || '+1 (555) 000-0000';

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
        {verifySuccess ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 max-w-[500px] mx-auto w-full">
            {/* Successful Phone Verification Card */}
            <div className="bg-card border border-border/80 rounded-xl p-8 md:p-12 shadow-[0_4px_24px_-2px_rgba(0,0,0,0.04),0_2px_8px_-1px_rgba(0,0,0,0.02)] success-glow relative overflow-hidden group flex flex-col items-center text-center w-full">
              <div className="absolute -top-12 -right-12 w-32 h-32 bg-primary-fixed/20 dark:bg-primary-fixed/10 rounded-full blur-3xl group-hover:bg-primary-fixed/30 dark:group-hover:bg-primary-fixed/20 transition-colors duration-500 pointer-events-none"></div>

              {/* Success Badge */}
              <div className="w-20 h-20 bg-primary-fixed/30 dark:bg-[#fcddbf]/20 rounded-full flex items-center justify-center mb-8 transition-transform duration-500 hover:scale-105 select-none">
                <div className="w-14 h-14 bg-primary rounded-full flex items-center justify-center text-primary-foreground shadow-sm">
                  <CheckCircle2 className="w-8 h-8" strokeWidth={1.5} />
                </div>
              </div>

              {/* Success Info */}
              <h2 className="font-serif text-[30px] leading-[38px] text-foreground mb-4 select-none">
                Phone Verified
              </h2>
              <p className="font-sans text-[15px] leading-relaxed text-muted-foreground mb-8">
                Your operator profile is now fully authenticated. Access is granted to the RoleSync AI Synchronization pipeline.
              </p>

              {/* Back to sign in / dashboard */}
              <Button
                variant="primary"
                className="w-full rounded-[12px] py-4 shadow-sm"
                onClick={handleGoToSignIn}
              >
                Proceed to Sign In
              </Button>
            </div>

            {/* Brand Copyright */}
            <div className="mt-8 text-center space-y-3 select-none">
              <p className="font-mono text-[12px] text-muted-foreground/90">
                © {new Date().getFullYear()} RoleSync AI.
              </p>
            </div>
          </div>
        ) : (
          <div className="animate-in fade-in duration-500 w-full">
            {/* Split Panel verification container */}
            <div className="bg-card shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-xl overflow-hidden border border-border">
              <div className="grid grid-cols-1 md:grid-cols-2">
                {/* Left Panel: Steps */}
                <div className="bg-muted/15 p-4 md:p-6 lg:p-8 flex flex-col justify-start border-r border-border">
                  <h3 className="text-[32px] font-serif font-normal text-foreground mb-3">Almost there!</h3>
                  <p className="text-muted-foreground mb-10 text-base">Follow these simple steps to secure your account.</p>

                  <div className="space-y-8 text-left">
                    {/* Step 1 */}
                    <div className="flex items-start gap-5">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <Phone className="w-[20px] h-[20px]" />
                      </div>
                      <div>
                        <h4 className="text-lg font-bold text-foreground mb-1">Step 1: Check Your Phone</h4>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          We've sent a 6-digit SMS verification code to your registered phone number.
                        </p>
                      </div>
                    </div>

                    {/* Step 2 */}
                    <div className="flex items-start gap-5">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <Hash className="w-[20px] h-[20px]" />
                      </div>
                      <div>
                        <h4 className="text-lg font-bold text-foreground mb-1">Step 2: Enter the 6-Digit Code</h4>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          Type the code into the fields on the right.
                        </p>
                      </div>
                    </div>

                    {/* Step 3 */}
                    <div className="flex items-start gap-5">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <ShieldCheck className="w-[20px] h-[20px]" />
                      </div>
                      <div>
                        <h4 className="text-lg font-bold text-foreground mb-1">Step 3: You're All Set!</h4>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          Once verified, you'll get full access to your account.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Right Panel: Action inputs */}
                <div className="p-4 md:p-6 lg:p-8 flex flex-col justify-center bg-card">
                  <h1 className="text-[32px] font-serif font-normal text-foreground mb-4">Verify your phone</h1>
                  <p className="text-muted-foreground mb-10 text-base leading-relaxed text-left">
                    We've sent a SMS verification code to{' '}
                    <span className="font-semibold text-primary dark:text-primary-foreground">{displayPhone}</span>.
                  </p>

                  {/* Error Alert Banner */}
                  {(verifyError || localError) && (
                    <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-6 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      <div className="grow text-left">
                        <p className="font-semibold">Unable to verify phone</p>
                        <p className="opacity-90">{localError || verifyError}</p>
                      </div>
                      <button
                        onClick={() => {
                          setLocalError(null);
                          dispatch(clearVerifyState());
                        }}
                        className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                        aria-label="Clear error banner"
                      >
                        &times;
                      </button>
                    </div>
                  )}

                  <form className="w-full text-left" onSubmit={handleSubmit}>
                    <label className="text-xs font-semibold text-muted-foreground mb-3 block uppercase tracking-wider">
                      Verification Code
                    </label>

                    {/* 6 Digit Inputs */}
                    <div className="flex justify-start py-2">
                      <div className="relative flex w-full max-w-[340px] gap-2 sm:gap-3">
                        {otp.map((digit, index) => (
                          <OtpInput
                            key={index}
                            ref={(el) => { inputRefs.current[index] = el; }}
                            id={`otp-digit-${index}`}
                            type="text"
                            maxLength={1}
                            value={digit}
                            onChange={(e) => handleChange(e.target.value, index)}
                            onKeyDown={(e) => handleKeyDown(e, index)}
                            onPaste={index === 0 ? handlePaste : undefined}
                            className="w-full max-w-[48px] flex-1 min-w-0 h-12 sm:h-14 text-center text-xl font-bold border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all duration-200"
                            aria-label={`Digit ${index + 1}`}
                          />
                        ))}
                      </div>
                    </div>

                    {/* Verify Action Button */}
                    <div className="flex pt-8">
                      <Button
                        type="submit"
                        isLoading={isVerifyLoading}
                        loadingText="Verifying..."
                        className="w-full rounded-lg"
                      >
                        Verify Account
                      </Button>
                    </div>
                  </form>

                  {/* Resend Link and countdown */}
                  <div className="text-center mt-8 select-none">
                    <p className="text-muted-foreground text-sm font-normal">
                      Didn't receive the code?{' '}
                      <button
                        onClick={handleResendCode}
                        disabled={countdown > 0}
                        className={`font-bold transition-opacity ${countdown > 0
                            ? 'text-muted-foreground/60 cursor-not-allowed'
                            : 'text-primary hover:underline underline-offset-4 cursor-pointer'
                          }`}
                      >
                        Resend Code
                      </button>
                      {countdown > 0 && (
                        <span className="text-xs opacity-60 ml-1">({countdown}s)</span>
                      )}
                    </p>
                  </div>

                  {/* Edit phone number link / Back to register */}
                  <div className="text-center mt-6 select-none">
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
                      Use a different phone number
                    </a>
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
        )}
      </main>
    </div>
  );
};

export default VerifyPhone;
