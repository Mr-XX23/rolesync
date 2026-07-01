package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.OnboardingStepRequest;
import com.role_sync.workspace.dto.PreferencesRequest;
import com.role_sync.workspace.dto.WorkspaceProfileRequest;
import com.role_sync.workspace.models.OnboardingState;
import com.role_sync.workspace.models.WorkspacePreferences;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.repository.OnboardingStateRepository;
import com.role_sync.workspace.repository.WorkspacePreferencesRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.UUID;

@Service
@RequiredArgsConstructor
public class WorkspaceProfileServiceImpl implements WorkspaceProfileService {

    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspacePreferencesRepository workspacePreferencesRepository;
    private final OnboardingStateRepository onboardingStateRepository;

    @Override
    public Mono<WorkspaceProfile> createOrUpdateProfile(WorkspaceProfileRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(request.getAuthUserId())
                    .orElse(null);
            if (profile == null) {
                profile = WorkspaceProfile.builder()
                        .authUserId(request.getAuthUserId())
                        .firstName(request.getFirstName())
                        .lastName(request.getLastName())
                        .jobTitle(request.getJobTitle())
                        .build();
                profile = workspaceProfileRepository.save(profile);

                // Create default preferences
                WorkspacePreferences prefs = WorkspacePreferences.builder()
                        .profile(profile)
                        .theme("dark")
                        .language("en")
                        .timezone("UTC")
                        .build();
                workspacePreferencesRepository.save(prefs);

                // Create default onboarding state
                OnboardingState onboarding = OnboardingState.builder()
                        .profile(profile)
                        .currentStep("PROFILE_SETUP")
                        .isCompleted(false)
                        .build();
                onboardingStateRepository.save(onboarding);
            } else {
                if (request.getFirstName() != null) profile.setFirstName(request.getFirstName());
                if (request.getLastName() != null) profile.setLastName(request.getLastName());
                if (request.getJobTitle() != null) profile.setJobTitle(request.getJobTitle());
                profile = workspaceProfileRepository.save(profile);
            }
            return profile;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<WorkspacePreferences> updatePreferences(UUID authUserId, PreferencesRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            WorkspacePreferences prefs = workspacePreferencesRepository.findByProfileProfileId(profile.getProfileId())
                    .orElseGet(() -> WorkspacePreferences.builder().profile(profile).build());

            if (request.getTheme() != null) prefs.setTheme(request.getTheme());
            if (request.getLanguage() != null) prefs.setLanguage(request.getLanguage());
            if (request.getTimezone() != null) prefs.setTimezone(request.getTimezone());
            if (request.getDashboardLayout() != null) prefs.setDashboardLayout(request.getDashboardLayout());

            return workspacePreferencesRepository.save(prefs);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<OnboardingState> updateOnboardingStep(UUID authUserId, OnboardingStepRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            OnboardingState onboarding = onboardingStateRepository.findByProfileProfileId(profile.getProfileId())
                    .orElseGet(() -> OnboardingState.builder().profile(profile).build());

            if (request.getCurrentStep() != null) onboarding.setCurrentStep(request.getCurrentStep());
            if (request.getCompletedSteps() != null) onboarding.setCompletedSteps(request.getCompletedSteps());
            if (request.getIsCompleted() != null) onboarding.setIsCompleted(request.getIsCompleted());

            return onboardingStateRepository.save(onboarding);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<WorkspaceProfile> getProfile(UUID authUserId) {
        return Mono.fromCallable(() -> workspaceProfileRepository.findByAuthUserId(authUserId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found")))
                .subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<WorkspacePreferences> getPreferences(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));
            return workspacePreferencesRepository.findByProfileProfileId(profile.getProfileId())
                    .orElseGet(() -> {
                        WorkspacePreferences prefs = WorkspacePreferences.builder()
                                .profile(profile)
                                .theme("dark")
                                .language("en")
                                .timezone("UTC")
                                .build();
                        return workspacePreferencesRepository.save(prefs);
                    });
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<OnboardingState> getOnboardingState(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));
            return onboardingStateRepository.findByProfileProfileId(profile.getProfileId())
                    .orElseGet(() -> {
                        OnboardingState onboarding = OnboardingState.builder()
                                .profile(profile)
                                .currentStep("PROFILE_SETUP")
                                .isCompleted(false)
                                .build();
                        return onboardingStateRepository.save(onboarding);
                    });
        }).subscribeOn(Schedulers.boundedElastic());
    }
}
