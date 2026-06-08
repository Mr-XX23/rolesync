import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

// Define the interface for user data
interface User {
  email: string;
}

// Define the auth state schema
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  isResetLoading: boolean;
  resetSuccess: boolean;
  resetError: string | null;
  isUpdateLoading: boolean;
  updateSuccess: boolean;
  updateError: string | null;
  isRegisterLoading: boolean;
  registerSuccess: boolean;
  registerError: string | null;
  isVerifyLoading: boolean;
  verifySuccess: boolean;
  verifyError: string | null;
}

// Initial state matching the schema
const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,
  isResetLoading: false,
  resetSuccess: false,
  resetError: null,
  isUpdateLoading: false,
  updateSuccess: false,
  updateError: null,
  isRegisterLoading: false,
  registerSuccess: false,
  registerError: null,
  isVerifyLoading: false,
  verifySuccess: false,
  verifyError: null,
};

// Async thunk simulating login request
export const loginUser = createAsyncThunk(
  'auth/loginUser',
  async (credentials: { email: string; password?: string }, { rejectWithValue }) => {
    try {
      // Simulate API call delay of 1.5s
      await new Promise((resolve) => setTimeout(resolve, 1500));
      
      // Basic mock validation (e.g. password can't be less than 6 chars)
      if (credentials.password && credentials.password.length < 6) {
        return rejectWithValue('Password must be at least 6 characters.');
      }
      
      return { email: credentials.email };
    } catch (err: any) {
      return rejectWithValue(err.message || 'An error occurred during authentication.');
    }
  }
);

// Async thunk simulating registration request
export const registerUser = createAsyncThunk(
  'auth/registerUser',
  async (userData: { email: string; fullName: string; password?: string; phone?: string; role?: string }, { rejectWithValue }) => {
    try {
      // Simulate API call delay of 1.5s
      await new Promise((resolve) => setTimeout(resolve, 1500));
      
      if (!userData.email || !userData.email.includes('@')) {
        return rejectWithValue('Please enter a valid work email address.');
      }
      if (userData.password && userData.password.length < 12) {
        return rejectWithValue('Password must be at least 12 characters.');
      }
      
      return { email: userData.email };
    } catch (err: any) {
      return rejectWithValue(err.message || 'An error occurred during registration.');
    }
  }
);

// Async thunk simulating phone OTP verification request
export const verifyPhone = createAsyncThunk(
  'auth/verifyPhone',
  async (data: { code: string }, { rejectWithValue }) => {
    try {
      // Simulate API call delay of 1.5s
      await new Promise((resolve) => setTimeout(resolve, 1500));
      
      if (data.code.length !== 6 || !/^\d+$/.test(data.code)) {
        return rejectWithValue('Please enter a valid 6-digit verification code.');
      }
      
      // Let's say entering '000000' represents an invalid code
      if (data.code === '000000') {
        return rejectWithValue('Invalid verification code. Please try again.');
      }
      
      return { success: true };
    } catch (err: any) {
      return rejectWithValue(err.message || 'An error occurred during verification.');
    }
  }
);

// Async thunk simulating password reset request
export const resetPassword = createAsyncThunk(
  'auth/resetPassword',
  async (data: { email: string }, { rejectWithValue }) => {
    try {
      // Simulate API call delay of 1.2s
      await new Promise((resolve) => setTimeout(resolve, 1200));

      if (!data.email || !data.email.includes('@')) {
        return rejectWithValue('Please enter a valid work email address.');
      }

      return { email: data.email };
    } catch (err: any) {
      return rejectWithValue(err.message || 'An error occurred while sending the reset link.');
    }
  }
);

