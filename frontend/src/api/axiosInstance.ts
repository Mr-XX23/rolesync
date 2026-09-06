import axios from 'axios';

let logoutCallback: (() => void) | null = null;
let activeUserId: string | null = null;

export const injectLogoutCallback = (cb: () => void) => {
  logoutCallback = cb;
};

export const injectUserId = (userId: string | null) => {
  activeUserId = userId;
};

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

api.interceptors.request.use(
  (config) => {
    if (activeUserId) {
      config.headers['X-User-Id'] = activeUserId;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value?: any) => void;
  reject: (reason?: any) => void;
}> = [];

const processQueue = (error: any) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve();
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (!originalRequest) {
      return Promise.reject(error);
    }

    const requestUrl = originalRequest.url || '';
    const isRefreshEndpoint = requestUrl.includes('/auth/refresh');

    // If 401 occurs on /auth/refresh itself, refresh token is invalid/expired -> logout
    if (isRefreshEndpoint && error.response?.status === 401) {
      if (logoutCallback) {
        logoutCallback();
      }
      return Promise.reject(error);
    }

    // Check if error is 401 and request has not been retried yet
    if (error.response?.status === 401 && !originalRequest._retry && !isRefreshEndpoint) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => {
            originalRequest._retry = true;
            return api(originalRequest);
          })
          .catch((err) => {
            return Promise.reject(err);
          });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // Request a new access token via refresh token cookie
        await api.post('/auth/refresh');
        
        isRefreshing = false;
        processQueue(null);
        
        return api(originalRequest);
      } catch (refreshError: any) {
        isRefreshing = false;
        processQueue(refreshError);
        
        // Refresh failed: ONLY logout user if the server explicitly rejected the refresh token (401 or 403)
        // Temporary network or 5xx server errors must NOT log the user out
        if (
          refreshError.response?.status === 401 ||
          refreshError.response?.status === 403
        ) {
          if (logoutCallback) {
            logoutCallback();
          }
        }
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
