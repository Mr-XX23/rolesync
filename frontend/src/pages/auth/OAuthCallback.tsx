import React, { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Sparkles, AlertCircle, Loader2 } from 'lucide-react';
import { useAppDispatch } from '../../store';
import { checkSession } from '../../store/authSlice';

const getExistingUserRoute = (): string => {
  const savedRole = localStorage.getItem('rolesync-active-role');
  if (savedRole === 'sales') return '/salesman';
  if (savedRole === 'teacher') return '/teacher';
  if (savedRole === 'student') return '/student';
  return '/select-role';
};

const OAuthCallback: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const success = searchParams.get('success');
    const userId = searchParams.get('userId');
    const isNewUserParam = searchParams.get('isNewUser');
    const errorParam = searchParams.get('error');
    const messageParam = searchParams.get('message');

    const isNewUser = isNewUserParam === 'true';

    // Handle OAuth failure or explicit error parameter
    if (errorParam || (success !== null && success !== 'true')) {
      const errorMsg = messageParam || errorParam || 'Google authentication failed. Please try again.';
      setErrorMessage(errorMsg);
      const timer = setTimeout(() => {
        navigate(`/signin?error=${encodeURIComponent(errorMsg)}`, { replace: true, state: { error: errorMsg } });
      }, 3000);
      return () => clearTimeout(timer);
    }

    // Handle OAuth success
    if (success === 'true') {
      dispatch(checkSession())
        .unwrap()
        .then(() => {
          if (userId && import.meta.env.DEV) {
            console.log(`OAuth login verified for user ID: ${userId}`);
          }
          if (isNewUser) {
            navigate('/onboarding', { replace: true });
          } else {
            navigate(getExistingUserRoute(), { replace: true });
          }
        })
        .catch((err: any) => {
          console.error('OAuth session verification failed:', err);
          const errorMsg = typeof err === 'string' ? err : 'Failed to authenticate session after OAuth login.';
          setErrorMessage(errorMsg);
          const timer = setTimeout(() => {
            navigate(`/signin?error=${encodeURIComponent(errorMsg)}`, { replace: true, state: { error: errorMsg } });
          }, 3000);
          return () => clearTimeout(timer);
        });
    } else {
      // Fallback session check if success param is missing
      dispatch(checkSession())
        .unwrap()
        .then(() => {
          if (isNewUser) {
            navigate('/onboarding', { replace: true });
          } else {
            navigate(getExistingUserRoute(), { replace: true });
          }
        })
        .catch(() => {
          navigate('/signin', { replace: true });
        });
    }
  }, [searchParams, dispatch, navigate]);

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-8 px-4">
      <div className="bg-card rounded-lg border border-border p-8 shadow-sm max-w-md w-full text-center space-y-4">
        {errorMessage ? (
          <div className="space-y-4">
            <div className="mx-auto w-12 h-12 bg-destructive/10 rounded-full flex items-center justify-center text-destructive">
              <AlertCircle className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-bold font-serif text-foreground">Authentication Error</h3>
            <p className="text-sm text-muted-foreground">{errorMessage}</p>
            <p className="text-xs text-muted-foreground/80 font-mono">Redirecting back to sign in...</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="mx-auto w-12 h-12 bg-primary/10 rounded-full flex items-center justify-center text-primary relative">
              <Sparkles className="w-6 h-6 animate-pulse" />
            </div>
            <h3 className="text-xl font-bold font-serif text-foreground">Authenticating via Google</h3>
            <div className="flex items-center justify-center gap-2 text-muted-foreground text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Verifying authorization tokens...</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default OAuthCallback;
