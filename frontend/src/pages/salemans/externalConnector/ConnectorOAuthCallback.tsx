import React, { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { CheckCircle2, AlertCircle, Loader2, ArrowRight } from 'lucide-react';
import { Button } from '../../../components/common/Button';

export const ConnectorOAuthCallback: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [isClosing, setIsClosing] = useState<boolean>(true);
  const [isError, setIsError] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('Verifying authorization with RoleSync...');

  useEffect(() => {
    const status = searchParams.get('status');
    const sourceParam =
      searchParams.get('source') ||
      searchParams.get('appName') ||
      searchParams.get('toolkit') ||
      searchParams.get('app') ||
      sessionStorage.getItem('rolesync_oauth_connecting_source') ||
      localStorage.getItem('rolesync_oauth_connecting_source') ||
      '';

    let appName = sourceParam.toLowerCase().trim();
    if (appName === 'googledrive' || appName === 'google_drive') {
      appName = 'gdrive';
    } else if (appName === 'googlecalendar' || appName === 'google_calendar') {
      appName = 'calendar';
    }

    const connectedAccountId = searchParams.get('connectedAccountId');
    const errorParam = searchParams.get('error');

    if (errorParam || (status && status.toLowerCase() === 'failed')) {
      setIsError(true);
      setStatusMessage(errorParam || 'Authorization was cancelled or failed.');
      setIsClosing(false);
      return;
    }

    setStatusMessage('Authorization verified! Closing window and returning to RoleSync...');

    // 1. Notify Parent/Opener Window
    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(
          {
            type: 'ROLESYNC_CONNECTOR_AUTH_SUCCESS',
            source: appName,
            connectedAccountId: connectedAccountId,
            status: 'success',
          },
          window.location.origin
        );
      }
    } catch (err) {
      console.warn('[OAuthCallback] Could not postMessage to opener:', err);
    }


    // 2. Automatically close popup window after a brief moment
    const closeTimer = setTimeout(() => {
      try {
        if (window.opener) {
          window.close();
        }
      } catch (e) {
        console.warn('[OAuthCallback] window.close() blocked by browser:', e);
      }
      setIsClosing(false);
    }, 600);

    return () => clearTimeout(closeTimer);
  }, [searchParams]);

  const handleManualReturn = () => {
    navigate('/salesman/external-connector', { replace: true });
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center p-4">
      <div className="bg-card border border-border rounded-2xl p-8 shadow-xl max-w-sm w-full text-center space-y-4 animate-in zoom-in-95 duration-200">
        {isError ? (
          <>
            <div className="w-12 h-12 rounded-2xl bg-destructive/10 border border-destructive/20 text-destructive flex items-center justify-center mx-auto">
              <AlertCircle className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h3 className="font-serif text-lg font-bold text-foreground">Connection Incomplete</h3>
              <p className="text-xs text-muted-foreground">{statusMessage}</p>
            </div>
            <Button variant="outline" className="w-full text-xs" onClick={handleManualReturn}>
              Return to Connectors
            </Button>
          </>
        ) : (
          <>
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto">
              {isClosing ? (
                <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
              ) : (
                <CheckCircle2 className="w-6 h-6" />
              )}
            </div>
            <div className="space-y-1">
              <h3 className="font-serif text-lg font-bold text-foreground">Authorization Complete</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">{statusMessage}</p>
            </div>
            {!isClosing && (
              <Button variant="primary" className="w-full text-xs flex items-center justify-center gap-1.5" onClick={handleManualReturn}>
                <span>Return to RoleSync</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default ConnectorOAuthCallback;
