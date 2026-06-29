import { useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { ThemeProvider } from './components/ThemeProvider';
import { ThemeToggle } from './components/ThemeToggle';
import { useAppDispatch, useAppSelector } from './store';
import { checkSession, skipSessionCheck } from './store/authSlice';

const App = () => {
  const dispatch = useAppDispatch();
  const { isCheckingSession, isAuthenticated } = useAppSelector((state) => state.auth);

  useEffect(() => {
    if (isAuthenticated) {
      dispatch(checkSession());
    } else {
      dispatch(skipSessionCheck());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isCheckingSession) {
    return (
      <ThemeProvider>
        <div className="flex flex-col items-center justify-center min-h-screen bg-background text-foreground">
          <div className="relative flex flex-col items-center gap-6">
            <div className="relative w-16 h-16">
              {/* Outer ring */}
              <div className="absolute inset-0 border-4 border-primary/15 rounded-full"></div>
              {/* Spinning sector */}
              <div className="absolute inset-0 border-4 border-transparent border-t-primary rounded-full animate-spin"></div>
            </div>
            <div className="flex flex-col items-center text-center space-y-1.5 animate-pulse">
              <h3 className="font-serif text-lg font-bold tracking-wide text-foreground">
                Initializing RoleSync
              </h3>
              <p className="text-xs text-muted-foreground max-w-[260px]">
                Securing AI synchronization pipelines...
              </p>
            </div>
          </div>
        </div>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider>
      <div className="relative min-h-screen bg-background text-foreground transition-colors duration-300">
        <RouterProvider router={router} />
        <ThemeToggle />
      </div>
    </ThemeProvider>
  );
};

export default App;
