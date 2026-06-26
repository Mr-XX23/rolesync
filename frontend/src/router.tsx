import { createBrowserRouter, Navigate } from 'react-router-dom';
import Signin from './pages/auth/Signin';
import Passwordreset from './pages/auth/Passwordreset';
import Changepassword from './pages/auth/Changepassword';
import Register from './pages/auth/Register';
import VerifyPhone from './pages/auth/VerifyPhone';
import VerifyEmail from './pages/auth/VerifyEmail';
import { RolePicker } from './pages/RolePicker';
import { DashboardLayout } from './components/layout/DashboardLayout';
import { ProtectedRoute } from './components/guards/ProtectedRoute';
import { WorkspaceGuard } from './components/guards/WorkspaceGuard';
import { KnowledgeVault } from './pages/salemans/knowledgeVault/KnowledgeVault';
import { ExternalConnector } from './pages/salemans/externalConnector/ExternalConnector';
import { AiTasks } from './pages/salemans/AiTasks';
import { Workspace } from './pages/salemans/Workspace';
import { Settings } from './pages/salemans/Settings';
import { Support } from './pages/salemans/Support';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/select-role" replace />,
  },
  {
    path: '/signin',
    element: <Signin />,
  },
  {
    path: '/login',
    element: <Navigate to="/signin" replace />,
  },
  {
    path: '/register',
    element: <Register />,
  },
  {
    path: '/verify-email',
    element: <VerifyEmail />,
  },
  {
    path: '/verify-phone',
    element: <VerifyPhone />,
  },
  {
    path: '/forgot-password',
    element: <Passwordreset />,
  },
  {
    path: '/change-password',
    element: <Changepassword />,
  },
  {
    path: '/select-role',
    element: (
      <ProtectedRoute>
        <RolePicker />
      </ProtectedRoute>
    ),
  },
  {
    path: '/salesman',
    element: (
      <ProtectedRoute>
        <WorkspaceGuard requiredRole="sales">
          <DashboardLayout />
        </WorkspaceGuard>
      </ProtectedRoute>
    ),
    children: [
      {
        path: '',
        element: <Navigate to="knowledge-vault" replace />,
      },
      {
        path: 'knowledge-vault',
        element: <KnowledgeVault />,
      },
      {
        path: 'external-connector',
        element: <ExternalConnector />,
      },
      {
        path: 'ai-tasks',
        element: <AiTasks />,
      },
      {
        path: 'workspace',
        element: <Workspace />,
      },
      {
        path: 'settings',
        element: <Settings />,
      },
      {
        path: 'support',
        element: <Support />,
      },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/select-role" replace />,
  },
]);
