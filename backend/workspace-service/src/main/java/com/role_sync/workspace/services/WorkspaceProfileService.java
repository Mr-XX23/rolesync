package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.OnboardingStepRequest;
import com.role_sync.workspace.dto.PreferencesRequest;
import com.role_sync.workspace.dto.WorkspaceProfileRequest;
import com.role_sync.workspace.models.OnboardingState;
import com.role_sync.workspace.models.WorkspacePreferences;
import com.role_sync.workspace.models.WorkspaceProfile;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceProfileService {
    Mono<WorkspaceProfile> createOrUpdateProfile(WorkspaceProfileRequest request);
    Mono<WorkspacePreferences> updatePreferences(UUID authUserId, PreferencesRequest request);
    Mono<OnboardingState> updateOnboardingStep(UUID authUserId, OnboardingStepRequest request);
}