// Async thunk simulating password update request
export const updatePassword = createAsyncThunk(
  'auth/updatePassword',
  async (password: string, { rejectWithValue }) => {
    try {
      // Simulate API call delay of 1.5s
      await new Promise((resolve) => setTimeout(resolve, 1500));
      
      if (!password || password.length < 12) {
        return rejectWithValue('Password does not meet requirements.');
      }
      
      return { success: true };
    } catch (err: any) {
      return rejectWithValue(err.message || 'An error occurred while updating the password.');
    }
  }
);

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout: (state) => {
      state.user = null;
      state.isAuthenticated = false;
      state.isLoading = false;
      state.error = null;
    },
    clearError: (state) => {
      state.error = null;
    },
    clearResetState: (state) => {
      state.isResetLoading = false;
      state.resetSuccess = false;
      state.resetError = null;
    },
    clearUpdateState: (state) => {
      state.isUpdateLoading = false;
      state.updateSuccess = false;
      state.updateError = null;
    },
    clearRegisterState: (state) => {
      state.isRegisterLoading = false;
      state.registerSuccess = false;
      state.registerError = null;
    },
    clearVerifyState: (state) => {
      state.isVerifyLoading = false;
      state.verifySuccess = false;
      state.verifyError = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // Login flow
      .addCase(loginUser.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(loginUser.fulfilled, (state, action: PayloadAction<User>) => {
        state.isLoading = false;
        state.isAuthenticated = true;
        state.user = action.payload;
        state.error = null;
      })
      .addCase(loginUser.rejected, (state, action) => {
        state.isLoading = false;
        state.isAuthenticated = false;
        state.error = (action.payload as string) || 'Authentication failed.';
      })
      // Register flow
      .addCase(registerUser.pending, (state) => {
        state.isRegisterLoading = true;
        state.registerSuccess = false;
        state.registerError = null;
      })
      .addCase(registerUser.fulfilled, (state, action: PayloadAction<User>) => {
        state.isRegisterLoading = false;
        state.registerSuccess = true;
        state.isAuthenticated = true;
        state.user = action.payload;
        state.registerError = null;
      })
      .addCase(registerUser.rejected, (state, action) => {
        state.isRegisterLoading = false;
        state.registerSuccess = false;
        state.registerError = (action.payload as string) || 'Registration failed.';
      })
      // Verify Phone flow
      .addCase(verifyPhone.pending, (state) => {
        state.isVerifyLoading = true;
        state.verifySuccess = false;
        state.verifyError = null;
      })
      .addCase(verifyPhone.fulfilled, (state) => {
        state.isVerifyLoading = false;
        state.verifySuccess = true;
        state.verifyError = null;
      })
      .addCase(verifyPhone.rejected, (state, action) => {
        state.isVerifyLoading = false;
        state.verifySuccess = false;
        state.verifyError = (action.payload as string) || 'Phone verification failed.';
      })
      // Password reset flow
      .addCase(resetPassword.pending, (state) => {
        state.isResetLoading = true;
        state.resetSuccess = false;
        state.resetError = null;
      })
      .addCase(resetPassword.fulfilled, (state) => {
        state.isResetLoading = false;
        state.resetSuccess = true;
        state.resetError = null;
      })
      .addCase(resetPassword.rejected, (state, action) => {
        state.isResetLoading = false;
        state.resetSuccess = false;
        state.resetError = (action.payload as string) || 'Failed to send reset link.';
      })
      // Password update flow
      .addCase(updatePassword.pending, (state) => {
        state.isUpdateLoading = true;
        state.updateSuccess = false;
        state.updateError = null;
      })
      .addCase(updatePassword.fulfilled, (state) => {
        state.isUpdateLoading = false;
        state.updateSuccess = true;
        state.updateError = null;
      })
      .addCase(updatePassword.rejected, (state, action) => {
        state.isUpdateLoading = false;
        state.verifySuccess = false;
        state.updateError = (action.payload as string) || 'Failed to update password.';
      });
  },
});

export const { logout, clearError, clearResetState, clearUpdateState, clearRegisterState, clearVerifyState } = authSlice.actions;
export default authSlice.reducer;
