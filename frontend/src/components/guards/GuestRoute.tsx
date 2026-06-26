import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAppSelector } from '../../store';

interface GuestRouteProps {
  children: React.ReactNode;
}

export const GuestRoute: React.FC<GuestRouteProps> = ({ children }) => {
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  if (isAuthenticated) {
    return <Navigate to="/select-role" replace />;
  }

  return <>{children}</>;
};
