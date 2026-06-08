import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

export type RolePack = 'sales' | 'teacher' | 'student';

interface RoleState {
  activeRolePack: RolePack | null;
  availableRoles: RolePack[];
}

const initialState: RoleState = {
  activeRolePack: (localStorage.getItem('rolesync-active-role') as RolePack) || null,
  availableRoles: ['sales', 'teacher', 'student'],
};

const roleSlice = createSlice({
  name: 'role',
  initialState,
  reducers: {
    setActiveRole: (state, action: PayloadAction<RolePack | null>) => {
      state.activeRolePack = action.payload;
      if (action.payload) {
        localStorage.setItem('rolesync-active-role', action.payload);
      } else {
        localStorage.removeItem('rolesync-active-role');
      }
    },
    clearActiveRole: (state) => {
      state.activeRolePack = null;
      localStorage.removeItem('rolesync-active-role');
    },
  },
});

export const { setActiveRole, clearActiveRole } = roleSlice.actions;
export default roleSlice.reducer;
