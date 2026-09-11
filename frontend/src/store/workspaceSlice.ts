import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import api from '../api/axiosInstance';

export interface WorkspaceProfile {
  profileId?: string;
  authUserId?: string;
  firstName?: string;
  lastName?: string;
  displayName?: string;
  avatarUrl?: string;
  jobTitle?: string;
  department?: string;
  organization?: string;
  location?: string;
  secondaryEmail?: string;
  phoneNumber?: string;
  education?: string;
  expertise?: string;
  skills?: string;
  interests?: string;
  hobbies?: string;
  aiPersonaContext?: string;
  communicationStyle?: string;
  linkedinUrl?: string;
  githubUrl?: string;
  websiteUrl?: string;
  facebookUrl?: string;
  xUrl?: string;
  instagramUrl?: string;
  bio?: string;
  dailyUpdateCount?: number;
  updateWindowStart?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface WorkspaceItem {
  workspaceId: string;
  name: string;
  description: string;
  isActive: boolean;
  createdAt?: string;
  updatedAt?: string;
  role?: string | null; // the signed-in user's role: OWNER, ADMIN, MEMBER or VIEWER
}

export type WorkspaceStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface WorkspacePreferences {
  preferenceId: string;
  theme: string;
  language: string;
  timezone: string;
}

export interface OnboardingStateSchema {
  stateId: string;
  currentStep: string;
  completedSteps: string[] | null;
  isCompleted: boolean;
}

interface WorkspaceState {
  profile: WorkspaceProfile | null;
  preferences: WorkspacePreferences | null;
  onboarding: OnboardingStateSchema | null;
  workspaces: WorkspaceItem[];
  currentWorkspace: WorkspaceItem | null;
  // Whether the active workspace is known yet (see ensureWorkspace), and for which user.
  workspaceStatus: WorkspaceStatus;
  workspaceLoadedFor: string | null;
  workspaceError: string | null;
  isLoading: boolean;
  error: string | null;
}

const initialState: WorkspaceState = {
  profile: null,
  preferences: null,
  onboarding: null,
  workspaces: [],
  currentWorkspace: null,
  workspaceStatus: 'idle',
  workspaceLoadedFor: null,
  workspaceError: null,
  isLoading: false,
  error: null,
};

const ACTIVE_WORKSPACE_KEY = 'rolesync_active_workspace_id';

function readRememberedWorkspace(): string | null {
  try {
    return localStorage.getItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    return null; // storage unavailable (private mode, blocked site data)
  }
}

function rememberWorkspace(workspaceId: string): void {
  try {
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId);
  } catch {
    // not remembered across reloads; the first workspace is picked again
  }
}

/**
 * Makes sure the signed-in user has a workspace and picks the active one. The first call
 * for a new account creates their personal workspace; the last workspace they used stays
 * active if they still belong to it. Every workspace-scoped page waits for this.
 */
export const ensureWorkspace = createAsyncThunk(
  'workspace/ensureWorkspace',
  async (userId: string, { rejectWithValue }) => {
    try {
      const ensured = (await api.post<WorkspaceItem>('/workspaces/default')).data;
      const listed = (await api.get<WorkspaceItem[]>('/workspaces')).data;
      const workspaces = listed.length > 0 ? listed : [ensured];
      const remembered = readRememberedWorkspace();
      const current =
        workspaces.find((ws) => ws.workspaceId === remembered) ??
        workspaces.find((ws) => ws.workspaceId === ensured.workspaceId) ??
        workspaces[0];
      rememberWorkspace(current.workspaceId);
      return { userId, workspaces, current };
    } catch (error) {
      const message = (error as { response?: { data?: { message?: string } } }).response?.data?.message;
      return rejectWithValue(message || 'Could not load your workspace');
    }
  }
);

export const fetchProfile = createAsyncThunk(
  'workspace/fetchProfile',
  async (_, { rejectWithValue }) => {
    try {
      const response = await api.get('/workspaces/profile');
      return response.data as WorkspaceProfile;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to fetch workspace profile'
      );
    }
  }
);

