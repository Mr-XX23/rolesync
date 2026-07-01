import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import api from '../api/axiosInstance';

export interface WorkspaceProfile {
  profileId: string;
  authUserId: string;
  firstName: string;
  lastName: string;
  jobTitle: string;
}

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
  isLoading: boolean;
  error: string | null;
}

const initialState: WorkspaceState = {
  profile: null,
  preferences: null,
  onboarding: null,
  isLoading: false,
  error: null,
};

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
  async (profileData: { firstName: string; lastName: string; jobTitle: string; authUserId: string }, { rejectWithValue }) => {
    try {
      await api.post('/workspaces/profile', {
        auth_user_id: profileData.authUserId,
        first_name: profileData.firstName,
        last_name: profileData.lastName,
        job_title: profileData.jobTitle,
      });
      const profileRes = await api.get('/workspaces/profile');
      return profileRes.data as WorkspaceProfile;
    } catch (error: any) {
      return rejectWithValue(
        error.response?.data?.message || 'Failed to update workspace profile'
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
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
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
      .addCase(updateProfile.fulfilled, (state, action: PayloadAction<WorkspaceProfile>) => {
        state.profile = action.payload;
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

export const { clearWorkspaceState } = workspaceSlice.actions;
export default workspaceSlice.reducer;
