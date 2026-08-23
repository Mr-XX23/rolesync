# Project: Role-Sync Google OAuth2 Integration

## Architecture
Role-Sync is a microservices architecture with a Spring Boot backend (Gateway, Auth-Service, Config-Service, etc.) and a React Vite frontend.
- Gateway Service listens on `:8080` and routes authentication requests.
- Auth Service handles user authentication, JWT token generation, OAuth2 flows, Kafka event publishing, and cookie management.
- Frontend React application uses Vite, React Router, and global state management for user authentication.

## Code Layout
- `backend/.env`: Environment configuration for backend services.
- `backend/auth-service/`: Auth service Spring Boot application.
  - `src/main/java/com/rolesync/authservice/configurations/`: `SecurityConfig.java`, `OAuth2AuthenticationSuccessHandler.java`, `PublicEndpointsConfig.java`, etc.
  - `src/main/java/com/rolesync/authservice/services/`: `OAuth2Service.java`, `TokenService.java`, `CookiesService.java`, etc.
  - `src/main/java/com/rolesync/authservice/controllers/`: `OAuth2Controller.java`, etc.
- `backend/config-service/`: Spring Cloud Config service properties.
- `frontend/`: React Vite application.
  - `src/pages/` / `src/components/`: `Signin.tsx`, `Register.tsx`, `OAuthCallback.tsx`.
  - `src/router/` / `src/routes/`: `router.tsx`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | credentials_config | Update backend/.env and Spring Security OAuth2 public endpoint configs in auth-service and config-service | none | DONE |
| 2 | backend_oauth2 | Edge cases in OAuth2Service & OAuth2AuthenticationSuccessHandler (account linking, auto-provisioning, Kafka event, status checks, null guard, JWT/cookie delivery) | M1 | DONE |
| 3 | frontend_oauth | Update Signin.tsx & Register.tsx buttons, create OAuthCallback.tsx in router.tsx | M2 | DONE |

## Interface Contracts
### OAuth2 Authorization Initiator
- Route: `http://localhost:8080/api/v1/auth/oauth2/authorization/google`
- Callback URL: `http://localhost:8080/api/v1/auth/oauth2/callback/google`

### Frontend OAuth Callback
- Route: `/auth/callback`
- Query Parameters: `success` (boolean), `userId` (string), `isNewUser` (boolean), `error` (string), `message` (string)
- Redirect target on success (isNewUser=true): `/auth/onboarding`
- Redirect target on success (isNewUser=false): `/workspace`
- Redirect target on failure: `/signin` with error message
