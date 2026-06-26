# Auth Service API Documentation

This document describes the REST API exposed by the `auth-service` module in the Role-Sync platform.

The service provides authentication, registration, verification, password reset, user lookup, and operational health endpoints.

---

## 1. Service Overview

**Base URL pattern**

All API routes are rooted under:

```text
/api/v1/auth
```

The service also exposes health endpoints under:

```text
/api/v1/auth/health
```

### 1.1 Common Behavior

- Most endpoints return JSON.
- `verify-email` returns an HTML page through `ModelAndView` rather than JSON.
- Some endpoints rely on cookies named `access_token` and `refresh_token`.
- Several write operations are rate-limited using the `@RateLimited` annotation.
- Validation errors are enforced with Jakarta Bean Validation annotations.
- Some endpoints require authentication/authorization at the Spring Security layer, for example `force-logout` requires the `ADMIN` role.

### 1.2 Cookie and Token Notes

The login flow stores or uses the following cookie names:

- `access_token`
- `refresh_token`

The exact cookie attributes are handled in service classes, not the controller layer.

---

## 2. Standard Response Types

### 2.1 `RegistrationResponse`

Returned by user registration, verification, and password reset related endpoints.

```json
{
  "success": true,
  "message": "...",
  "userId": "...",
  "username": "...",
  "emailVerificationSent": true,
  "smsVerificationSent": false,
  "email": "..."
}
```

Field notes:

- `success`: operation result.
- `message`: human-readable result.
- `userId`: user identifier when available.
- `username`: username when available.
- `emailVerificationSent`: indicates whether email verification was queued/sent.
- `smsVerificationSent`: indicates whether SMS verification was queued/sent.
- `email`: email address when applicable.

### 2.2 `LoginResponse`

Returned by login.

```json
{
  "message": "Login successful",
  "username": "jdoe",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "LastLoginTime": "2026-05-10T10:20:30",
  "status": "ACTIVE",
  "role": "USER",
  "statusCode": "200"
}
```

Field notes:

- `LastLoginTime` is spelled with a capital `L` in the current DTO.
- `statusCode` is returned as a string.

### 2.3 `UserDetailsResponse`

Returned by user lookup and verification endpoints.

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "username": "jdoe",
  "usernameId": "jdoe",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "role": "USER",
  "status": "ACTIVE",
  "loginType": "PASSWORD",
  "emailVerified": true,
  "phoneVerified": false,
  "mfaEnabled": false,
  "createdAt": "2026-05-01T12:00:00",
  "updatedAt": "2026-05-10T10:20:30",
  "lastLoginAt": "2026-05-10T10:20:30",
  "message": "Success",
  "success": true,
  "timestamp": 1715336430000
}
```

Notes:

- Sensitive fields such as password hashes are not included.
- `timestamp` is a numeric metadata field.

---

## 3. Authentication and Account APIs

### 3.1 Register a New User

**Endpoint**

```http
POST /api/v1/auth/register
```

**Rate limit**

- `3` requests per `300` seconds

**Purpose**

Creates a new user account using email or phone contact details.

**Request body** — `RegistrationRequest`

```json
{
  "username": "jdoe",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "password": "StrongPassword123!",
  "role": "USER",
  "acceptTerms": true,
  "hipaaPrivacyNotice": true
}
```

**Validation rules**

- `username`: required, 3–24 characters.
- `email`: must be valid if provided.
- `phoneNumber`: must match international phone format if provided.
- `password`: required, minimum 8 characters.
- `role`: required and deserialized into the application role type.
- `acceptTerms`: must be `true`.
- `hipaaPrivacyNotice`: must be `true`.

**Success response**

- HTTP `200 OK`
- Body: `RegistrationResponse`

**Example response**

```json
{
  "success": true,
  "message": "User registered successfully",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "username": "jdoe",
  "emailVerificationSent": true,
  "smsVerificationSent": false,
  "email": "jdoe@example.com"
}
```

**Common failure cases**

- Invalid field validation.
- Duplicate username, email, or phone.
- Missing terms acceptance.

---

### 3.2 Send Email Verification

**Endpoint**

```http
POST /api/v1/auth/send-email-verification
```

**Rate limit**

- `5` requests per `3600` seconds

**Purpose**

Triggers a verification email for the specified user.

**Request body** — `EmailVerificationRequest`

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Validation rules**

- `userId`: required UUID.

**Success response**

- HTTP `200 OK`
- Body: `RegistrationResponse`

**Example response**

```json
{
  "success": true,
  "message": "Verification email sent",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "emailVerificationSent": true
}
```

---

### 3.3 Send Phone Verification

**Endpoint**

```http
POST /api/v1/auth/send-phone-verification
```

**Rate limit**

- `5` requests per `3600` seconds

**Purpose**

Triggers an SMS verification message for the specified user.

**Request body** — `PhoneVerificationRequest`

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Validation rules**

- `userId`: required UUID.

**Success response**

- HTTP `200 OK`
- Body: `RegistrationResponse`

**Example response**

```json
{
  "success": true,
  "message": "Verification SMS sent",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "smsVerificationSent": true
}
```

---

### 3.4 Verify Email

**Endpoint**

```http
GET /api/v1/auth/verify-email?token={token}
```

**Purpose**

Completes email verification using a token and returns a rendered HTML page.

**Query parameters**

- `token`: required, non-blank string.

**Response type**

- `ModelAndView` rendered as HTML

**Typical behavior**

- Successful verification shows an email verification success page.
- Failed verification usually shows an error page or message depending on the service implementation.

**Example URL**

```text
/api/v1/auth/verify-email?token=eyJhbGciOiJIUzI1NiJ9...
```

---

### 3.5 Verify Phone with OTP

**Endpoint**

```http
POST /api/v1/auth/verify-phone
```

**Rate limit**

- `10` requests per `300` seconds

**Purpose**

Verifies a user’s phone number using an OTP and returns success or failure.

**Request body** — `PhoneVerificationOtpRequest`

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "otp": "123456"
}
```