export const updateProfile = createAsyncThunk(
  'workspace/updateProfile',
  async (profileData: Partial<WorkspaceProfile> & { authUserId: string }, { rejectWithValue }) => {
    try {
      await api.post('/workspaces/profile', {
        auth_user_id: profileData.authUserId,
        first_name: profileData.firstName,
        last_name: profileData.lastName,
        display_name: profileData.displayName,
        avatar_url: profileData.avatarUrl,
        job_title: profileData.jobTitle,
        department: profileData.department,
        organization: profileData.organization,
        location: profileData.location,
        secondary_email: profileData.secondaryEmail,
        phone_number: profileData.phoneNumber,
        education: profileData.education,
        expertise: profileData.expertise,
        skills: profileData.skills,
        interests: profileData.interests,
        hobbies: profileData.hobbies,
        ai_persona_context: profileData.aiPersonaContext,
        communication_style: profileData.communicationStyle,
        linkedin_url: profileData.linkedinUrl,
        github_url: profileData.githubUrl,
        website_url: profileData.websiteUrl,
        facebook_url: profileData.facebookUrl,
        x_url: profileData.xUrl,
        instagram_url: profileData.instagramUrl,
        bio: profileData.bio,
      });
      const profileRes = await api.get('/workspaces/profile');
      return profileRes.data as WorkspaceProfile;
    } catch (error: any) {
      if (error.response?.status === 429) {
        return rejectWithValue(
          error.response?.data?.message || 'Profile update limit reached. You can only update your profile 2 times every 24 hours.'
        );
      }
      return rejectWithValue(
        error.response?.data?.message || 'Failed to update workspace profile'
      );
    }
  }
);

export const uploadAvatar = createAsyncThunk(
  'workspace/uploadAvatar',
  async (file: File, { rejectWithValue }) => {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await api.post('/workspaces/profile/avatar', formData, {
        headers: {
          'Content-Type': undefined,
        },
      });
      return response.data as { avatar_url: string; message: string };
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to upload profile photo'
      );
    }
  }
);

export const uploadAvatarUrl = createAsyncThunk(
  'workspace/uploadAvatarUrl',
  async (url: string, { rejectWithValue }) => {
    try {
      const response = await api.post('/workspaces/profile/avatar/url', { url });
      return response.data as { avatar_url: string; message: string };
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to process and save image from URL'
      );
    }
  }
);

export const fetchWorkspaces = createAsyncThunk(
  'workspace/fetchWorkspaces',
  async (_, { rejectWithValue }) => {
    try {
      const response = await api.get('/workspaces');
      return response.data as WorkspaceItem[];
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to fetch workspaces'
      );
    }
  }
);

export const updateWorkspaceDetails = createAsyncThunk(
  'workspace/updateWorkspaceDetails',
  async ({ workspaceId, name, description }: { workspaceId: string; name: string; description: string }, { rejectWithValue }) => {
    try {
      const response = await api.put(`/workspaces/${workspaceId}`, {
        name,
        description,
      });
      return response.data as WorkspaceItem;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to update workspace details'
      );
    }
  }
);

export const fetchPreferences = createAsyncThunk(
  'workspace/fetchPreferences',
  async (_, { rejectWithValue }) => {
    try {
      const response = await api.get('/workspaces/profile/preferences');
      return response.data as WorkspacePreferences;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to fetch workspace preferences'
      );
    }
  }
);

export const updateThemePreference = createAsyncThunk(
  'workspace/updateThemePreference',
  async (theme: 'light' | 'dark' | 'system', { rejectWithValue }) => {
    try {
      const response = await api.put('/workspaces/profile/preferences', {
        theme,
      });
      return response.data as WorkspacePreferences;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to update theme preference'
      );
    }
  }
);

export const fetchOnboarding = createAsyncThunk(
  'workspace/fetchOnboarding',
  async (_, { rejectWithValue }) => {
    try {
      const response = await api.get('/workspaces/profile/onboarding');
      return response.data as OnboardingStateSchema;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to fetch onboarding state'
      );
    }
  }
);

export const updateOnboarding = createAsyncThunk(
  'workspace/updateOnboarding',
  async (
    onboardingData: { currentStep?: string; completedSteps?: string[]; isCompleted?: boolean },
    { rejectWithValue }
  ) => {
    try {
      const response = await api.put('/workspaces/profile/onboarding/step', {
        current_step: onboardingData.currentStep,
        completed_steps: onboardingData.completedSteps,
        is_completed: onboardingData.isCompleted,
      });
      return response.data as OnboardingStateSchema;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to update onboarding step'
      );
    }
  }
);

