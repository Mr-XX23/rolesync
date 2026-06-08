import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAppSelector } from '../../store';
import type { RolePack } from '../../store/roleSlice';

interface WorkspaceGuardProps {
  children: React.ReactNode;
  requiredRole: RolePack;
}

export const WorkspaceGuard: React.FC<WorkspaceGuardProps> = ({ children, requiredRole }) => {
  const { activeRolePack } = useAppSelector((state) => state.role);

  if (!activeRolePack) {
    // If no active persona is selected, bounce them back to the selection screen
    return <Navigate to="/select-role" replace />;
  }

  if (activeRolePack !== requiredRole) {
    // Role mismatch, bounce them to the selection screen
    return <Navigate to="/select-role" replace />;
  }

  return <>{children}</>;
};
