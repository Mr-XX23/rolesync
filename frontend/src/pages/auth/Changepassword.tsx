import React, { useState, useEffect } from 'react';
import { Eye, EyeOff, CheckCircle2, Circle, ArrowLeft, AlertCircle, Shield, UserRoundKey } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useAppDispatch, useAppSelector } from '../../store';
import { updatePassword, clearUpdateState } from '../../store/authSlice';

const Changepassword: React.FC = () => {
  const navigate = useNavigate();
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const dispatch = useAppDispatch();
  const { isUpdateLoading, updateSuccess, updateError } = useAppSelector(
    (state) => state.auth
  );

  // Clear state on mount and unmount
  useEffect(() => {
    dispatch(clearUpdateState());
    return () => {
      dispatch(clearUpdateState());
    };
  }, [dispatch]);

  // Subtle mouse tracking for background glow
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

  // Compute password validation rules dynamically on render
  const hasLength = newPassword.length >= 12;
  const hasCase = /[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword);
  const hasSymbols = /[0-9]/.test(newPassword) && /[^A-Za-z0-9]/.test(newPassword);

  // Strength score from 0 to 4
  let strengthScore = 0;
  if (newPassword.length > 0) strengthScore += 1;
  if (hasLength) strengthScore += 1;
  if (hasCase) strengthScore += 1;
  if (hasSymbols) strengthScore += 1;

  // Get labels and colors for strength levels
  const getStrengthMeta = () => {
    switch (strengthScore) {
      case 1:
        return { label: 'Weak', colorClass: 'bg-destructive' };
      case 2:
        return { label: 'Fair', colorClass: 'bg-[#4b342a]/70 dark:bg-[#ffe0c2]/60' };
      case 3:
        return { label: 'Good', colorClass: 'bg-[#1d4ed8]' };
      case 4:
        return { label: 'Strong', colorClass: 'bg-[#644a40] dark:bg-[#ffe0c2]' };
      default:
        return { label: 'Weak', colorClass: 'bg-muted' };
    }
  };

  const { label: strengthLabel, colorClass: strengthColorClass } = getStrengthMeta();

  const handleSubmit = (e: React.SyntheticEvent) => {
    e.preventDefault();
    setLocalError(null);

    // Validate strength requirements
    if (strengthScore < 4) {
      setLocalError('Please satisfy all password strength requirements.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setLocalError('Passwords do not match.');
      return;
    }

    dispatch(updatePassword(newPassword));
  };

  const handleBackToSignIn = () => {
    dispatch(clearUpdateState());
    navigate('/signin');
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-8 px-4 sm:px-6 relative overflow-hidden">
      {/* Atmospheric Background Decoration */}
      <div className="fixed inset-0 bg-pattern pointer-events-none"></div>
      <div id="interactive-bg" className="fixed inset-0 pointer-events-none transition-all duration-300 bg-cover bg-no-repeat" style={{
        backgroundImage: `
          radial-gradient(at 0% 0%, rgba(222, 187, 174, 0.15) 0px, transparent 50%),
          radial-gradient(at 100% 100%, rgba(113, 91, 58, 0.1) 0px, transparent 50%)
        `
      }}></div>
      <div className="fixed -top-40 -right-40 w-80 h-80 bg-primary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>
      <div className="fixed -bottom-40 -left-40 w-80 h-80 bg-secondary-fixed opacity-20 blur-[100px] rounded-full pointer-events-none"></div>

      <main className="relative z-10 w-full max-w-[480px] transition-all duration-700 ease-out">
        {updateSuccess ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
            {/* Confirmation Card */}
            <div className="bg-card border border-border/80 rounded-xl p-8 md:p-12 shadow-[0_4px_24px_-2px_rgba(0,0,0,0.04),0_2px_8px_-1px_rgba(0,0,0,0.02)] success-glow relative overflow-hidden group flex flex-col items-center text-center w-full">
              {/* Subtle Decorative Element */}
              <div className="absolute -top-12 -right-12 w-32 h-32 bg-primary-fixed/20 dark:bg-primary-fixed/10 rounded-full blur-3xl group-hover:bg-primary-fixed/30 dark:group-hover:bg-primary-fixed/20 transition-colors duration-500 pointer-events-none"></div>

              {/* Success Icon Indicator */}
              <div className="w-20 h-20 bg-primary-fixed/30 dark:bg-[#fcddbf]/20 rounded-full flex items-center justify-center mb-8 transition-transform duration-500 hover:scale-105 select-none">
                <div className="w-14 h-14 bg-primary rounded-full flex items-center justify-center text-primary-foreground shadow-sm">
                  <CheckCircle2 className="w-8 h-8" strokeWidth={1.5} />
                </div>
              </div>

              {/* Content */}
              <h2 className="font-serif text-[30px] leading-[38px] text-foreground mb-4 select-none">
                Password Updated
              </h2>
              <p className="font-sans text-[16px] leading-relaxed text-muted-foreground mb-8 max-w-[280px]">
                Your password has been successfully reset. You can now use your new password to sign in to your account.
              </p>

              {/* Primary Action */}
              <Button
                variant="primary"
                className="w-full rounded-[12px] py-4 shadow-sm"
                onClick={handleBackToSignIn}
              >
                Back to Sign In
              </Button>

              {/* Security Note */}
              <div className="mt-8 flex items-center gap-2 text-muted-foreground/60 select-none">
                <Shield className="w-4 h-4" />
                <span className="font-mono text-[10px] tracking-wider uppercase">Secure Session Verified</span>
              </div>
            </div>

            {/* Footer Alternative (Subtle Links) */}
            <div className="mt-8 flex justify-center gap-4 text-xs select-none">
              <a href="#" className="text-muted-foreground hover:text-primary transition-colors cursor-pointer" onClick={(e) => e.preventDefault()}>Help Center</a>
              <span className="text-border">•</span>
              <a href="#" className="text-muted-foreground hover:text-primary transition-colors cursor-pointer" onClick={(e) => e.preventDefault()}>Terms of Service</a>
            </div>
          </div>
        ) : (
          <div className="animate-in fade-in duration-500">
            {/* Header */}
            <div className="flex flex-col items-center mb-4 md:mb-6 lg:mb-8 text-center animate-in slide-in-from-top-2 duration-500">
              <h2 className="text-[28px] leading-tight font-bold mb-2 font-serif text-foreground">
                Set New Password
              </h2>
              <p className="text-muted-foreground text-sm max-w-[300px]">
                Ensure your account stays secure with a strong password.
              </p>
            </div>

            {/* Form Card */}
            <div className="bg-card rounded-[12px] border border-border p-4 md:p-6 lg:p-8 shadow-[0_4px_6px_-1px_rgba(0,0,0,0.05),0_2px_4px_-2px_rgba(0,0,0,0.05),0_20px_25px_-5px_rgba(0,0,0,0.02)]">
              {/* Error Banner */}
              {(updateError || localError) && (
                <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-4 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  <div className="grow text-left">
                    <p className="font-semibold">Unable to set password</p>
                    <p className="opacity-90">{localError || updateError}</p>
                  </div>
                  <button
                    onClick={() => {
                      setLocalError(null);
                      dispatch(clearUpdateState());
                    }}
                    className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                    aria-label="Clear error banner"
                  >
                    &times;
                  </button>
                </div>
              )}

              <form className="space-y-4 text-left" onSubmit={handleSubmit}>
                {/* New Password */}
                <Input
                  label="NEW PASSWORD"
                  id="new-password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="••••••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  leftElement={<UserRoundKey className="w-[16px] h-[16px]" />}
                  required
                  rightElementInside={
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer focus:outline-none flex items-center justify-center"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      {showPassword ? (
                        <EyeOff className="w-[16px] h-[16px]" />
                      ) : (
                        <Eye className="w-[16px] h-[16px]" />
                      )}
                    </button>
                  }
                />

                {/* Strength Meter */}
                <div className="space-y-1.5 py-1">
                  <div className="flex justify-between items-center">
                    <span className="text-[10px] font-mono font-medium tracking-wider text-muted-foreground">PASSWORD STRENGTH</span>
                    <span className={`text-[10px] font-mono font-semibold uppercase ${strengthScore > 0 ? (strengthScore === 1 ? 'text-destructive' : strengthScore === 2 ? 'text-foreground/75' : strengthScore === 3 ? 'text-[#1d4ed8]' : 'text-primary') : 'text-muted-foreground'
                      }`}>
                      {newPassword.length > 0 ? strengthLabel : 'Empty'}
                    </span>
                  </div>
                  <div className="flex gap-1 h-1.5 w-full">
                    {[0, 1, 2, 3].map((index) => (
                      <div
                        key={index}
                        className={`h-full flex-1 rounded-full transition-all duration-300 ${index < strengthScore ? strengthColorClass : 'bg-muted'
                          }`}
                      ></div>
                    ))}
                  </div>
                </div>

                {/* Requirements */}
                <div className="bg-muted/30 dark:bg-muted/10 rounded-lg p-3 space-y-2 border border-border/40">
                  <ul className="space-y-2 text-xs">
                    <li className={`flex items-center gap-2 transition-colors duration-300 ${hasLength ? 'text-primary font-medium' : 'text-muted-foreground'
                      }`}>
                      {hasLength ? (
                        <CheckCircle2 className="w-[16px] h-[16px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[16px] h-[16px] text-muted-foreground" />
                      )}
                      <span>At least 12 characters</span>
                    </li>
                    <li className={`flex items-center gap-2 transition-colors duration-300 ${hasCase ? 'text-primary font-medium' : 'text-muted-foreground'
                      }`}>
                      {hasCase ? (
                        <CheckCircle2 className="w-[16px] h-[16px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[16px] h-[16px] text-muted-foreground" />
                      )}
                      <span>Mixed case letters (Aa)</span>
                    </li>
                    <li className={`flex items-center gap-2 transition-colors duration-300 ${hasSymbols ? 'text-primary font-medium' : 'text-muted-foreground'
                      }`}>
                      {hasSymbols ? (
                        <CheckCircle2 className="w-[16px] h-[16px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[16px] h-[16px] text-muted-foreground" />
                      )}
                      <span>Numbers and symbols</span>
                    </li>
                  </ul>
                </div>

                {/* Confirm Password */}
                <Input
                  label="CONFIRM NEW PASSWORD"
                  id="confirm-password"
                  type="password"
                  placeholder="••••••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  leftElement={<UserRoundKey className="w-[16px] h-[16px]" />}
                  required
                />

                {/* Submit button */}
                <Button
                  type="submit"
                  isLoading={isUpdateLoading}
                  loadingText="Updating..."
                  icon={<CheckCircle2 className="w-[18px] h-[18px]" />}
                  className="mt-4"
                >
                  Update Password
                </Button>
              </form>

              {/* Navigation Back */}
              <div className="mt-6 pt-6 border-t border-border text-center">
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

export default Changepassword;
