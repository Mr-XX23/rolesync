package com.medisecure.authservice.configurations;

import com.medisecure.authservice.dto.loginregistration.OAuth2LoginResponse;
import com.medisecure.authservice.services.OAuth2Service;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

@Slf4j
@Component
@RequiredArgsConstructor
public class OAuth2AuthenticationSuccessHandler implements AuthenticationSuccessHandler {

    private final OAuth2Service oauth2Service;

    @Value("${app.frontend.url:http://localhost:3000}")
    private String frontendUrl;

    @Override
    public void onAuthenticationSuccess(
            HttpServletRequest request,
            HttpServletResponse response,
            Authentication authentication) throws IOException {

        OAuth2User oauth2User = (OAuth2User) authentication.getPrincipal();

        try {
            log.info("OAuth2 authentication successful for user: {}",
                    (Object) oauth2User.getAttribute("email"));

            // Process OAuth2 login and generate tokens
            OAuth2LoginResponse loginResponse = oauth2Service.processOAuth2Login(
                    oauth2User, response, request);

            // Redirect to frontend with success
            String redirectUrl = String.format(
                    "%s/auth/callback?success=true&userId=%s&isNewUser=%s",
                    frontendUrl,
                    URLEncoder.encode(loginResponse.getUserId(), StandardCharsets.UTF_8),
                    loginResponse.isNewUser()
            );

            log.info("Redirecting to: {}", redirectUrl);
            response.sendRedirect(redirectUrl);

        } catch (Exception e) {
            log.error("OAuth2 authentication processing failed: {}", e.getMessage(), e);

            String errorUrl = String.format(
                    "%s/login?error=oauth_failed&message=%s",
                    frontendUrl,
                    URLEncoder.encode(e.getMessage(), StandardCharsets.UTF_8)
            );

            response.sendRedirect(errorUrl);
        }
    }
}