**Validation rules**

- `userId`: required string.
- `otp`: required 6-digit numeric string.

**Success response**

- HTTP `200 OK` when verification succeeds.

**Failure response**

- HTTP `400 Bad Request` when the verification result indicates failure.

**Example response**

```json
{
  "success": true,
  "message": "Phone verified successfully",
  "userId": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 3.6 Request Password Reset

**Endpoint**

```http
POST /api/v1/auth/reset-password
```

**Rate limit**

- `3` requests per `3600` seconds

**Purpose**

Starts the password reset flow using an email address or phone number.

**Request body** — `PasswordResetRequest`

```json
{
  "userContact": "jdoe@example.com"
}
```

`userContact` may also be a phone number, depending on the account.

**Validation rules**

- `userContact`: required non-blank string.

**Success response**

- HTTP `200 OK`
- Body: `RegistrationResponse`

**Example response**

```json
{
  "success": true,
  "message": "Password reset instructions sent",
  "email": "jdoe@example.com"
}
```

---

### 3.7 Confirm Password Reset Using Token

**Endpoint**

```http
POST /api/v1/auth/confirm-reset
```

**Rate limit**

- `5` requests per `300` seconds

**Purpose**

Completes password reset with a reset token and new password.

**Request body** — `PasswordResetConfirmRequest`

```json
{
  "token": "reset-token-value",
  "newPassword": "NewStrongPassword123!"
}
```

**Validation rules**

- `token`: required.
- `newPassword`: required, minimum 8 characters.

**Success response**

- HTTP `200 OK` when reset succeeds.

**Failure response**

- HTTP `400 Bad Request` when the reset fails.

**Example response**

```json
{
  "success": true,
  "message": "Password reset successful"
}
```

---

### 3.8 Confirm Password Reset Using OTP

**Endpoint**

```http
POST /api/v1/auth/confirm-reset-otp
```

**Rate limit**

- `5` requests per `300` seconds

**Purpose**

Completes password reset using a contact identifier, OTP, and a new password.

**Request body** — `PasswordResetOtpConfirmRequest`

```json
{
  "userContact": "+15551234567",
  "otp": "123456",
  "newPassword": "NewStrongPassword123!"
}
```

**Validation rules**

- `userContact`: required.
- `otp`: required 6-digit string.
- `newPassword`: required, minimum 8 characters.

**Success response**

- HTTP `200 OK` when reset succeeds.

**Failure response**

- HTTP `400 Bad Request` when the reset fails.

---

## 4. Login and Session APIs

### 4.1 Login

**Endpoint**

```http
POST /api/v1/auth/login
```

**Rate limit**

- `5` requests per `300` seconds

**Purpose**

Authenticates a user using username/email and password and issues session tokens via cookies.

**Request body** — `LoginRequest`

```json
{
  "username": "jdoe",
  "password": "StrongPassword123!"
}
```

**Validation rules**

- `username`: required.
- `password`: required.

**Success response**

- HTTP `200 OK`
- Body: `LoginResponse`

**Example response**

```json
{
  "message": "Login successful",
  "username": "jdoe",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "LastLoginTime": "2026-05-10T10:20:30",
  "status": "ACTIVE",
  "role": "USER",
  "statusCode": "200"
}
```

**Behavior notes**

- The controller passes both `HttpServletResponse` and `HttpServletRequest` to the login service so cookies and audit data can be handled.
- Rate limiting exists to slow down brute-force attempts.

---

### 4.2 Verify Access Token

**Endpoint**

```http
GET /api/v1/auth/verify-token
```

**Purpose**

Checks the `access_token` cookie and returns the authenticated user details if the token is valid.

**Request requirements**

- An `access_token` cookie must be present.

**Success response**

```json
{
  "message": "Token is valid",
  "user": {
	"userId": "550e8400-e29b-41d4-a716-446655440000",
	"username": "jdoe"
  },
  "success": true,
  "timestamp": "2026-05-10T10:20:30.123"
}
```

**Failure case**

- If the `access_token` cookie is missing, the endpoint throws an `IllegalArgumentException` with message:

```text
No token provided
```

---

### 4.3 Refresh Access Token

**Endpoint**

```http
POST /api/v1/auth/refresh
```

**Rate limit**

- `10` requests per `60` seconds

**Purpose**

Uses the `refresh_token` cookie to mint a new access token.

**Request requirements**

- A `refresh_token` cookie must be present.

**Success response**

- HTTP `200 OK`
- Body: plain text or token string returned by the service layer

**Failure case**

- If the `refresh_token` cookie is missing, the endpoint throws an `IllegalArgumentException` with message:

```text
Refresh token not found
```

---

### 4.4 Logout

**Endpoint**

```http
POST /api/v1/auth/logout
```

**Purpose**

Logs out the current user and invalidates access and refresh tokens.

**Request requirements**

- Cookies are optional at the controller level, but are used if present.

**Success response**

```json
{
  "message": "Logged out successfully",
  "success": true,
  "timestamp": "2026-05-10T10:20:30.123"
}
```

**Behavior notes**

- The controller retrieves `access_token` and `refresh_token` cookies if available.
- The logout service performs the actual invalidation and cookie cleanup.

---

### 4.5 Force Logout User Sessions

**Endpoint**

```http
POST /api/v1/auth/force-logout/{userId}
```

**Authorization**

- Requires Spring Security role: `ADMIN`

**Rate limit**

- `20` requests per `60` seconds

**Purpose**

Terminates all active sessions for a target user.

**Path parameter**

- `userId`: user identifier.

**Query parameter**

- `reason` (optional): defaults to `Admin action`

**Example**

```http
POST /api/v1/auth/force-logout/550e8400-e29b-41d4-a716-446655440000?reason=Security%20incident
```

**Success response**

```text
All sessions terminated for user
```

---

## 5. User Lookup and Verification APIs

### 5.1 Get Current User Details

**Endpoint**

```http
GET /api/v1/auth/users/me
```

**Purpose**

Returns details for the currently authenticated user based on the incoming request context.

**Success response**

- HTTP `200 OK`
- Body: `UserDetailsResponse`

**Example response**

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "username": "jdoe",
  "email": "jdoe@example.com",
  "role": "USER",
  "status": "ACTIVE",
  "success": true,
  "message": "Current user details retrieved"
}
```

