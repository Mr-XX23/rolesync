import { configureStore } from '@reduxjs/toolkit';
import { useDispatch, useSelector } from 'react-redux';
import type { TypedUseSelectorHook } from 'react-redux';
import { persistStore, persistReducer } from 'redux-persist';
import storage from 'redux-persist/lib/storage';
import authReducer, { logout } from './authSlice';
import roleReducer from './roleSlice';
import taskReducer from './taskSlice';
import { injectLogoutCallback } from '../api/axiosInstance';

const safeStorage = (storage as any).default || storage;

const persistConfig = {
  key: 'auth',
  storage: safeStorage,
  whitelist: ['user', 'isAuthenticated'],
};

const persistedAuthReducer = persistReducer(persistConfig, authReducer);

// Configure root store
export const store = configureStore({
  reducer: {
    auth: persistedAuthReducer,
    role: roleReducer,
    task: taskReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActions: [
          'persist/PERSIST',
          'persist/REHYDRATE',
          'persist/REGISTER',
          'persist/PURGE',
          'persist/FLUSH',
          'persist/PAUSE',
        ],
      },
    }),
});

export const persistor = persistStore(store);

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;

// Inject the store dispatch callback into Axios to break the circular import loop
injectLogoutCallback(() => {
  store.dispatch(logout());
});


