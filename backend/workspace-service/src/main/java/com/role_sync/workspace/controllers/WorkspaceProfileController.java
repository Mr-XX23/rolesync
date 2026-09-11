package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.OnboardingStepRequest;
import com.role_sync.workspace.dto.PreferencesRequest;
import com.role_sync.workspace.dto.WorkspaceProfileRequest;
import com.role_sync.workspace.models.OnboardingState;
import com.role_sync.workspace.models.WorkspacePreferences;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.services.CloudinaryService;
import com.role_sync.workspace.services.WorkspaceProfileService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/workspaces/profile")
@RequiredArgsConstructor
public class WorkspaceProfileController {

    private final WorkspaceProfileService workspaceProfileService;
    private final CloudinaryService cloudinaryService;

    @PostMapping(value = "/avatar", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Mono<ResponseEntity<Map<String, Object>>> uploadAvatar(
            @RequestPart("file") FilePart filePart,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return cloudinaryService.uploadAvatar(filePart, authUserId.toString())
                .flatMap(url -> workspaceProfileService.updateAvatarUrl(authUserId, url)
                        .thenReturn(url))
                .map(url -> ResponseEntity.ok(Map.of(
                        "avatar_url", url,
                        "message", "Profile photo uploaded successfully"
                )));
    }

    @PostMapping("/avatar/url")
    public Mono<ResponseEntity<Map<String, Object>>> uploadAvatarFromUrl(
            @RequestBody Map<String, String> body,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        String url = body.get("url");
        if (url == null || url.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Missing 'url' parameter in request body");
        }
        return cloudinaryService.uploadImageUrl(url, authUserId.toString())
                .flatMap(hostedUrl -> workspaceProfileService.updateAvatarUrl(authUserId, hostedUrl)
                        .thenReturn(hostedUrl))
                .map(hostedUrl -> ResponseEntity.ok(Map.of(
                        "avatar_url", hostedUrl,
                        "message", "Image processed and saved successfully"
                )));
    }

    @PostMapping
    public Mono<ResponseEntity<Map<String, Object>>> createOrUpdateProfile(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody WorkspaceProfileRequest request) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.createOrUpdateProfile(authUserId, request)
                .map(profile -> ResponseEntity.status(HttpStatus.CREATED)
                        .body(Map.of(
                                "profile_id", profile.getProfileId(),
                                "message", "Workspace profile processed successfully"
                        )));
    }

    @GetMapping
    public Mono<ResponseEntity<WorkspaceProfile>> getProfile(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.getProfile(authUserId)
                .map(ResponseEntity::ok);
    }

    @GetMapping("/preferences")
    public Mono<ResponseEntity<WorkspacePreferences>> getPreferences(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.getPreferences(authUserId)
                .map(ResponseEntity::ok);
    }

    @GetMapping("/onboarding")
    public Mono<ResponseEntity<OnboardingState>> getOnboardingState(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.getOnboardingState(authUserId)
                .map(ResponseEntity::ok);
    }

    @PutMapping("/preferences")
    public Mono<ResponseEntity<WorkspacePreferences>> updatePreferences(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @RequestBody PreferencesRequest request) {
        
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.updatePreferences(authUserId, request)
                .map(ResponseEntity::ok);
    }

    @PutMapping("/onboarding/step")
    public Mono<ResponseEntity<OnboardingState>> updateOnboardingStep(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @RequestBody OnboardingStepRequest request) {
        
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceProfileService.updateOnboardingStep(authUserId, request)
                .map(ResponseEntity::ok);
    }

    private UUID resolveAuthUserId(String userIdHeader, String authUserIdHeader) {
        String idStr = userIdHeader != null ? userIdHeader : authUserIdHeader;
        if (idStr == null || idStr.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, 
                    "Missing user identification header (X-User-Id or X-Auth-User-Id)");
        }
        try {
            return UUID.fromString(idStr);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, 
                    "Invalid UUID format in user identification header");
        }
    }
}
