package com.rolesync.authservice.configurations;

import com.rolesync.authservice.dto.loginregistration.OAuth2LoginResponse;
import com.rolesync.authservice.exceptions.BadRequestException;
import com.rolesync.authservice.services.OAuth2Service;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class OAuth2AuthenticationSuccessHandlerTest {

    @Mock
    private OAuth2Service oauth2Service;

    @Mock
    private HttpServletRequest request;

    @Mock
    private HttpServletResponse response;

    @Mock
    private Authentication authentication;

    @Mock
    private OAuth2User oauth2User;

    @InjectMocks
    private OAuth2AuthenticationSuccessHandler successHandler;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(successHandler, "frontendUrl", "http://localhost:3000");
    }

    @Test
    void onAuthenticationSuccess_successfulLogin_redirectsToCallbackUrl() throws IOException {
        when(authentication.getPrincipal()).thenReturn(oauth2User);
        when(oauth2User.getAttribute("email")).thenReturn("user@example.com");

        OAuth2LoginResponse loginResponse = OAuth2LoginResponse.builder()
                .accessToken("acc_token")
                .refreshToken("ref_token")
                .userId("12345678-1234-1234-1234-1234567890ab")
                .email("user@example.com")
                .name("Test User")
                .isNewUser(true)
                .message("Account created successfully")
                .build();

        when(oauth2Service.processOAuth2Login(eq(oauth2User), eq(response), eq(request))).thenReturn(loginResponse);

        successHandler.onAuthenticationSuccess(request, response, authentication);

        String expectedRedirect = "http://localhost:3000/auth/callback?success=true&userId=12345678-1234-1234-1234-1234567890ab&isNewUser=true";
        verify(response).sendRedirect(expectedRedirect);
    }

    @Test
    void onAuthenticationSuccess_exceptionThrown_redirectsToErrorUrlWithEncodedMessage() throws IOException {
        when(authentication.getPrincipal()).thenReturn(oauth2User);
        when(oauth2User.getAttribute("email")).thenReturn("user@example.com");

        when(oauth2Service.processOAuth2Login(any(), any(), any()))
                .thenThrow(new BadRequestException("Account is suspended"));

        successHandler.onAuthenticationSuccess(request, response, authentication);

        String expectedRedirect = "http://localhost:3000/login?error=oauth_failed&message=Account+is+suspended";
        verify(response).sendRedirect(expectedRedirect);
    }

    @Test
    void onAuthenticationSuccess_nullMessageException_redirectsToErrorUrlWithDefaultMessage() throws IOException {
        when(authentication.getPrincipal()).thenReturn(oauth2User);
        when(oauth2User.getAttribute("email")).thenReturn("user@example.com");

        when(oauth2Service.processOAuth2Login(any(), any(), any()))
                .thenThrow(new RuntimeException((String) null));

        successHandler.onAuthenticationSuccess(request, response, authentication);

        String expectedRedirect = "http://localhost:3000/login?error=oauth_failed&message=OAuth2+authentication+failed";
        verify(response).sendRedirect(expectedRedirect);
    }
}
