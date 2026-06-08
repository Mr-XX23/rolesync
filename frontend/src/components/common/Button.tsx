import React from 'react';
import { Loader2 } from 'lucide-react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'outline';
  isLoading?: boolean;
  icon?: React.ReactNode;
  loadingText?: string;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  isLoading = false,
  icon,
  loadingText,
  className = '',
  disabled,
  type = 'button',
  ...props
}) => {
  const hasPadding = className.includes('py-') || className.includes('px-') || className.includes('p-');
  const hasWidth = className.includes('w-');

  const baseStyle =
    'flex items-center justify-center gap-2 font-semibold rounded-lg transition-all active:scale-[0.98] text-sm cursor-pointer disabled:opacity-70 disabled:cursor-not-allowed disabled:active:scale-100 whitespace-nowrap';
  
  const variants = {
    primary: `bg-primary hover:opacity-90 text-primary-foreground ${hasPadding ? '' : 'py-3 px-4'} ${hasWidth ? '' : 'w-full'}`,
    outline: `border border-border hover:bg-background text-foreground ${hasPadding ? '' : 'py-3 px-4'}`,
  };

  return (
    <button
      type={type}
      disabled={disabled || isLoading}
      className={`${baseStyle} ${variants[variant]} ${className}`}
      {...props}
    >
      {isLoading ? (
        <>
          <Loader2 className="w-[18px] h-[18px] animate-spin" />
          <span>{loadingText || 'Processing...'}</span>
        </>
      ) : (
        <>
          {children}
          {icon && <span className="flex items-center">{icon}</span>}
        </>
      )}
    </button>
  );
};
