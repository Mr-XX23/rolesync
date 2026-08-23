package com.rolesync.authservice.services;

import com.rolesync.authservice.dto.loginregistration.OAuth2LoginResponse;
import com.rolesync.authservice.exceptions.BadRequestException;
import com.rolesync.authservice.exceptions.ForbiddenException;
import com.rolesync.authservice.kafka.producer.AuthEventPublisher;
import com.rolesync.authservice.models.AuthUserCredentials;
import com.rolesync.authservice.models.Role;
import com.rolesync.authservice.repository.UserRepository;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.oauth2.core.user.OAuth2User;

import java.time.LocalDateTime;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OAuth2ServiceTest {

    @Mock
    private UserRepository userRepository;

    @Mock
    private JwtService jwtService;

    @Mock
    private CookiesService cookiesService;

    @Mock
    private TokenService tokenService;

    @Mock
    private AuthSecurityEventService securityEvents;

    @Mock
    private AuthEventPublisher authEventPublisher;

    @Mock
    private EntityManager entityManager;

    @Mock
    private OAuth2User oauth2User;

    @Mock
    private HttpServletRequest request;

    @Mock
    private HttpServletResponse response;

    @InjectMocks
    private OAuth2Service oauth2Service;

    private AuthUserCredentials existingUser;
    private UUID userId;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();
        existingUser = AuthUserCredentials.builder()
                .authUserId(userId)
                .usernameId("MS_12345678")
                .username("Existing User")
                .email("test@example.com")
                .status(AuthUserCredentials.Status.ACTIVE)
                .role(Role.USER)
                .loginType(AuthUserCredentials.LoginType.EMAIL)
                .passwordHash("hashed_password")
                .createdAt(LocalDateTime.now().minusDays(1))
                .updatedAt(LocalDateTime.now().minusDays(1))
                .build();

        when(userRepository.save(any(AuthUserCredentials.class))).thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void processOAuth2Login_nullOAuth2User_throwsBadRequestException() {
        BadRequestException exception = assertThrows(BadRequestException.class, () ->
                oauth2Service.processOAuth2Login(null, response, request)
        );
        assertEquals("OAuth2 authentication failed", exception.getMessage());
    }

    @Test
    void processOAuth2Login_missingEmail_throwsBadRequestException() {
        when(oauth2User.getAttribute("email")).thenReturn(null);
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-123");

        BadRequestException exception = assertThrows(BadRequestException.class, () ->
                oauth2Service.processOAuth2Login(oauth2User, response, request)
        );
        assertEquals("Invalid Google OAuth response - missing required information", exception.getMessage());
    }

    @Test
    void processOAuth2Login_missingSub_throwsBadRequestException() {
        when(oauth2User.getAttribute("email")).thenReturn("user@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("");

        BadRequestException exception = assertThrows(BadRequestException.class, () ->
                oauth2Service.processOAuth2Login(oauth2User, response, request)
        );
        assertEquals("Invalid Google OAuth response - missing required information", exception.getMessage());
    }

    @Test
    void processOAuth2Login_accountLinking_existingUser() {
        when(oauth2User.getAttribute("email")).thenReturn("test@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-123");
        when(oauth2User.getAttribute("name")).thenReturn("Existing User");

        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(existingUser));

        when(jwtService.generateAccessToken(any(AuthUserCredentials.class))).thenReturn("access_token_123");
        when(jwtService.generateRefreshToken(any(AuthUserCredentials.class))).thenReturn("refresh_token_123");

        OAuth2LoginResponse loginResponse = oauth2Service.processOAuth2Login(oauth2User, response, request);

        assertNotNull(loginResponse);
        assertEquals("test@example.com", loginResponse.getEmail());
        assertFalse(loginResponse.isNewUser());
        assertEquals("Login successful", loginResponse.getMessage());
        assertEquals("access_token_123", loginResponse.getAccessToken());

        // Verify account linking updates
        assertEquals("google-sub-123", existingUser.getGoogleId());
        assertTrue(existingUser.isEmailVerified());

        // Verify unified sessionId passed to TokenService
        ArgumentCaptor<UUID> sessionCaptor1 = ArgumentCaptor.forClass(UUID.class);
        ArgumentCaptor<UUID> sessionCaptor2 = ArgumentCaptor.forClass(UUID.class);
        verify(tokenService).saveAccessToken(eq(userId), eq("access_token_123"), sessionCaptor1.capture());
        verify(tokenService).saveRefreshToken(eq(userId), eq("refresh_token_123"), sessionCaptor2.capture());
        assertEquals(sessionCaptor1.getValue(), sessionCaptor2.getValue());

        // Verify cookies and security event
        verify(cookiesService).setAccessTokenCookie(response, "access_token_123");
        verify(cookiesService).setRefreshTokenCookie(response, "refresh_token_123");
        verify(securityEvents).logSecurityEvent(eq(existingUser), eq("OAUTH2_LOGIN"), anyString(), eq(request));
    }

    @Test
    void processOAuth2Login_autoProvisioning_newUser() {
        when(oauth2User.getAttribute("email")).thenReturn("newuser@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-999");
        when(oauth2User.getAttribute("name")).thenReturn("New User");

        when(userRepository.findByEmail("newuser@example.com")).thenReturn(Optional.empty());
        when(userRepository.existsByUsernameId(anyString())).thenReturn(false);

        when(jwtService.generateAccessToken(any(AuthUserCredentials.class))).thenReturn("access_token_new");
        when(jwtService.generateRefreshToken(any(AuthUserCredentials.class))).thenReturn("refresh_token_new");

        OAuth2LoginResponse loginResponse = oauth2Service.processOAuth2Login(oauth2User, response, request);

        assertNotNull(loginResponse);
        assertEquals("newuser@example.com", loginResponse.getEmail());
        assertTrue(loginResponse.isNewUser());
        assertEquals("Account created successfully", loginResponse.getMessage());

        // Verify user attributes created
        ArgumentCaptor<AuthUserCredentials> userCaptor = ArgumentCaptor.forClass(AuthUserCredentials.class);
        verify(userRepository, atLeastOnce()).save(userCaptor.capture());
        AuthUserCredentials created = userCaptor.getAllValues().get(0);

        assertTrue(created.getUsernameId().startsWith("MS_"));
        assertEquals("New User", created.getUsername());
        assertEquals("google-sub-999", created.getGoogleId());
        assertTrue(created.isEmailVerified());
        assertEquals(AuthUserCredentials.Status.ACTIVE, created.getStatus());
        assertEquals(AuthUserCredentials.LoginType.THIRD_PARTY, created.getLoginType());
        assertEquals(Role.USER, created.getRole());
        assertEquals("$2a$10$OAUTH2_NO_LOCAL_PASSWORD_PLACEHOLDER", created.getPasswordHash());

        // Verify Kafka event published
        verify(authEventPublisher).publishUserRegistered(any(AuthUserCredentials.class));

        // Verify unified sessionId
        ArgumentCaptor<UUID> s1 = ArgumentCaptor.forClass(UUID.class);
        ArgumentCaptor<UUID> s2 = ArgumentCaptor.forClass(UUID.class);
        verify(tokenService).saveAccessToken(any(UUID.class), eq("access_token_new"), s1.capture());
        verify(tokenService).saveRefreshToken(any(UUID.class), eq("refresh_token_new"), s2.capture());
        assertEquals(s1.getValue(), s2.getValue());
    }

    @Test
    void processOAuth2Login_usernameTruncation_longDisplayName() {
        when(oauth2User.getAttribute("email")).thenReturn("longname@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-888");
        when(oauth2User.getAttribute("name")).thenReturn("Very Long Display Name Exceeding 20 Chars");

        when(userRepository.findByEmail("longname@example.com")).thenReturn(Optional.empty());
        when(userRepository.existsByUsernameId(anyString())).thenReturn(false);
        when(jwtService.generateAccessToken(any())).thenReturn("token");
        when(jwtService.generateRefreshToken(any())).thenReturn("token");

        oauth2Service.processOAuth2Login(oauth2User, response, request);

        ArgumentCaptor<AuthUserCredentials> userCaptor = ArgumentCaptor.forClass(AuthUserCredentials.class);
        verify(userRepository, atLeastOnce()).save(userCaptor.capture());
        AuthUserCredentials created = userCaptor.getAllValues().get(0);

        assertEquals("Very Long Display Na", created.getUsername());
        assertTrue(created.getUsername().length() <= 20);
    }

    @Test
    void processOAuth2Login_suspendedUser_throwsForbiddenException() {
        existingUser.setStatus(AuthUserCredentials.Status.SUSPENDED);

        when(oauth2User.getAttribute("email")).thenReturn("test@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-123");
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(existingUser));

        ForbiddenException exception = assertThrows(ForbiddenException.class, () ->
                oauth2Service.processOAuth2Login(oauth2User, response, request)
        );
        assertEquals("Account is suspended", exception.getMessage());
    }

    @Test
    void processOAuth2Login_lockedUser_throwsForbiddenException() {
        existingUser.setStatus(AuthUserCredentials.Status.LOCKED);

        when(oauth2User.getAttribute("email")).thenReturn("test@example.com");
        when(oauth2User.getAttribute("sub")).thenReturn("google-sub-123");
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(existingUser));

        ForbiddenException exception = assertThrows(ForbiddenException.class, () ->
                oauth2Service.processOAuth2Login(oauth2User, response, request)
        );
        assertEquals("Account is locked", exception.getMessage());
    }
}
