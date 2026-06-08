---
description: Comprehensive workspace architecture and design system instruction profile for RoleSync.ai. This configuration dictates strict engineering boundaries for the agent runtime—forcing absolute obedience to decoupled microservice patterns,
---

# RoleSync.ai Anti Gravity Execution Rules & Standards

## 1. Core Stack Framework Controls
- **Runtime Engine:** `Bun` (Enforce local native package resolution via bun. lock files only; do not spawn npm or yarn processes).
- **Frontend Stack:** `Vite + React (TypeScript)`.
- **State Architecture:** `Redux Toolkit (RTK)` manages app state lifecycles (active tokens, active persona workspace configurations, websocket channels).
- **Routing Engine:** `React Router v6` utilizing the declarative **Data Router API** (`createBrowserRouter`).
  - Strict File Mapping Requirements:
    - `src/router.tsx` -> Primary application route registry and auth state guards.
    - `src/store/roleSlice.ts` -> Single source of truth for current workspace profile mode context.
    - `src/views/LoginView.tsx` -> Frame 1: Pure white geometric authentication gate.
    - `src/views/RolePicker.tsx` -> Frame 2: Multi-persona grid launcher canvas.
    - `src/views/ConsoleShell.tsx` -> Frame 3: Content-rich Industrial Foundry workspace log deck.

## 2. Strict Routing Architecture Rules
- **No Inline Route Sprinkling:** All route layouts must be mapped inside the central `src/router.tsx` object configuration registry using structural layout wrappers.
- **Route Authorization Enforcement:** Guard access to protected endpoints (`/select-role`, `/console`) via a custom state-aware `<ProtectedRoute>` component that queries the current authentication attribute out of the global Redux store before painting target fragments.
- **Context Locking Guard:** Ingress into the dynamic control deck (`/console`) must be protected by an explicit `<WorkspaceGuard>` verifying that `activeRolePack` inside the store contains an authorized value (`'sales' | 'teacher' | 'student'`). If missing, safely bounce browser address history back to `/select-role`.

## 3. Stitch Project Design System & Token Integration
The automation runtime must match these exact theme tokens extracted from the platform's layout configuration screen:

```css
/* Core Styling Constants — Do Not Deviate or Rewrite */
:root {
  --background: #f9f9f9;
  --foreground: #202020;
  --card: #fcfcfc;
  --card-foreground: #202020;
  --primary: #644a40; /* Industrial Slate Copper */
  --primary-foreground: #ffffff;
  --secondary: #ffdfb5; /* Accent Amber Blend */
  --secondary-foreground: #582d1d;
  --muted: #efefef;
  --muted-foreground: #646464;
  --accent: #e8e8e8;
  --accent-foreground: #202020;
  --destructive: #e54d2e;
  --border: #d8d8d8;
  --input: #d8d8d8;
  --ring: #644a40;
  
  --sidebar: #fbfbfb;
  --sidebar-foreground: #252525;
  --sidebar-border: #ebebeb;
  
  --font-sans: DM Sans, ui-sans-serif, sans-serif, system-ui;
  --font-serif: DM Serif Display, ui-serif, serif;
  --font-mono: DM Mono, ui-monospace, monospace;
  
  --radius: 0.75rem; /* Base Roundness = 12px Exactly */
}

.dark {
  --background: #111111;
  --foreground: #eeeeee;
  --card: #191919;
  --card-foreground: #eeeeee;
  --primary: #ffe0c2;
  --primary-foreground: #081a1b;
  --secondary: #393028;
  --secondary-foreground: #ffe0c2;
  --muted: #222222;
  --muted-foreground: #b4b4b4;
  --accent: #2a2a2a;
  --accent-foreground: #eeeeee;
  --border: #201e18;
  --input: #484848;
  --ring: #ffe0c2;
  
  --sidebar: #18181b;
  --sidebar-foreground: #f4f4f5;
  --sidebar-border: #27272a;
}