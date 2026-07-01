import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAppSelector } from '../../store';

interface OnboardingGuardProps {
  children: React.ReactNode;
}

export const OnboardingGuard: React.FC<OnboardingGuardProps> = ({ children }) => {
  const { onboarding, isLoading } = useAppSelector((state) => state.workspace);
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  if (!isAuthenticated) {
    return <Navigate to="/signin" replace />;
  }

  if (isLoading && !onboarding) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background text-foreground">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (onboarding && !onboarding.isCompleted) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
};
