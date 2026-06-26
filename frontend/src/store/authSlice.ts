import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import api from '../api/axiosInstance';

// Define the interface for user data
interface User {
  userId: string;
  username: string;
  email: string;
  role?: string;
  status?: string;
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
  isSendEmailLoading: boolean;
  sendEmailSuccess: boolean;
  sendEmailError: string | null;
  isSendPhoneLoading: boolean;
  sendPhoneSuccess: boolean;
  sendPhoneError: string | null;
  tempUser: { userId: string; email: string; phone: string | null } | null;
  registrationStep: 'email' | 'phone' | null;
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
  isSendEmailLoading: false,
  sendEmailSuccess: false,
  sendEmailError: null,
  isSendPhoneLoading: false,
  sendPhoneSuccess: false,
  sendPhoneError: null,
  tempUser: null,
  registrationStep: null,
};

// Role mapping from frontend dropdown to backend Enum
const mapRole = (role?: string): string => {
  if (!role) return 'USER';
  switch (role.toLowerCase()) {
    case 'sales':
      return 'SALESMAN';
    case 'teacher':
      return 'TEACHER';
    case 'student':
      return 'STUDENT';
    default:
      return 'USER';
  }
};

// Async thunk making real login request
export const loginUser = createAsyncThunk(
  'auth/loginUser',
  async (credentials: { email: string; password?: string }, { rejectWithValue }) => {
    try {
      const response = await api.post('/auth/login', {
        username: credentials.email,
        password: credentials.password,
      });
      
      const data = response.data;
      
      return {
        userId: data.userId,
        username: data.username,
        email: data.email,
        role: data.role,
        status: data.status,
      };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || err.message || 'An error occurred during authentication.');
    }
  }
);

// Async thunk making real registration request
export const registerUser = createAsyncThunk(
  'auth/registerUser',
  async (userData: { email: string; fullName: string; password?: string; phone?: string; role?: string }, { rejectWithValue }) => {
    try {
      const cleanPhone = userData.phone ? userData.phone.replace(/[^\d+]/g, '') : undefined;
      
      const payload = {
        username: userData.fullName,
        email: userData.email,
        phoneNumber: cleanPhone,
        password: userData.password,
        role: mapRole(userData.role),
        acceptTerms: true,
        hipaaPrivacyNotice: true,
      };

      const response = await api.post('/auth/register', payload);

      const data = response.data;

      return {
        userId: data.userId,
        username: data.username,
        email: data.email,
        phone: cleanPhone || null,
      };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || err.message || 'An error occurred during registration.');
    }
  }
);

// Async thunk making real phone OTP verification request
export const verifyPhone = createAsyncThunk(
  'auth/verifyPhone',
  async (data: { code: string; userId: string }, { rejectWithValue }) => {
    try {
      await api.post('/auth/verify-phone', {
        otp: data.code,
        userId: data.userId,
      });

      return { success: true };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || err.message || 'An error occurred during verification.');
    }
  }
);

// Async thunk making real send email verification request
export const sendEmailVerification = createAsyncThunk(
  'auth/sendEmailVerification',
  async (data: { userId: string }, { rejectWithValue }) => {
    try {
      const response = await api.post('/auth/send-email-verification', {
        userId: data.userId,
      });

      const result = response.data;

      return { success: true, message: result.message };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || err.message || 'An error occurred while sending email verification.');
    }
  }
);

// Async thunk making real send phone verification request
export const sendPhoneVerification = createAsyncThunk(
  'auth/sendPhoneVerification',
  async (data: { userId: string }, { rejectWithValue }) => {
    try {
      const response = await api.post('/auth/send-phone-verification', {
        userId: data.userId,
      });

      const result = response.data;

      return { success: true, message: result.message };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || err.message || 'An error occurred while sending phone verification.');
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
    clearSendEmailState: (state) => {
      state.isSendEmailLoading = false;
      state.sendEmailSuccess = false;
      state.sendEmailError = null;
    },
    clearSendPhoneState: (state) => {
      state.isSendPhoneLoading = false;
      state.sendPhoneSuccess = false;
      state.sendPhoneError = null;
    },
    abortRegistrationFlow: (state) => {
      state.tempUser = null;
      state.registrationStep = null;
      state.registerSuccess = false;
      state.verifySuccess = false;
    },
    setRegistrationStep: (state, action: PayloadAction<'email' | 'phone' | null>) => {
      state.registrationStep = action.payload;
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
        state.tempUser = null;
        state.registrationStep = null;
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
      .addCase(registerUser.fulfilled, (state, action: PayloadAction<any>) => {
        state.isRegisterLoading = false;
        state.registerSuccess = true;
        state.isAuthenticated = false; // Do not authenticate during registration
        state.user = null;
        state.tempUser = {
          userId: action.payload.userId,
          email: action.payload.email,
          phone: action.payload.phone,
        };
        state.registrationStep = 'email';
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
        state.tempUser = null;
        state.registrationStep = null;
        state.verifyError = null;
      })
      .addCase(verifyPhone.rejected, (state, action) => {
        state.isVerifyLoading = false;
        state.verifySuccess = false;
        state.verifyError = (action.payload as string) || 'Phone verification failed.';
      })
      // Send Email Verification flow
      .addCase(sendEmailVerification.pending, (state) => {
        state.isSendEmailLoading = true;
        state.sendEmailSuccess = false;
        state.sendEmailError = null;
      })
      .addCase(sendEmailVerification.fulfilled, (state) => {
        state.isSendEmailLoading = false;
        state.sendEmailSuccess = true;
        state.sendEmailError = null;
      })
      .addCase(sendEmailVerification.rejected, (state, action) => {
        state.isSendEmailLoading = false;
        state.sendEmailSuccess = false;
        state.sendEmailError = (action.payload as string) || 'Failed to send email verification.';
      })
      // Send Phone Verification flow
      .addCase(sendPhoneVerification.pending, (state) => {
        state.isSendPhoneLoading = true;
        state.sendPhoneSuccess = false;
        state.sendPhoneError = null;
      })
      .addCase(sendPhoneVerification.fulfilled, (state) => {
        state.isSendPhoneLoading = false;
        state.sendPhoneSuccess = true;
        state.registrationStep = 'phone'; // Transition step to phone
        state.sendPhoneError = null;
      })
      .addCase(sendPhoneVerification.rejected, (state, action) => {
        state.isSendPhoneLoading = false;
        state.sendPhoneSuccess = false;
        state.sendPhoneError = (action.payload as string) || 'Failed to send phone verification.';
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

export const { logout, clearError, clearResetState, clearUpdateState, clearRegisterState, clearVerifyState, clearSendEmailState, clearSendPhoneState, abortRegistrationFlow, setRegistrationStep } = authSlice.actions;
export default authSlice.reducer;
