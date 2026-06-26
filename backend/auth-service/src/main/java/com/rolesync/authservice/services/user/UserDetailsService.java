package com.medisecure.authservice.services.user;

import com.medisecure.authservice.dto.user.UserDetailsRequest;
import com.medisecure.authservice.dto.user.UserDetailsResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.exceptions.ResourceNotFoundException;
import com.medisecure.authservice.exceptions.UnauthorizedException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/**
 * Service for retrieving user details with enhanced security and performance
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class UserDetailsService {

    private final UserRepository userRepository;

    /**
     * Get user details by various lookup methods with caching
     * 
     * @param request     UserDetailsRequest
     * @param httpRequest HttpServletRequest for security logging
     * @return UserDetailsResponse
     */
    @Transactional(readOnly = true)
    @Cacheable(value = "userDetails", key = "#request.userId != null ? #request.userId : (#request.email != null ? #request.email : (#request.phoneNumber != null ? #request.phoneNumber : #request.username))", unless = "#result == null")
    public UserDetailsResponse getUserDetails(UserDetailsRequest request, HttpServletRequest httpRequest) {
        log.info("Fetching user details for request: {}", sanitizeLogData(request));

        // Validate that at least one identifier is provided
        if (!hasValidIdentifier(request)) {
            log.warn("User details request missing identifier from IP: {}", getClientIp(httpRequest));
            throw new BadRequestException(
                    "At least one identifier (userId, email, phoneNumber, or username) must be provided");
        }

        // Find user by provided identifier
        AuthUserCredentials user = findUserByIdentifier(request);

        if (user == null) {
            log.warn("User not found for request from IP: {}", getClientIp(httpRequest));
            throw new ResourceNotFoundException("User not found");
        }

        // Build and return response
        return buildUserDetailsResponse(user, true);
    }

    /**
     * Get current authenticated user details
     * 
     * @param httpRequest HttpServletRequest
     * @return UserDetailsResponse
     */
    @Transactional(readOnly = true)
    public UserDetailsResponse getCurrentUserDetails(HttpServletRequest httpRequest) {
        String username = SecurityContextHolder.getContext().getAuthentication().getName();

        if (username == null || username.equals("anonymousUser")) {
            log.warn("Unauthorized access attempt to get current user from IP: {}", getClientIp(httpRequest));
            throw new UnauthorizedException("User not authenticated");
        }

        log.info("Fetching current user details for username: {}", username);

        AuthUserCredentials user = userRepository.findByEmailOrPhoneNumber(username, username)
                .orElseThrow(() -> new ResourceNotFoundException("Current user not found"));

        return buildUserDetailsResponse(user, true);
    }

    /**
     * Get user details by user ID with role-based access control
     * Only admins or the user themselves can access
     * 
     * @param userId      String
     * @param httpRequest HttpServletRequest
     * @return UserDetailsResponse
     */
    @Transactional(readOnly = true)
    @Cacheable(value = "userDetailsById", key = "#userId", unless = "#result == null")
    public UserDetailsResponse getUserDetailsById(String userId, HttpServletRequest httpRequest) {
        log.info("Fetching user details by ID: {}", userId);

        // Validate UUID format
        UUID userUuid;
        try {
            userUuid = UUID.fromString(userId);
        } catch (IllegalArgumentException e) {
            log.warn("Invalid UUID format for userId: {} from IP: {}", userId, getClientIp(httpRequest));
            throw new BadRequestException("Invalid user ID format");
        }

        // Find user
        AuthUserCredentials user = userRepository.findById(userUuid)
                .orElseThrow(() -> {
                    log.warn("User not found for ID: {} from IP: {}", userId, getClientIp(httpRequest));
                    return new ResourceNotFoundException("User not found with ID: " + userId);
                });

        // Verify access rights
        verifyAccessRights(user, httpRequest);

        return buildUserDetailsResponse(user, true);
    }

    /**
     * Verify user status (lightweight check for external services)
     * 
     * @param userId String
     * @return UserDetailsResponse with minimal information
     */
    @Transactional(readOnly = true)
    @Cacheable(value = "userStatus", key = "#userId", unless = "#result == null")
    public UserDetailsResponse verifyUserStatus(String userId) {
        log.info("Verifying user status for ID: {}", userId);

        UUID userUuid;
        try {
            userUuid = UUID.fromString(userId);
        } catch (IllegalArgumentException e) {
            throw new BadRequestException("Invalid user ID format");
        }

        AuthUserCredentials user = userRepository.findById(userUuid)
                .orElseThrow(() -> new ResourceNotFoundException("User not found"));

        // Return minimal user info for status check
        return UserDetailsResponse.builder()
                .userId(user.getAuthUserId().toString())
                .status(user.getStatus().name())
                .emailVerified(user.isEmailVerified())
                .phoneVerified(user.isPhoneVerified())
                .role(user.getRole())
                .success(true)
                .timestamp(Instant.now().toEpochMilli())
                .build();
    }

    /**
     * Build comprehensive user details response
     */
    private UserDetailsResponse buildUserDetailsResponse(AuthUserCredentials user, boolean includeFullDetails) {
        UserDetailsResponse.UserDetailsResponseBuilder builder = UserDetailsResponse.builder()
                .userId(user.getAuthUserId().toString())
                .username(user.getUsername())
                .usernameId(user.getUsernameId())
                .role(user.getRole())
                .status(user.getStatus().name())
                .loginType(user.getLoginType().name())
                .emailVerified(user.isEmailVerified())
                .phoneVerified(user.isPhoneVerified())
                .mfaEnabled(user.isMfaEnabled())
                .success(true)
                .message("User details retrieved successfully")
                .timestamp(Instant.now().toEpochMilli());

        if (includeFullDetails) {
            builder.email(user.getEmail())
                    .phoneNumber(user.getPhoneNumber())
                    .createdAt(user.getCreatedAt())
                    .updatedAt(user.getUpdatedAt())
                    .lastLoginAt(user.getLastLoginAt());
        }

        return builder.build();
    }

    /**
     * Find user by any provided identifier
     */
    private AuthUserCredentials findUserByIdentifier(UserDetailsRequest request) {
        Optional<AuthUserCredentials> userOpt = Optional.empty();

        if (request.getUserId() != null) {
            try {
                UUID uuid = UUID.fromString(request.getUserId());
                userOpt = userRepository.findById(uuid);
            } catch (IllegalArgumentException e) {
                log.error("Invalid UUID format: {}", request.getUserId());
                throw new BadRequestException("Invalid user ID format");
            }
        } else if (request.getEmail() != null) {
            userOpt = userRepository.findByEmail(request.getEmail());
        } else if (request.getPhoneNumber() != null || request.getUsername() != null) {
            String identifier = request.getPhoneNumber() != null ? request.getPhoneNumber() : request.getUsername();
            userOpt = userRepository.findByEmailOrPhoneNumber(identifier, identifier);
        }

        return userOpt.orElse(null);
    }

    /**
     * Verify access rights - users can only access their own data unless they're
     * admin
     */
    private void verifyAccessRights(AuthUserCredentials targetUser, HttpServletRequest httpRequest) {
        String currentUsername = SecurityContextHolder.getContext().getAuthentication().getName();

        if (currentUsername == null || currentUsername.equals("anonymousUser")) {
            throw new UnauthorizedException("User not authenticated");
        }

        // Get current user
        AuthUserCredentials currentUser = userRepository.findByEmailOrPhoneNumber(currentUsername, currentUsername)
                .orElseThrow(() -> new UnauthorizedException("Current user not found"));

        // Check if user is accessing their own data or is admin/super_admin
        boolean isOwnData = currentUser.getAuthUserId().equals(targetUser.getAuthUserId());
        boolean isAdmin = currentUser.getRole().name().equals("ADMIN") ||
                currentUser.getRole().name().equals("SUPER_ADMIN");

        if (!isOwnData && !isAdmin) {
            log.warn("Unauthorized access attempt: User {} tried to access user {} data from IP: {}",
                    currentUser.getAuthUserId(), targetUser.getAuthUserId(), getClientIp(httpRequest));
            throw new UnauthorizedException("You do not have permission to access this user's details");
        }
    }

    /**
     * Check if request has at least one valid identifier
     */
    private boolean hasValidIdentifier(UserDetailsRequest request) {
        return request.getUserId() != null ||
                request.getEmail() != null ||
                request.getPhoneNumber() != null ||
                request.getUsername() != null;
    }

    /**
     * Sanitize log data to prevent log injection
     */
    private String sanitizeLogData(UserDetailsRequest request) {
        return String.format("UserDetailsRequest[userId=%s, email=%s, phone=%s, username=%s]",
                request.getUserId() != null ? "***" : "null",
                request.getEmail() != null ? maskEmail(request.getEmail()) : "null",
                request.getPhoneNumber() != null ? maskPhone(request.getPhoneNumber()) : "null",
                request.getUsername() != null ? request.getUsername() : "null");
    }

    /**
     * Mask email for logging
     */
    private String maskEmail(String email) {
        if (email == null || !email.contains("@"))
            return "***";
        String[] parts = email.split("@");
        return parts[0].substring(0, Math.min(2, parts[0].length())) + "***@" + parts[1];
    }

    /**
     * Mask phone for logging
     */
    private String maskPhone(String phone) {
        if (phone == null || phone.length() < 4)
            return "***";
        return "***" + phone.substring(phone.length() - 4);
    }

    /**
     * Get client IP address
     */
    private String getClientIp(HttpServletRequest request) {
        String xForwardedFor = request.getHeader("X-Forwarded-For");
        if (xForwardedFor != null && !xForwardedFor.isEmpty()) {
            return xForwardedFor.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
