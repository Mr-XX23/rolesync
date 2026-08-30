import React, { useState, forwardRef } from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
  rightElement?: React.ReactNode;
  leftElement?: React.ReactNode;
  rightElementInside?: React.ReactNode;
  error?: string;
  helperText?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({
  label,
  id,
  type = 'text',
  rightElement,
  leftElement,
  rightElementInside,
  error,
  helperText,
  onFocus,
  onBlur,
  className = '',
  ...props
}, ref) => {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <div className="space-y-1 text-left w-full">
      <div className="flex justify-between items-center">
        <label
          htmlFor={id}
          className={`text-xs font-mono font-bold uppercase tracking-wider transition-colors duration-200 block ${
            error ? 'text-destructive' : isFocused ? 'text-primary' : 'text-muted-foreground'
          }`}
        >
          {label}
        </label>
        {rightElement}
      </div>
      <div className="relative flex items-center w-full">
        {leftElement && (
          <div className="absolute left-3.5 flex items-center pointer-events-none text-muted-foreground/80">
            {leftElement}
          </div>
        )}
        <input
          ref={ref}
          id={id}
          type={type}
          className={`w-full py-2.5 rounded-xl border bg-background text-foreground placeholder:text-muted-foreground/50 transition-all duration-200 text-sm focus:outline-none ${
            error
              ? 'border-destructive focus:border-destructive focus:ring-2 focus:ring-destructive/10'
              : 'border-border focus:ring-2 focus:ring-primary/10 focus:border-primary'
          } ${
            leftElement ? 'pl-10' : 'pl-4'
          } ${
            rightElementInside ? 'pr-10' : 'pr-4'
          } ${className}`}
          onFocus={(e) => {
            setIsFocused(true);
            if (onFocus) onFocus(e);
          }}
          onBlur={(e) => {
            setIsFocused(false);
            if (onBlur) onBlur(e);
          }}
          {...props}
        />
        {rightElementInside && (
          <div className="absolute right-3.5 flex items-center">
            {rightElementInside}
          </div>
        )}
      </div>
      {error && (
        <p className="text-[11px] text-destructive font-medium pl-1 animate-in fade-in duration-200">
          {error}
        </p>
      )}
      {!error && helperText && (
        <p className="text-[11px] text-muted-foreground pl-1">
          {helperText}
        </p>
      )}
    </div>
  );
});

Input.displayName = 'Input';



