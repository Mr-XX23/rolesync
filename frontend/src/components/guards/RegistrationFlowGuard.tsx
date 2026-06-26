import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAppSelector } from '../../store';

interface RegistrationFlowGuardProps {
  children: React.ReactNode;
}

export const RegistrationFlowGuard: React.FC<RegistrationFlowGuardProps> = ({ children }) => {
  const { isAuthenticated, tempUser, registrationStep } = useAppSelector((state) => state.auth);
  const location = useLocation();

  // 1. Authenticated users shouldn't see registration/verification flows
  if (isAuthenticated) {
    return <Navigate to="/select-role" replace />;
  }

  // 2. If no active registration flow is in progress, send them back to start
  if (!tempUser || !registrationStep) {
    return <Navigate to="/register" replace />;
  }

  // 3. Enforce step-by-step route traversal
  if (location.pathname === '/verify-email' && registrationStep !== 'email') {
    // If they have completed email and are on phone step, send them to phone verify
    if (registrationStep === 'phone') {
      return <Navigate to="/verify-phone" replace />;
    }
  }

  if (location.pathname === '/verify-phone' && registrationStep !== 'phone') {
    // If they are supposed to verify email, do not let them access phone verify
    if (registrationStep === 'email') {
      return <Navigate to="/verify-email" replace />;
    }
  }

  return <>{children}</>;
};
