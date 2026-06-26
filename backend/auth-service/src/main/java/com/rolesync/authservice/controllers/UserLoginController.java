package com.medisecure.authservice.controllers;

import com.medisecure.authservice.annotations.RateLimited;
import com.medisecure.authservice.dto.CookieUtil;
import com.medisecure.authservice.dto.loginregistration.LoginRequest;
import com.medisecure.authservice.dto.loginregistration.LoginResponse;
import com.medisecure.authservice.services.userlogin.Logout;
import com.medisecure.authservice.services.userlogin.RefreshToken;
import com.medisecure.authservice.services.userlogin.UserLogin;
import com.medisecure.authservice.services.userlogin.VerifyUser;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class UserLoginController {

    private final UserLogin userLogin;
    private final RefreshToken refreshTokenService;
    private final Logout logoutService;
    private final VerifyUser verifyUserService;

    /**
     * Login a user with username and password.
     * 
     * @param response HttpServletResponse, request HttpServletRequest, username
     *                 String, password String , The registration request containing
     *                 user details.
     * @return A LoginResponse entity with login status, jwt token and details.
     */
    @PostMapping("/login")
    @RateLimited(maxRequests = 5, windowSeconds = 300, message = "Too many login attempts. Please try again in 5 minutes.")
    public ResponseEntity<LoginResponse> loginUser(HttpServletResponse response, HttpServletRequest request,
            @RequestBody @Valid LoginRequest loginRequest) {
        LoginResponse loginResponse = userLogin.loginUsers(loginRequest.getUsername(), loginRequest.getPassword(),
                response, request);
        return ResponseEntity.ok(loginResponse);
    }

    /**
     * Verify if the access token is valid and return user details.
     * 
     * @param request HttpServletRequest
     * @return A response entity with user details if token is valid.
     */
    @GetMapping("/verify-token")
    public ResponseEntity<Map<String, Object>> verifyToken(HttpServletRequest request) {

        String accessToken = CookieUtil.getCookieValue(request, "access_token")
                .orElseThrow(() -> new IllegalArgumentException("No token provided"));

        Map<String, Object> userDetails = verifyUserService.verifyAndGetUserDetails(accessToken);

        Map<String, Object> responseBody = Map.of(
                "message", "Token is valid",
                "user", userDetails,
                "success", true,
                "timestamp", LocalDateTime.now().toString());

        return ResponseEntity.ok(responseBody);
    }

    /**
     * Refresh access token using refresh token.
     * 
     * @param response HttpServletResponse, request HttpServletRequest
     * @return A response entity with new access token.
     */
    @PostMapping("/refresh")
    @RateLimited(maxRequests = 10, windowSeconds = 60, message = "Too many refresh requests. Please wait a moment.")
    public ResponseEntity<String> refreshToken(HttpServletRequest request, HttpServletResponse response) {

        String refreshToken = CookieUtil.getCookieValue(request, "refresh_token")
                .orElseThrow(() -> new IllegalArgumentException("Refresh token not found"));

        String newAccessToken = refreshTokenService.refreshAccessToken(refreshToken, response, request);
        return ResponseEntity.ok(newAccessToken);
    }

    /**
     * Logout user by invalidating tokens.
     * 
     * @param response HttpServletResponse, request HttpServletRequest
     * @return A response entity with logout status.
     */
    @PostMapping("/logout")
    public ResponseEntity<Map<String, Object>> logout(
            HttpServletRequest request,
            HttpServletResponse response) {

        String accessToken = CookieUtil.getCookieValue(request, "access_token").orElse(null);
        String refreshToken = CookieUtil.getCookieValue(request, "refresh_token").orElse(null);

        String res = logoutService.logout(accessToken, refreshToken, request, response);

        Map<String, Object> responseBody = Map.of(
                "message", res,
                "success", true,
                "timestamp", LocalDateTime.now().toString());

        return ResponseEntity.ok(responseBody);
    }

    /**
     * Force logout user by invalidating all their tokens.
     * ADMIN ONLY endpoint - requires ADMIN role.
     * 
     * @param userId The ID of the user to force logout.
     * @param reason The reason for force logout.
     * @return A response entity with logout status.
     */
    @PostMapping("/force-logout/{userId}")
    @PreAuthorize("hasRole('ADMIN')")
    @RateLimited(maxRequests = 20, windowSeconds = 60, message = "Too many force logout requests. Please wait.")
    public ResponseEntity<String> forceLogout(
            @PathVariable String userId,
            @RequestParam(defaultValue = "Admin action") String reason) {

        logoutService.forceLogoutAllSessions(userId, reason);

        return ResponseEntity.ok("All sessions terminated for user");
    }
}
