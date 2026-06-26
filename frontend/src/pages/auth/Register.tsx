import React, { useState, useEffect } from 'react';
import { User, Mail, Eye, EyeOff, CheckCircle2, Circle, AlertCircle, Phone, ArrowRight, UserRoundKey } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useAppDispatch, useAppSelector } from '../../store';
import { registerUser, clearRegisterState, abortRegistrationFlow } from '../../store/authSlice';

const Register: React.FC = () => {
  const navigate = useNavigate();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState('Sales');
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const dispatch = useAppDispatch();
  const { isRegisterLoading, registerSuccess, registerError } = useAppSelector(
    (state) => state.auth
  );

  // Redirect to correct verification page after successful registration
  useEffect(() => {
    if (registerSuccess) {
      navigate('/verify-email');
      dispatch(clearRegisterState());
    }
  }, [registerSuccess, navigate, dispatch]);

  // Clear state on mount and unmount
  useEffect(() => {
    dispatch(clearRegisterState());
    dispatch(abortRegistrationFlow()); // Clear any previous registration flow state
    return () => {
      dispatch(clearRegisterState());
    };
  }, [dispatch]);

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

  // Compute password validation rules dynamically
  const hasLength = password.length >= 12;
  const hasUpper = /[A-Z]/.test(password);
  const hasNumber = /[0-9]/.test(password);
  const hasSpecial = /[!@#$%^&*(),.?":{}|<>]/.test(password);

  let strengthScore = 0;
  if (password.length > 0) {
    if (hasLength) strengthScore += 1;
    if (hasUpper) strengthScore += 1;
    if (hasNumber) strengthScore += 1;
    if (hasSpecial) strengthScore += 1;
  }

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
    if (password.length > 0 && strengthScore < 4) {
      setLocalError('Please satisfy all password security requirements.');
      return;
    }

    if (!agreeTerms) {
      setLocalError('You must agree to the Terms and Conditions.');
      return;
    }

    dispatch(
      registerUser({
        fullName,
        email,
        password,
        phone: phone || undefined,
        role,
      })
    );
  };

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

      <main className="relative z-10 w-full max-w-xl transition-all duration-700 ease-out">
        <div className="animate-in fade-in duration-500">
          {/* Brand Header */}
          <div className="flex flex-col items-center mb-6 text-center animate-in slide-in-from-top-2 duration-500">
            <h1 className="font-serif text-[32px] font-bold text-foreground mb-2">
              Create your account
            </h1>
            <p className="text-muted-foreground text-sm">
              Already have an account?{' '}
              <a
                className="text-primary font-semibold hover:underline transition-all cursor-pointer"
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  navigate('/signin');
                }}
              >
                Sign in
              </a>
            </p>
          </div>

          {/* Register Card */}
          <div className="bg-card rounded-[12px] border border-border p-4 md:p-6 lg:p-8 shadow-[0_4px_6px_-1px_rgba(0,0,0,0.05),0_2px_4px_-2px_rgba(0,0,0,0.05),0_20px_25px_-5px_rgba(0,0,0,0.02)]">
            {/* Error Banner */}
            {(registerError || localError) && (
              <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2.5 px-3 rounded-lg mb-4 flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="grow text-left">
                  <p className="font-semibold">Unable to register</p>
                  <p className="opacity-90">{localError || registerError}</p>
                </div>
                <button
                  onClick={() => {
                    setLocalError(null);
                    dispatch(clearRegisterState());
                  }}
                  className="text-destructive hover:opacity-80 font-bold ml-1 cursor-pointer select-none focus:outline-none"
                  aria-label="Clear error banner"
                >
                  &times;
                </button>
              </div>
            )}

            <form className="space-y-4 text-left" onSubmit={handleSubmit}>
              {/* Full Name */}
              <Input
                label="Full Name"
                id="fullName"
                type="text"
                placeholder="Enter your full name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                leftElement={<User className="w-[16px] h-[16px]" />}
                required
              />

              {/* Email Address */}
              <Input
                label="Email Address"
                id="email"
                type="email"
                placeholder="name@company.com"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                leftElement={<Mail className="w-[16px] h-[16px]" />}
                required
              />

              {/* Password Input & Strength Tracker */}
              <div className="space-y-1.5">
                <Input
                  label="Password"
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Min. 12 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
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

                {/* Real-time Strength Meter */}
                {password.length > 0 && (
                  <div className="space-y-1.5 py-1">
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] font-mono font-medium tracking-wider text-muted-foreground">PASSWORD STRENGTH</span>
                      <span className={`text-[10px] font-mono font-semibold uppercase ${strengthScore > 0
                          ? (strengthScore === 1
                            ? 'text-destructive'
                            : strengthScore === 2
                              ? 'text-foreground/75'
                              : strengthScore === 3
                                ? 'text-[#1d4ed8]'
                                : 'text-primary')
                          : 'text-muted-foreground'
                        }`}>
                        {strengthLabel}
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
                )}

                {/* Checklist */}
                <div className="bg-muted/30 dark:bg-muted/10 rounded-lg p-3 space-y-2 border border-border/40">
                  <p className="text-[10px] font-mono font-medium tracking-wider text-muted-foreground">SECURITY CHECKLIST</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                    <div className={`flex items-center gap-2 transition-colors duration-300 ${hasLength ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                      {hasLength ? (
                        <CheckCircle2 className="w-[14px] h-[14px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[14px] h-[14px] text-muted-foreground" />
                      )}
                      <span>At least 12 characters</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors duration-300 ${hasUpper ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                      {hasUpper ? (
                        <CheckCircle2 className="w-[14px] h-[14px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[14px] h-[14px] text-muted-foreground" />
                      )}
                      <span>1 uppercase letter</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors duration-300 ${hasNumber ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                      {hasNumber ? (
                        <CheckCircle2 className="w-[14px] h-[14px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[14px] h-[14px] text-muted-foreground" />
                      )}
                      <span>1 number</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors duration-300 ${hasSpecial ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                      {hasSpecial ? (
                        <CheckCircle2 className="w-[14px] h-[14px] text-primary fill-primary/10" />
                      ) : (
                        <Circle className="w-[14px] h-[14px] text-muted-foreground" />
                      )}
                      <span>1 special character</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Phone & Role Select Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Phone Input */}
                <Input
                  label="Phone (Optional)"
                  id="phone"
                  type="tel"
                  placeholder="+15550000000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  leftElement={<Phone className="w-[16px] h-[16px]" />}
                />

                {/* Role Dropdown */}
                <div className="space-y-1.5 text-left">
                  <label htmlFor="role" className="text-sm font-medium text-foreground block">
                    I am...
                  </label>
                  <div className="relative flex items-center">
                    <select
                      id="role"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      className="w-full py-2.5 px-4 bg-card rounded-lg border border-border text-foreground transition-all duration-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary cursor-pointer appearance-none"
                    >
                      <option value="Sales">Sales</option>
                      <option value="Teacher">Teacher</option>
                      <option value="Student">Student</option>
                      <option value="Other">Other Profession</option>
                    </select>
                    <div className="absolute right-4 pointer-events-none text-muted-foreground/60 flex items-center">
                      <span className="border-l-[5px] border-r-[5px] border-t-[5px] border-transparent border-t-current w-0 h-0 inline-block align-middle"></span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Consent Checkbox */}
              <div className="flex items-start sm:items-center gap-3 py-1">
                <input
                  id="terms"
                  type="checkbox"
                  checked={agreeTerms}
                  onChange={(e) => setAgreeTerms(e.target.checked)}
                  className="mt-0.5 sm:mt-0 w-4 h-4 rounded border-border text-primary accent-primary focus:ring-primary/20 transition-all cursor-pointer bg-card"
                  required
                />
                <label htmlFor="terms" className="text-xs text-muted-foreground select-none cursor-pointer">
                  I agree to the{' '}
                  <a href="#" className="text-primary underline underline-offset-2 font-medium hover:opacity-85 transition-opacity" onClick={(e) => e.preventDefault()}>
                    Terms and Conditions
                  </a>{' '}
                  and{' '}
                  <a href="#" className="text-primary underline underline-offset-2 font-medium hover:opacity-85 transition-opacity" onClick={(e) => e.preventDefault()}>
                    Privacy Policy
                  </a>.
                </label>
              </div>

              {/* Submit Action Button */}
              <Button
                type="submit"
                isLoading={isRegisterLoading}
                loadingText="Creating account..."
                icon={<ArrowRight className="w-[18px] h-[18px] group-hover:translate-x-0.5 transition-transform" />}
                className="mt-2 group"
              >
                Create Account
              </Button>
            </form>

            {/* Divider */}
            <div className="relative my-6 flex items-center">
              <div className="grow border-t border-border"></div>
              <span className="shrink mx-4 text-[10px] font-mono uppercase tracking-widest text-muted-foreground bg-card px-2 select-none">
                OR CONTINUE WITH
              </span>
              <div className="grow border-t border-border"></div>
            </div>

            {/* Social Logins */}
            <div className="grid grid-cols-2 gap-4">
              <Button
                variant="outline"
                onClick={() => alert('Google Register clicked')}
                className="py-2.5"
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
                onClick={() => alert('Facebook Register clicked')}
                className="py-2.5"
              >
                <svg className="w-4 h-4" fill="#1877F2" viewBox="0 0 24 24">
                  <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"></path>
                </svg>
                Facebook
              </Button>
            </div>
          </div>
        </div>

        {/* Brand Copyright */}
        <div className="mt-8 text-center space-y-3 select-none">
          <p className="font-mono text-[12px] text-muted-foreground/90">
            © {new Date().getFullYear()} RoleSync AI.
          </p>
        </div>
      </main>
    </div>
  );
};

export default Register;