const workspaceSlice = createSlice({
  name: 'workspace',
  initialState,
  reducers: {
    clearWorkspaceState: (state) => {
      state.profile = null;
      state.preferences = null;
      state.onboarding = null;
      state.workspaces = [];
      state.currentWorkspace = null;
      state.workspaceStatus = 'idle';
      state.workspaceLoadedFor = null;
      state.workspaceError = null;
      state.error = null;
    },
    setCurrentWorkspace: (state, action: PayloadAction<WorkspaceItem>) => {
      state.currentWorkspace = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      // ensureWorkspace
      .addCase(ensureWorkspace.pending, (state) => {
        state.workspaceStatus = 'loading';
        state.workspaceError = null;
      })
      .addCase(ensureWorkspace.fulfilled, (state, action) => {
        state.workspaces = action.payload.workspaces;
        state.currentWorkspace = action.payload.current;
        state.workspaceLoadedFor = action.payload.userId;
        state.workspaceStatus = 'ready';
      })
      .addCase(ensureWorkspace.rejected, (state, action) => {
        state.workspaceStatus = 'failed';
        state.workspaceError = (action.payload as string) || 'Could not load your workspace';
      })
      // fetchProfile
      .addCase(fetchProfile.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchProfile.fulfilled, (state, action: PayloadAction<WorkspaceProfile>) => {
        state.isLoading = false;
        state.profile = action.payload;
      })
      .addCase(fetchProfile.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // updateProfile
      .addCase(updateProfile.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(updateProfile.fulfilled, (state, action: PayloadAction<WorkspaceProfile>) => {
        state.isLoading = false;
        state.profile = action.payload;
      })
      .addCase(updateProfile.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // uploadAvatar
      .addCase(uploadAvatar.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(uploadAvatar.fulfilled, (state, action: PayloadAction<{ avatar_url: string; message: string }>) => {
        state.isLoading = false;
        if (state.profile) {
          state.profile.avatarUrl = action.payload.avatar_url;
        }
      })
      .addCase(uploadAvatar.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // uploadAvatarUrl
      .addCase(uploadAvatarUrl.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(uploadAvatarUrl.fulfilled, (state, action: PayloadAction<{ avatar_url: string; message: string }>) => {
        state.isLoading = false;
        if (state.profile) {
          state.profile.avatarUrl = action.payload.avatar_url;
        }
      })
      .addCase(uploadAvatarUrl.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // fetchWorkspaces
      .addCase(fetchWorkspaces.fulfilled, (state, action: PayloadAction<WorkspaceItem[]>) => {
        state.workspaces = action.payload;
        if (action.payload.length > 0 && !state.currentWorkspace) {
          state.currentWorkspace = action.payload[0];
        }
      })
      // updateWorkspaceDetails
      .addCase(updateWorkspaceDetails.fulfilled, (state, action: PayloadAction<WorkspaceItem>) => {
        // The update response doesn't include the caller's role; keep the one we know.
        const updated = { ...action.payload, role: action.payload.role ?? state.currentWorkspace?.role };
        state.currentWorkspace = updated;
        state.workspaces = state.workspaces.map((ws) =>
          ws.workspaceId === updated.workspaceId ? updated : ws
        );
      })
      // fetchPreferences
      .addCase(fetchPreferences.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchPreferences.fulfilled, (state, action: PayloadAction<WorkspacePreferences>) => {
        state.isLoading = false;
        state.preferences = action.payload;
      })
      .addCase(fetchPreferences.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // updateThemePreference
      .addCase(updateThemePreference.fulfilled, (state, action: PayloadAction<WorkspacePreferences>) => {
        state.preferences = action.payload;
      })
      // fetchOnboarding
      .addCase(fetchOnboarding.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchOnboarding.fulfilled, (state, action: PayloadAction<OnboardingStateSchema>) => {
        state.isLoading = false;
        state.onboarding = action.payload;
      })
      .addCase(fetchOnboarding.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      // updateOnboarding
      .addCase(updateOnboarding.fulfilled, (state, action: PayloadAction<OnboardingStateSchema>) => {
        state.onboarding = action.payload;
      });
  },
});

export const { clearWorkspaceState, setCurrentWorkspace } = workspaceSlice.actions;
export default workspaceSlice.reducer;
