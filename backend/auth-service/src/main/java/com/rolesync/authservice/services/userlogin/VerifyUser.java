package com.medisecure.authservice.services.userlogin;

import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.JwtService;
import java.util.HashMap;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class VerifyUser {

    private final UserRepository userRepository;
    private final JwtService jwtUtil;

    public HashMap<String, Object> verifyAndGetUserDetails(String token) {
        try {
            // Decode and validate JWT token
            String userId = jwtUtil.extractUserId(token);

            if (userId == null || jwtUtil.isTokenExpired(token)) {
                throw new IllegalArgumentException("Invalid or expired token");
            }

            // Fetch user from database
            AuthUserCredentials user = userRepository.findById(UUID.fromString(userId))
                    .orElseThrow(() -> new IllegalArgumentException("User not found"));

            return (getStringObjectMap(user));

        } catch (Exception e) {
            throw new IllegalArgumentException("Token verification failed: " + e.getMessage());
        }
    }

    private static HashMap<String, Object> getStringObjectMap(AuthUserCredentials user) {
        HashMap<String, Object> userDetails = new HashMap<>();

        userDetails.put("userId", user.getAuthUserId() != null ? user.getAuthUserId().toString() : "");
        userDetails.put("username", user.getUsername() != null ? user.getUsername() : "");
        userDetails.put("role", user.getRole() != null ? user.getRole().name() : "");
        userDetails.put("status", user.getStatus() != null ? user.getStatus().name() : "");
        userDetails.put("email", user.getEmail() != null ? user.getEmail() : "");
        userDetails.put("phoneNumber", user.getPhoneNumber() != null ? user.getPhoneNumber() : "");
        userDetails.put("emailVerified", user.isEmailVerified());
        userDetails.put("phoneVerified", user.isPhoneVerified());
        userDetails.put("mfaEnabled", user.isMfaEnabled());
        userDetails.put("loginType", user.getLoginType() != null ? user.getLoginType().name() : "");
        userDetails.put("googleId", user.getGoogleId() != null ? user.getGoogleId() : "");
        return userDetails;
    }

}
