package com.medisecure.authservice.services.userlogin;

import com.medisecure.authservice.dto.loginregistration.LoginResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.exceptions.ForbiddenException;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.services.AccountLockoutService;
import com.medisecure.authservice.services.CookiesService;
import com.medisecure.authservice.services.JwtService;
import com.medisecure.authservice.services.TokenService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Set;

@Service
@RequiredArgsConstructor
@Slf4j
public class UserLogin {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    private final JwtService jwtService;
    private final TokenService tokenService;
    private final CookiesService cookiesService;
    private final LoginUtilities loginUtilities;
    private final AccountLockoutService accountLockoutService;

    // Login Users
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public LoginResponse loginUsers(@NotBlank(message = "Username is needed") String username,
            @NotBlank(message = "Password is needed") String password, HttpServletResponse response,
            HttpServletRequest request) {

        try {

            String ipAddress = loginUtilities.getClientIpAddress(request);
            String userAgent = request.getHeader("User-Agent");

            // Check if username or password is blank or null
            if (username == null || username.isBlank() || password == null || password.isBlank()) {
                log.error("Username or password is blank");
                loginUtilities.saveLoginEvent(null, "FAILED_LOGIN", "Blank username or password", ipAddress, userAgent);
                throw new BadRequestException("Username or password cannot be blank");
            }

            // SECURITY: Check if account is locked due to failed attempts
            if (accountLockoutService.isAccountLocked(username)) {
                long minutesLeft = accountLockoutService.getMinutesUntilUnlock(username);
                log.warn("Login attempted for locked account: {}. Unlock in {} minutes", username, minutesLeft);
                loginUtilities.saveLoginEvent(null, "FAILED_LOGIN_LOCKED", "Account temporarily locked", ipAddress,
                        userAgent);
                throw new ForbiddenException(String.format(
                        "Account temporarily locked due to too many failed attempts. Try again in %d minutes.",
                        minutesLeft));
            }

            // check if user is existing in the database
            AuthUserCredentials user = userRepository.findByEmailOrPhoneNumber(username, username)
                    .orElseThrow(() -> {
                        log.error("User not found with username: {}", username);
                        loginUtilities.saveLoginEvent(null, "FAILED_LOGIN", "User not found", ipAddress, userAgent);
                        accountLockoutService.recordFailedAttempt(username); // Record attempt
                        return new BadRequestException("Invalid username or password");
                    });

            // check password with hashed password in the database
            if (!passwordEncoder.matches(password, user.getPasswordHash())) {
                log.error("Invalid password for user: {}", username);
                loginUtilities.saveLoginEvent(user, "FAILED_LOGIN", "Invalid password attempt", ipAddress, userAgent);
                accountLockoutService.recordFailedAttempt(username); // Record failed attempt

                int attempts = accountLockoutService.getFailedAttempts(username);
                log.warn("Failed login attempt {} for user: {}", attempts, username);

                throw new BadRequestException("Invalid credentials");
            }

            // Check if user account is verified
            if (!isUserVerified(user)) {
                log.error("User account not verified: {}", username);
                loginUtilities.saveLoginEvent(user, "FAILED_LOGIN", "Account not verified", ipAddress, userAgent);
                throw new ForbiddenException("Account not verified");
            }

            // check user status ( suspended, locked)
            if (Set.of(AuthUserCredentials.Status.LOCKED, AuthUserCredentials.Status.SUSPENDED)
                    .contains(user.getStatus())) {
                log.error("User account is locked or suspended: {}", username);
                loginUtilities.saveLoginEvent(user, "FAILED_LOGIN", "Account is locked or suspended", ipAddress,
                        userAgent);
                throw new ForbiddenException("Account is blocked or suspended");
            }

            // Generate access token (7 days) and refresh token (30 days)
            String accessToken = jwtService.generateAccessToken(user);
            String refreshToken = jwtService.generateRefreshToken(user);

            // Save tokens in database
            tokenService.saveAccessToken(user.getAuthUserId(), accessToken);
            tokenService.saveRefreshToken(user.getAuthUserId(), refreshToken);

            // SECURITY: Reset failed login attempts after successful login
            accountLockoutService.resetFailedAttempts(username);

            // Update last login timestamp
            user.setLastLoginAt(LocalDateTime.now());
            userRepository.save(user);

            // Set HttpOnly cookies
            cookiesService.setAccessTokenCookie(response, accessToken);
            cookiesService.setRefreshTokenCookie(response, refreshToken);

            // Save successful login log
            loginUtilities.saveLoginEvent(user, "SUCCESSFUL_LOGIN", "User logged in successfully", ipAddress,
                    userAgent);

            // Prepare response
            LoginResponse loginResponse = getLoginResponse(user);

            log.info("User {} logged in successfully", username);
            return loginResponse;
        } catch (RuntimeException e) {
            throw new RuntimeException(e);
        }
    }

    private static LoginResponse getLoginResponse(AuthUserCredentials user) {
        LoginResponse loginResponse = new LoginResponse();
        loginResponse.setMessage("Login successful");
        loginResponse.setUsername(user.getUsername());
        loginResponse.setUserId(String.valueOf(user.getAuthUserId()));
        loginResponse.setEmail(user.getEmail());
        loginResponse.setPhoneNumber(user.getPhoneNumber());
        loginResponse.setStatus(user.getStatus().name());
        loginResponse.setRole(String.valueOf(user.getRole()));
        loginResponse.setLastLoginTime(String.valueOf(user.getLastLoginAt()));
        return loginResponse;
    }

    // Check if user is verified
    private boolean isUserVerified(AuthUserCredentials user) {
        return user.isEmailVerified() || user.isPhoneVerified();
    }

}
