import React, { forwardRef } from 'react';

interface OtpInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  id: string;
}

export const OtpInput = forwardRef<HTMLInputElement, OtpInputProps>(({
  id,
  className = '',
  ...props
}, ref) => {
  return (
    <input
      ref={ref}
      id={id}
      type="text"
      maxLength={1}
      className={`w-full max-w-[48px] flex-1 min-w-0 h-12 sm:h-14 text-center text-xl font-bold border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all duration-200 ${className}`}
      {...props}
    />
  );
});

OtpInput.displayName = 'OtpInput';
