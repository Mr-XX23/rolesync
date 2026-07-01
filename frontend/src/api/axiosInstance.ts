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
let failedQueue: any[] = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Check if error is 401 and request has not been retried yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Avoid infinite loop if refresh itself fails with 401
      if (originalRequest.url === '/auth/refresh') {
        if (logoutCallback) {
          logoutCallback();
        }
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => {
            return api(originalRequest);
          })
          .catch((err) => {
            return Promise.reject(err);
          });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // Request a new access token
        const response = await api.post('/auth/refresh');
        const newAccessToken = response.data;
        
        processQueue(null, newAccessToken);
        isRefreshing = false;
        
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        isRefreshing = false;
        
        // Refresh failed (e.g. refresh token expired/revoked) -> Logout user
        if (logoutCallback) {
          logoutCallback();
        }
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
