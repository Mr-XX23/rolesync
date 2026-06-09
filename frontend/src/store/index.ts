import { configureStore } from '@reduxjs/toolkit';
import { useDispatch, useSelector } from 'react-redux';
import type { TypedUseSelectorHook } from 'react-redux';
import authReducer from './authSlice';
import roleReducer from './roleSlice';
import taskReducer from './taskSlice';

// Configure root store
export const store = configureStore({
  reducer: {
    auth: authReducer,
    role: roleReducer,
    task: taskReducer,
  },
});

  export type RootState = ReturnType<typeof store.getState>;
  export type AppDispatch = typeof store.dispatch;

  export const useAppDispatch = () => useDispatch<AppDispatch>();
  export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;


