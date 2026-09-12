import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import {
  Library,
  Cable,
  Bot,
  FolderKanban,
  LifeBuoy,
  Plus,
  Settings as SettingsIcon,
  Package,
  MessagesSquare,
  Handshake,
} from 'lucide-react';
import { Sidebar } from './Sidebar';
import type { SidebarItem } from './Sidebar';
import { Header } from './Header';
import { useAppSelector, useAppDispatch } from '../../store';
import { setModalOpen } from '../../store/taskSlice';
import { NewInstanceModal } from '../common/NewInstanceModal';
import { WorkspaceGate } from '../guards/WorkspaceGate';

export const DashboardLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { activeRolePack } = useAppSelector((state) => state.role);
  const dispatch = useAppDispatch();

  // Define sidebar configurations based on the selected persona role
  const getSidebarConfig = () => {
    switch (activeRolePack) {
      case 'sales':
      default:
        return {
          logo: {
            title: 'RoleSync',
            subtitle: 'Enterprise AI',
          },
          items: [
            {
              id: 'sales-agent',
              label: 'Sales Agent',
              icon: MessagesSquare,
              path: '/salesman/sales-agent',
              badge: 'New',
            },
            {
              id: 'deals',
              label: 'Deals',
              icon: Handshake,
              path: '/salesman/deals',
            },
            {
              id: 'products',
              label: 'Product Management',
              icon: Package,
              path: '/salesman/products',
            },
            {
              id: 'knowledge-vault',
              label: 'Knowledge Vault',
              icon: Library,
              path: '/salesman/knowledge-vault',
              badge: 'Live',
            },
            {
              id: 'external-connector',
              label: 'Data Connectors',
              icon: Cable,
              path: '/salesman/external-connector',
            },
            {
              id: 'ai-tasks',
              label: 'Agent Manager',
              icon: Bot,
              path: '/salesman/ai-tasks',
            },
            {
              id: 'workspace',
              label: 'Workspace',
              icon: FolderKanban,
              path: '/salesman/workspace',
            },
          ] as SidebarItem[],
          bottomItems: [
            {
              id: 'settings',
              label: 'Settings',
              icon: SettingsIcon,
              path: '/salesman/settings',
            },
            {
              id: 'support',
              label: 'Support',
              icon: LifeBuoy,
              path: '/salesman/support',
            },
          ] as SidebarItem[],
          actionButton: {
            label: 'New Agent',
            icon: Plus,
            onClick: () => {
              dispatch(setModalOpen(true));
            },
          },
        };
    }
  };

  const config = getSidebarConfig();

  return (
    <div className="min-h-screen bg-background text-foreground flex overflow-hidden">
      {/* Sidebar Viewport */}
      <Sidebar
        logo={config.logo}
        items={config.items}
        bottomItems={config.bottomItems}
        actionButton={config.actionButton}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main Console Section */}
      <div className="flex-1 flex flex-col h-screen relative overflow-hidden">
        {/* Header Appbar */}
        <Header
          onMenuToggle={() => setSidebarOpen(!sidebarOpen)}
          searchPlaceholder="Search knowledge embeddings..."
        />

        {/* Scrollable Viewport Outlet */}
        <main className="flex-1 overflow-y-auto relative p-4 md:p-8 bg-background/50">
          <div className="max-w-[87rem] mx-auto w-full h-full">
            <WorkspaceGate>
              <Outlet />
            </WorkspaceGate>
          </div>
        </main>
      </div>

      {/* Modal Component */}
      <NewInstanceModal />
    </div>
  );
};