---

### 5.2 Search User Details

**Endpoint**

```http
POST /api/v1/auth/users/search
```

**Purpose**

Looks up a user by one of several optional identifiers.

**Request body** — `UserDetailsRequest`

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "username": "jdoe"
}
```

**Validation rules**

- `userId`: must be a UUID if provided.
- `email`: must be a valid email if provided.
- `phoneNumber`: must match international phone format if provided.
- `username`: must be 3–24 characters and contain only letters, numbers, and underscores.

**Success response**

- HTTP `200 OK`
- Body: `UserDetailsResponse`

**Example response**

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "username": "jdoe",
  "email": "jdoe@example.com",
  "phoneNumber": "+15551234567",
  "role": "USER",
  "status": "ACTIVE",
  "emailVerified": true,
  "phoneVerified": false,
  "success": true,
  "message": "User found"
}
```

---

### 5.3 Verify User Status

**Endpoint**

```http
GET /api/v1/auth/users/verify/{userId}
```

**Purpose**

Returns the verification/account status for a user by ID.

**Path parameter**

- `userId`: required and must not be blank.

**Success response**

- HTTP `200 OK`
- Body: `UserDetailsResponse`

**Example response**

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ACTIVE",
  "emailVerified": true,
  "phoneVerified": true,
  "success": true,
  "message": "User status verified"
}
```

---

## 6. Health and Readiness APIs

### 6.1 Full Health Check

**Endpoint**

```http
GET /api/v1/auth/health
```

**Purpose**

Returns a full operational health snapshot including service status, system information, memory usage, database status, active session count, and uptime.

**Success response**

```json
{
  "status": "UP",
  "timestamp": "2026-05-10T10:20:30.123Z",
  "service": "auth-service",
  "system": {
	"osName": "Windows 11",
	"osVersion": "10.0",
	"osArch": "amd64",
	"availableProcessors": 8,
	"systemLoadAverage": 1.25
  },
  "memory": {
	"heap": {
	  "used": "128.00 MB",
	  "max": "512.00 MB",
	  "committed": "256.00 MB",
	  "usagePercent": "25.00%"
	},
	"nonHeap": {
	  "used": "64.00 MB",
	  "max": "undefined"
	},
	"totalMemory": "256.00 MB",
	"freeMemory": "128.00 MB",
	"maxMemory": "512.00 MB"
  },
  "database": {
	"status": "UP",
	"version": "PostgreSQL 16.x",
	"database": "auth_service",
	"size": "12.34 MB",
	"activeConnections": 4
  },
  "activeSessions": {
	"count": 42,
	"description": "Active user accounts"
  },
  "uptime": {
	"milliseconds": 123456789,
	"formatted": "1 days, 10 hours, 17 minutes, 36 seconds"
  }
}
```

**Important implementation detail**

- The database section queries PostgreSQL-specific metadata and statistics.
- If a database query fails, the `database` object will contain `status: DOWN` and an `error` message.

---

### 6.2 Liveness Probe

**Endpoint**

```http
GET /api/v1/auth/health/live
```

**Purpose**

Lightweight liveness check to confirm the service process is running.

**Response**

```json
{
  "status": "UP",
  "check": "liveness"
}
```

---

### 6.3 Readiness Probe

**Endpoint**

```http
GET /api/v1/auth/health/ready
```

**Purpose**

Checks whether the service is ready to accept traffic by validating a database connection.

**Success response**

```json
{
  "database": "UP",
  "status": "READY",
  "check": "readiness"
}
```

**Failure response**

```json
{
  "database": "DOWN",
  "error": "...",
  "status": "NOT_READY",
  "check": "readiness"
}
```

---

## 7. OAuth2 API Status

### 7.1 OAuth2 Controller

**Base path**

```text
/api/v1/auth/oauth2
```

**Current status**

- OAuth2 endpoints are present in the controller skeleton but are currently disabled/commented out.
- No active OAuth2 routes are exposed at the moment.

**Planned use**

- The commented example indicates a future Google OAuth2 callback endpoint.

---

## 8. Error Handling Reference

This service uses standard Spring validation and runtime exceptions in several places.

### 8.1 Validation Errors

Typical causes:

- Blank required fields.
- Invalid email/phone/UUID formats.
- Password too short.
- OTP not matching the expected format.

Typical HTTP status:

- `400 Bad Request`

### 8.2 Missing Token or Cookie Errors

Examples:

- `No token provided`
- `Refresh token not found`

Typical HTTP status:

- `400 Bad Request` unless handled differently by a global exception handler.

### 8.3 Authorization Errors

Examples:

- Accessing `force-logout` without `ADMIN` role.

Typical HTTP status:

- `403 Forbidden`

### 8.4 Service or Data Source Errors

Examples:

- Database unavailable.
- Token invalid or expired.
- User not found.
- Duplicate account conflicts.

Typical HTTP status:

- `4xx` or `5xx` depending on the service-layer exception and global exception mapping.

---

## 9. Endpoint Summary

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Register a new user |
| POST | `/api/v1/auth/send-email-verification` | Send email verification |
| POST | `/api/v1/auth/send-phone-verification` | Send phone verification |
| GET | `/api/v1/auth/verify-email` | Verify email via token and render HTML page |
| POST | `/api/v1/auth/verify-phone` | Verify phone with OTP |
| POST | `/api/v1/auth/reset-password` | Start password reset |
| POST | `/api/v1/auth/confirm-reset` | Confirm password reset using token |
| POST | `/api/v1/auth/confirm-reset-otp` | Confirm password reset using OTP |
| POST | `/api/v1/auth/login` | Authenticate user and establish session |
| GET | `/api/v1/auth/verify-token` | Validate access token from cookie |
| POST | `/api/v1/auth/refresh` | Refresh access token from refresh cookie |
| POST | `/api/v1/auth/logout` | Logout current user |
| POST | `/api/v1/auth/force-logout/{userId}` | Admin-only logout of all user sessions |
| GET | `/api/v1/auth/users/me` | Get current user details |
| POST | `/api/v1/auth/users/search` | Search user details |
| GET | `/api/v1/auth/users/verify/{userId}` | Verify user status |
| GET | `/api/v1/auth/health` | Full health snapshot |
| GET | `/api/v1/auth/health/live` | Liveness probe |
| GET | `/api/v1/auth/health/ready` | Readiness probe |

---

## 10. Practical Usage Examples

### 10.1 Login Flow

1. Call `POST /api/v1/auth/login` with username and password.
2. The service authenticates the user.
3. The response may set authentication cookies.
4. Use `GET /api/v1/auth/verify-token` to confirm the session from the `access_token` cookie.
5. Use `POST /api/v1/auth/refresh` when the access token expires.

### 10.2 Registration Flow

1. Call `POST /api/v1/auth/register`.
2. If enabled by the account type, request verification email/SMS.
3. Complete email verification using `GET /api/v1/auth/verify-email`.
4. Complete phone verification using `POST /api/v1/auth/verify-phone`.

### 10.3 Password Reset Flow

1. Call `POST /api/v1/auth/reset-password` with email or phone.
2. Receive a reset token or OTP out-of-band.
3. Confirm the reset using either:
   - `POST /api/v1/auth/confirm-reset`
   - `POST /api/v1/auth/confirm-reset-otp`

---

## 11. Implementation Notes for Integrators

- Always send JSON request bodies with the `Content-Type: application/json` header.
- Handle `400` responses for validation and token problems.
- Handle `403` for admin-only actions.
- Preserve cookies when calling token verification and refresh endpoints.
- Treat `verify-email` as a browser-facing route, not a pure API JSON route.

---

## 12. Quick Reference for Request DTOs

### `LoginRequest`

- `username` — string, required
- `password` — string, required

### `RegistrationRequest`

- `username` — required
- `email` — optional but validated if present
- `phoneNumber` — optional but validated if present
- `password` — required
- `role` — required
- `acceptTerms` — required and must be `true`
- `hipaaPrivacyNotice` — required and must be `true`

### `UserDetailsRequest`

- `userId` — UUID format if provided
- `email` — email format if provided
- `phoneNumber` — phone format if provided
- `username` — 3–24 chars, letters/numbers/underscore

### `PasswordResetRequest`

- `userContact` — required

### `PasswordResetConfirmRequest`

- `token` — required
- `newPassword` — required, minimum 8 characters

### `PasswordResetOtpConfirmRequest`

- `userContact` — required
- `otp` — required 6-digit code
- `newPassword` — required, minimum 8 characters

### `EmailVerificationRequest`

- `userId` — required UUID

### `PhoneVerificationRequest`

- `userId` — required UUID

### `PhoneVerificationOtpRequest`

- `userId` — required string
- `otp` — required string

---

## 13. Final Notes

This documentation reflects the controller layer currently implemented in `auth-service`. Some exact response messages and token/cookie behaviors are delegated to service classes, so the runtime output may differ slightly depending on downstream business logic and global exception handling.

