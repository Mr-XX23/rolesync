import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { ThemeProvider } from './components/ThemeProvider';
import { ThemeToggle } from './components/ThemeToggle';

const App = () => {
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
