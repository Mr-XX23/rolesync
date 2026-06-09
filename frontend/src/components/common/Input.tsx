import React, { useState, forwardRef } from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
  rightElement?: React.ReactNode;
  leftElement?: React.ReactNode;
  rightElementInside?: React.ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({
  label,
  id,
  type = 'text',
  rightElement,
  leftElement,
  rightElementInside,
  onFocus,
  onBlur,
  className = '',
  ...props
}, ref) => {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <div className="space-y-1.5 text-left w-full">
      <div className="flex justify-between items-center">
        <label
          htmlFor={id}
          className={`text-sm font-medium transition-colors duration-200 block ${
            isFocused ? 'text-primary' : 'text-foreground'
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
          className={`w-full py-2.5 rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground/50 transition-all duration-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary ${
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
    </div>
  );
});

Input.displayName = 'Input';



