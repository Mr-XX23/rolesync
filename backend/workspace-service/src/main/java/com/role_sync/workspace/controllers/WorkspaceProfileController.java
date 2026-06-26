package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.OnboardingStepRequest;
import com.role_sync.workspace.dto.PreferencesRequest;
import com.role_sync.workspace.dto.WorkspaceProfileRequest;
import com.role_sync.workspace.models.OnboardingState;
import com.role_sync.workspace.models.WorkspacePreferences;
import com.role_sync.workspace.services.WorkspaceProfileService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
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

    @PostMapping
    public Mono<ResponseEntity<Map<String, Object>>> createOrUpdateProfile(
            @Valid @RequestBody WorkspaceProfileRequest request) {
        return workspaceProfileService.createOrUpdateProfile(request)
                .map(profile -> ResponseEntity.status(HttpStatus.CREATED)
                        .body(Map.of(
                                "profile_id", profile.getProfileId(),
                                "message", "Workspace profile processed successfully"
                        )));
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
