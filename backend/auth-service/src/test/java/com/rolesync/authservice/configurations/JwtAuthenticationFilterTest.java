package com.rolesync.authservice.configurations;

import com.rolesync.authservice.services.JwtService;
import com.rolesync.authservice.services.TokenService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.io.IOException;

import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class JwtAuthenticationFilterTest {

    @Mock
    private JwtService jwtService;

    @Mock
    private TokenService tokenService;

    @Mock
    private HttpServletRequest request;

    @Mock
    private HttpServletResponse response;

    @Mock
    private FilterChain filterChain;

    private JwtAuthenticationFilter filter;

    @BeforeEach
    void setUp() {
        String[] publicEndpoints = new String[]{
                "/api/v1/auth/login",
                "/api/v1/auth/register",
                "/api/v1/auth/oauth2/**",
                "/oauth2/**"
        };
        filter = new JwtAuthenticationFilter(jwtService, tokenService, publicEndpoints);
    }

    @Test
    void doFilterInternal_ShouldSkipJwtValidationForWildcardPublicEndpoints() throws ServletException, IOException {
        when(request.getRequestURI()).thenReturn("/api/v1/auth/oauth2/authorization/google");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain, times(1)).doFilter(request, response);
        verifyNoInteractions(jwtService);
        verifyNoInteractions(tokenService);
    }

    @Test
    void doFilterInternal_ShouldSkipJwtValidationForOtherOAuth2Wildcard() throws ServletException, IOException {
        when(request.getRequestURI()).thenReturn("/oauth2/authorization/google");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain, times(1)).doFilter(request, response);
        verifyNoInteractions(jwtService);
        verifyNoInteractions(tokenService);
    }
}
