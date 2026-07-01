import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, User, Settings, Check, ArrowRight, Sun, Moon, Monitor } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../../store';
import { updateProfile, updateOnboarding } from '../../store/workspaceSlice';
import { useTheme } from '../../components/ThemeProvider';

export const OnboardingWizard: React.FC = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { user } = useAppSelector((state) => state.auth);
  const { onboarding, profile, preferences, isLoading } = useAppSelector((state) => state.workspace);
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    if (onboarding && onboarding.isCompleted) {
      navigate('/select-role', { replace: true });
    }
  }, [onboarding, navigate]);

  const [step, setStep] = useState(1);
  const [firstName, setFirstName] = useState(profile?.firstName || '');
  const [lastName, setLastName] = useState(profile?.lastName || '');
  const [jobTitle, setJobTitle] = useState(profile?.jobTitle || 'Member');
  const [lang, setLang] = useState(preferences?.language || 'en');

  useEffect(() => {
    if (profile) {
      if (!firstName) setFirstName(profile.firstName || '');
      if (!lastName) setLastName(profile.lastName || '');
      if (profile.jobTitle && jobTitle === 'Member') setJobTitle(profile.jobTitle);
    }
  }, [profile]);

  const handleStep1Submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!firstName.trim() || !lastName.trim()) return;

    if (user?.userId) {
      dispatch(updateProfile({
        authUserId: user.userId,
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        jobTitle: jobTitle.trim(),
      })).then(() => {
        dispatch(updateOnboarding({ currentStep: 'PREFERENCES_SETUP', completedSteps: ['PROFILE_SETUP'] }));
        setStep(2);
      });
    }
  };

  const handleStep2Submit = (e: React.FormEvent) => {
    e.preventDefault();
    dispatch(updateOnboarding({ currentStep: 'CONFIRMATION', completedSteps: ['PROFILE_SETUP', 'PREFERENCES_SETUP'] }));
    setStep(3);
  };

  const handleComplete = () => {
    dispatch(updateOnboarding({ currentStep: 'COMPLETE', completedSteps: ['PROFILE_SETUP', 'PREFERENCES_SETUP', 'CONFIRMATION'], isCompleted: true }))
      .then(() => {
        navigate('/select-role', { replace: true });
      });
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-12 px-4 sm:px-6 relative overflow-hidden font-sans">
      {/* Background blurs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl -z-10 animate-pulse duration-5000"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary/15 rounded-full blur-3xl -z-10 animate-pulse duration-7000"></div>

      <div className="w-full max-w-md relative z-10">
        {/* Progress Bar */}
        <div className="flex items-center justify-between mb-8 px-2">
          <div className="flex items-center gap-1">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${step >= 1 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>1</span>
            <span className="text-[10px] font-mono tracking-wider text-muted-foreground uppercase hidden sm:inline">Profile</span>
          </div>
          <div className={`h-[2px] flex-1 mx-2 ${step >= 2 ? 'bg-primary' : 'bg-muted'}`} />
          <div className="flex items-center gap-1">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${step >= 2 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>2</span>
            <span className="text-[10px] font-mono tracking-wider text-muted-foreground uppercase hidden sm:inline">Preferences</span>
          </div>
          <div className={`h-[2px] flex-1 mx-2 ${step >= 3 ? 'bg-primary' : 'bg-muted'}`} />
          <div className="flex items-center gap-1">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${step >= 3 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>3</span>
            <span className="text-[10px] font-mono tracking-wider text-muted-foreground uppercase hidden sm:inline">Launch</span>
          </div>
        </div>

        {/* Card Frame */}
        <div className="bg-card border border-border rounded-2xl p-8 shadow-lg hover:shadow-xl transition-all duration-300 animate-in fade-in slide-in-from-bottom-4 duration-500">
          
          {/* STEP 1: Profile Setup */}
          {step === 1 && (
            <form onSubmit={handleStep1Submit} className="space-y-6">
              <div className="text-center space-y-2 mb-4">
                <div className="inline-flex p-3 bg-primary/10 text-primary rounded-xl mb-2">
                  <User className="w-6 h-6" />
                </div>
                <h2 className="text-2xl font-serif font-bold text-foreground">Tell us about yourself</h2>
                <p className="text-xs text-muted-foreground">Initialize your workspace persona parameters.</p>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">First Name</label>
                  <input
                    type="text"
                    required
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="e.g. John"
                    className="w-full px-4 py-2.5 bg-muted/65 border border-border/80 rounded-xl focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all text-sm font-sans"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">Last Name</label>
                  <input
                    type="text"
                    required
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="e.g. Doe"
                    className="w-full px-4 py-2.5 bg-muted/65 border border-border/80 rounded-xl focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all text-sm font-sans"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">Job Title</label>
                  <input
                    type="text"
                    required
                    value={jobTitle}
                    onChange={(e) => setJobTitle(e.target.value)}
                    placeholder="e.g. Sales Consultant"
                    className="w-full px-4 py-2.5 bg-muted/65 border border-border/80 rounded-xl focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all text-sm font-sans"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading || !firstName.trim() || !lastName.trim()}
                className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 rounded-xl cursor-pointer disabled:opacity-50 active:scale-98 transition-all text-sm mt-8 shadow-xs"
              >
                <span>Continue</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}

          {/* STEP 2: Preferences */}
          {step === 2 && (
            <form onSubmit={handleStep2Submit} className="space-y-6">
              <div className="text-center space-y-2 mb-4">
                <div className="inline-flex p-3 bg-primary/10 text-primary rounded-xl mb-2">
                  <Settings className="w-6 h-6" />
                </div>
                <h2 className="text-2xl font-serif font-bold text-foreground">Configure Preferences</h2>
                <p className="text-xs text-muted-foreground">Select your interface theme and local parameters.</p>
              </div>

              <div className="space-y-5">
                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-2">Interface Theme</label>
                  <div className="grid grid-cols-3 gap-3">
                    {([
                      { id: 'light', icon: Sun, label: 'Light' },
                      { id: 'dark', icon: Moon, label: 'Dark' },
                      { id: 'system', icon: Monitor, label: 'System' }
                    ] as const).map((t) => {
                      const Icon = t.icon;
                      const active = theme === t.id;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setTheme(t.id)}
                          className={`flex flex-col items-center justify-center p-3 border rounded-xl cursor-pointer hover:border-primary/60 active:scale-97 transition-all ${active ? 'border-primary bg-primary/5 text-primary' : 'border-border/80 text-foreground/80'}`}
                        >
                          <Icon className="w-4 h-4 mb-1.5" />
                          <span className="text-[10px] font-semibold">{t.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">Language</label>
                  <select
                    value={lang}
                    onChange={(e) => setLang(e.target.value)}
                    className="w-full px-4 py-2.5 bg-muted/65 border border-border/80 rounded-xl focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all text-sm font-sans"
                  >
                    <option value="en">English (US)</option>
                    <option value="es">Español</option>
                    <option value="fr">Français</option>
                    <option value="de">Deutsch</option>
                  </select>
                </div>
              </div>

              <button
                type="submit"
                className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 rounded-xl cursor-pointer active:scale-98 transition-all text-sm mt-8 shadow-xs"
              >
                <span>Continue</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}

          {/* STEP 3: Launch Confirmation */}
          {step === 3 && (
            <div className="text-center space-y-6">
              <div className="space-y-2">
                <div className="inline-flex p-3 bg-emerald-500/10 text-emerald-500 rounded-xl mb-2 animate-bounce">
                  <Sparkles className="w-6 h-6" />
                </div>
                <h2 className="text-2xl font-serif font-bold text-foreground">You are all set!</h2>
                <p className="text-xs text-muted-foreground">Your workspace profile synchronization is complete.</p>
              </div>

              <div className="bg-muted/40 border border-border/50 rounded-xl p-4 text-left space-y-2">
                <p className="text-xs font-semibold text-foreground/80 flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Profile provisioning completed</span>
                </p>
                <p className="text-xs font-semibold text-foreground/80 flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Preferences saved successfully</span>
                </p>
                <p className="text-xs font-semibold text-foreground/80 flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Default personal workspace deployed</span>
                </p>
              </div>

              <button
                onClick={handleComplete}
                className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-bold py-2.5 rounded-xl cursor-pointer active:scale-98 transition-all text-sm mt-8 shadow-xs"
              >
                <span>Launch Console</span>
                <Check className="w-4 h-4" />
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default OnboardingWizard;
