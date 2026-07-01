import React, { createContext, useContext, useEffect, useState } from 'react';
import { useAppDispatch, useAppSelector } from '../store';
import { updateThemePreference } from '../store/workspaceSlice';

type Theme = 'light' | 'dark' | 'system';

interface ThemeProviderProps {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
}

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const ThemeProvider: React.FC<ThemeProviderProps> = ({
  children,
  defaultTheme = 'system',
  storageKey = 'rolesync-theme',
}) => {
  const dispatch = useAppDispatch();
  const { preferences } = useAppSelector((state) => state.workspace);
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(storageKey) as Theme) || defaultTheme
  );

  useEffect(() => {
    const root = window.document.documentElement;

    // Helper to apply classes
    const applyTheme = (resolvedTheme: 'light' | 'dark') => {
      root.classList.remove('light', 'dark');
      root.classList.add(resolvedTheme);
    };

    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      
      const handleSystemChange = () => {
        applyTheme(mediaQuery.matches ? 'dark' : 'light');
      };

      // Set initial
      handleSystemChange();

      // Listen for OS theme shifts
      mediaQuery.addEventListener('change', handleSystemChange);
      return () => {
        mediaQuery.removeEventListener('change', handleSystemChange);
      };
    } else {
      applyTheme(theme);
    }
  }, [theme]);

  useEffect(() => {
    if (preferences && preferences.theme) {
      setThemeState(preferences.theme as Theme);
    }
  }, [preferences]);

  const setTheme = (newTheme: Theme) => {
    localStorage.setItem(storageKey, newTheme);
    setThemeState(newTheme);
    if (isAuthenticated) {
      dispatch(updateThemePreference(newTheme));
    }
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
