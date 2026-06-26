-- ============================================================================
-- Initial Database Schema for Workspace Service
-- ============================================================================
-- Purpose: Create all tables for workspace management, memberships, preferences, tasks, context, and notes
-- Version: 1.0
-- ============================================================================

-- 1. Workspace Profile Table
CREATE TABLE IF NOT EXISTS workspace_profiles (
    profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    display_name VARCHAR(100),
    avatar_url VARCHAR(255),
    job_title VARCHAR(100),
    bio TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Workspace Role Table
CREATE TABLE IF NOT EXISTS workspace_roles (
    role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Workspace Table
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    owner_profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Workspace Membership Table
CREATE TABLE IF NOT EXISTS workspace_memberships (
    membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES workspace_roles(role_id) ON DELETE RESTRICT,
    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (workspace_id, profile_id)
);

-- 5. Workspace Preferences Table
CREATE TABLE IF NOT EXISTS workspace_preferences (
    preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID UNIQUE NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE CASCADE,
    theme VARCHAR(20) DEFAULT 'dark',
    language VARCHAR(10) DEFAULT 'en',
    timezone VARCHAR(50) DEFAULT 'UTC',
    notification_email BOOLEAN NOT NULL DEFAULT TRUE,
    notification_sms BOOLEAN NOT NULL DEFAULT TRUE,
    dashboard_layout JSONB,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Onboarding State Table
CREATE TABLE IF NOT EXISTS onboarding_states (
    state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID UNIQUE NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE CASCADE,
    current_step VARCHAR(50),
    completed_steps JSONB,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Workspace Context Table
CREATE TABLE IF NOT EXISTS workspace_contexts (
    context_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    created_by_profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE RESTRICT,
    title VARCHAR(150) NOT NULL,
    context_type VARCHAR(50),
    summary TEXT,
    status VARCHAR(30),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Workspace Task View Table
CREATE TABLE IF NOT EXISTS workspace_task_views (
    view_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    context_id UUID NOT NULL REFERENCES workspace_contexts(context_id) ON DELETE CASCADE,
    task_name VARCHAR(150) NOT NULL,
    agent_name VARCHAR(100),
    output_type VARCHAR(50),
    task_status VARCHAR(30),
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 9. Workspace Agent Assignment Table
CREATE TABLE IF NOT EXISTS workspace_agent_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    context_id UUID NOT NULL REFERENCES workspace_contexts(context_id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE RESTRICT,
    agent_type VARCHAR(100),
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 10. Workspace Note Table
CREATE TABLE IF NOT EXISTS workspace_notes (
    note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    context_id UUID NOT NULL REFERENCES workspace_contexts(context_id) ON DELETE CASCADE,
    author_profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE RESTRICT,
    note_title VARCHAR(150) NOT NULL,
    note_body TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 11. Saved Dashboard Layout Table
CREATE TABLE IF NOT EXISTS saved_dashboard_layouts (
    layout_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES workspace_profiles(profile_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    layout_name VARCHAR(100) NOT NULL,
    layout_config JSONB,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- Triggers for Automatic Timestamp Updates
-- ============================================================================

CREATE OR REPLACE FUNCTION update_workspace_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to tables that have updated_at
CREATE TRIGGER update_workspace_profiles_updated_at
    BEFORE UPDATE ON workspace_profiles
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_workspace_preferences_updated_at
    BEFORE UPDATE ON workspace_preferences
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_onboarding_states_updated_at
    BEFORE UPDATE ON onboarding_states
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_workspace_contexts_updated_at
    BEFORE UPDATE ON workspace_contexts
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_workspace_task_views_updated_at
    BEFORE UPDATE ON workspace_task_views
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_workspace_notes_updated_at
    BEFORE UPDATE ON workspace_notes
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();

CREATE TRIGGER update_saved_dashboard_layouts_updated_at
    BEFORE UPDATE ON saved_dashboard_layouts
    FOR EACH ROW EXECUTE FUNCTION update_workspace_updated_at_column();
