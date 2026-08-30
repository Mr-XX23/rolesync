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
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class WorkspaceProfileServiceImpl implements WorkspaceProfileService {

    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspacePreferencesRepository workspacePreferencesRepository;
    private final OnboardingStateRepository onboardingStateRepository;
    private final CloudinaryService cloudinaryService;

    @Override
    @Transactional
    public Mono<WorkspaceProfile> createOrUpdateProfile(WorkspaceProfileRequest request) {
        return Mono.fromCallable(() -> {
            String sanitizedFirst = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getFirstName());
            String sanitizedLast = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getLastName());
            String sanitizedDisplay = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getDisplayName());
            String sanitizedAvatar = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getAvatarUrl());
            String sanitizedJob = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getJobTitle());
            String sanitizedDept = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getDepartment());
            String sanitizedOrg = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getOrganization());
            String sanitizedLoc = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getLocation());
            String sanitizedSecEmail = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getSecondaryEmail());
            String sanitizedPhone = com.role_sync.workspace.utils.SanitizationUtils.sanitizePhoneNumber(request.getPhoneNumber());
            String sanitizedEdu = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getEducation());
            String sanitizedExp = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getExpertise());
            String sanitizedSkills = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getSkills());
            String sanitizedInterests = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getInterests());
            String sanitizedHobbies = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getHobbies());
            String sanitizedAiContext = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getAiPersonaContext());
            String sanitizedCommStyle = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getCommunicationStyle());
            String sanitizedLinkedin = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getLinkedinUrl());
            String sanitizedGithub = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getGithubUrl());
            String sanitizedWebsite = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getWebsiteUrl());
            String sanitizedFacebook = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getFacebookUrl());
            String sanitizedX = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getXUrl());
            String sanitizedInstagram = com.role_sync.workspace.utils.SanitizationUtils.sanitizeUrl(request.getInstagramUrl());
            String sanitizedBio = com.role_sync.workspace.utils.SanitizationUtils.sanitizeText(request.getBio());

            // If an external image URL is provided and not yet hosted on Cloudinary, host it permanently
            if (sanitizedAvatar != null && !sanitizedAvatar.isBlank() && !sanitizedAvatar.contains("cloudinary.com")) {
                try {
                    String permanentUrl = cloudinaryService.uploadImageUrl(sanitizedAvatar, request.getAuthUserId().toString()).block();
                    if (permanentUrl != null && !permanentUrl.isBlank()) {
                        sanitizedAvatar = permanentUrl;
                    }
                } catch (Exception e) {
                    log.warn("Could not convert external avatar URL to Cloudinary on profile save: {}", e.getMessage());
                }
            }

            java.time.LocalDateTime now = java.time.LocalDateTime.now();
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(request.getAuthUserId())
                    .orElse(null);
            if (profile == null) {
                profile = WorkspaceProfile.builder()
                        .authUserId(request.getAuthUserId())
                        .dailyUpdateCount(1)
                        .updateWindowStart(now)
                        .firstName(sanitizedFirst)
                        .lastName(sanitizedLast)
                        .displayName(sanitizedDisplay)
                        .avatarUrl(sanitizedAvatar)
                        .jobTitle(sanitizedJob)
                        .department(sanitizedDept)
                        .organization(sanitizedOrg)
                        .location(sanitizedLoc)
                        .secondaryEmail(sanitizedSecEmail)
                        .phoneNumber(sanitizedPhone)
                        .education(sanitizedEdu)
                        .expertise(sanitizedExp)
                        .skills(sanitizedSkills)
                        .interests(sanitizedInterests)
                        .hobbies(sanitizedHobbies)
                        .aiPersonaContext(sanitizedAiContext)
                        .communicationStyle(sanitizedCommStyle)
                        .linkedinUrl(sanitizedLinkedin)
                        .githubUrl(sanitizedGithub)
                        .websiteUrl(sanitizedWebsite)
                        .facebookUrl(sanitizedFacebook)
                        .xUrl(sanitizedX)
                        .instagramUrl(sanitizedInstagram)
                        .bio(sanitizedBio)
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
                // Rate limit enforcement: Maximum 2 updates per 24 hours
                java.time.LocalDateTime windowStart = profile.getUpdateWindowStart();
                Integer currentCount = profile.getDailyUpdateCount();
                if (currentCount == null) currentCount = 0;

                if (windowStart == null || windowStart.isBefore(now.minusHours(24))) {
                    // Reset 24-hour window
                    profile.setUpdateWindowStart(now);
                    profile.setDailyUpdateCount(1);
                } else {
                    if (currentCount >= 2) {
                        java.time.Duration remaining = java.time.Duration.between(now, windowStart.plusHours(24));
                        long hoursRemaining = Math.max(0, remaining.toHours());
                        long minutesRemaining = Math.max(1, remaining.toMinutes() % 60);
                        String timeMessage = hoursRemaining > 0 
                                ? hoursRemaining + " hour(s) and " + minutesRemaining + " minute(s)"
                                : minutesRemaining + " minute(s)";
                        throw new org.springframework.web.server.ResponseStatusException(
                                org.springframework.http.HttpStatus.TOO_MANY_REQUESTS,
                                "Profile update rate limit reached. You can only update your profile 2 times every 24 hours. Please try again in " + timeMessage + "."
                        );
                    }
                    profile.setDailyUpdateCount(currentCount + 1);
                }
                if (request.getFirstName() != null) profile.setFirstName(sanitizedFirst);
                if (request.getLastName() != null) profile.setLastName(sanitizedLast);
                if (request.getDisplayName() != null) profile.setDisplayName(sanitizedDisplay);
                if (request.getAvatarUrl() != null) profile.setAvatarUrl(sanitizedAvatar);
                if (request.getJobTitle() != null) profile.setJobTitle(sanitizedJob);
                if (request.getDepartment() != null) profile.setDepartment(sanitizedDept);
                if (request.getOrganization() != null) profile.setOrganization(sanitizedOrg);
                if (request.getLocation() != null) profile.setLocation(sanitizedLoc);
                if (request.getSecondaryEmail() != null) profile.setSecondaryEmail(sanitizedSecEmail);
                if (request.getPhoneNumber() != null) profile.setPhoneNumber(sanitizedPhone);
                if (request.getEducation() != null) profile.setEducation(sanitizedEdu);
                if (request.getExpertise() != null) profile.setExpertise(sanitizedExp);
                if (request.getSkills() != null) profile.setSkills(sanitizedSkills);
                if (request.getInterests() != null) profile.setInterests(sanitizedInterests);
                if (request.getHobbies() != null) profile.setHobbies(sanitizedHobbies);
                if (request.getAiPersonaContext() != null) profile.setAiPersonaContext(sanitizedAiContext);
                if (request.getCommunicationStyle() != null) profile.setCommunicationStyle(sanitizedCommStyle);
                if (request.getLinkedinUrl() != null) profile.setLinkedinUrl(sanitizedLinkedin);
                if (request.getGithubUrl() != null) profile.setGithubUrl(sanitizedGithub);
                if (request.getWebsiteUrl() != null) profile.setWebsiteUrl(sanitizedWebsite);
                if (request.getFacebookUrl() != null) profile.setFacebookUrl(sanitizedFacebook);
                if (request.getXUrl() != null) profile.setXUrl(sanitizedX);
                if (request.getInstagramUrl() != null) profile.setInstagramUrl(sanitizedInstagram);
                if (request.getBio() != null) profile.setBio(sanitizedBio);
                profile = workspaceProfileRepository.save(profile);
            }
            return profile;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional
    public Mono<WorkspaceProfile> updateAvatarUrl(UUID authUserId, String avatarUrl) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = getOrCreateProfile(authUserId);
            profile.setAvatarUrl(avatarUrl);
            return workspaceProfileRepository.save(profile);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    private WorkspaceProfile getOrCreateProfile(UUID authUserId) {
        return workspaceProfileRepository.findByAuthUserId(authUserId)
                .orElseGet(() -> {
                    WorkspaceProfile profile = WorkspaceProfile.builder()
                            .authUserId(authUserId)
                            .firstName("")
                            .lastName("")
                            .jobTitle("")
                            .build();
                    profile = workspaceProfileRepository.save(profile);

                    WorkspacePreferences prefs = WorkspacePreferences.builder()
                            .profile(profile)
                            .theme("dark")
                            .language("en")
                            .timezone("UTC")
                            .build();
                    workspacePreferencesRepository.save(prefs);

                    OnboardingState onboarding = OnboardingState.builder()
                            .profile(profile)
                            .currentStep("PROFILE_SETUP")
                            .isCompleted(false)
                            .build();
                    onboardingStateRepository.save(onboarding);

                    return profile;
                });
    }

    @Override
    @Transactional
    public Mono<WorkspacePreferences> updatePreferences(UUID authUserId, PreferencesRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = getOrCreateProfile(authUserId);

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
    @Transactional
    public Mono<OnboardingState> updateOnboardingStep(UUID authUserId, OnboardingStepRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = getOrCreateProfile(authUserId);

            OnboardingState onboarding = onboardingStateRepository.findByProfileProfileId(profile.getProfileId())
                    .orElseGet(() -> OnboardingState.builder().profile(profile).build());

            if (request.getCurrentStep() != null) onboarding.setCurrentStep(request.getCurrentStep());
            if (request.getCompletedSteps() != null) onboarding.setCompletedSteps(request.getCompletedSteps());
            if (request.getIsCompleted() != null) onboarding.setIsCompleted(request.getIsCompleted());

            return onboardingStateRepository.save(onboarding);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional(readOnly = true)
    public Mono<WorkspaceProfile> getProfile(UUID authUserId) {
        return Mono.fromCallable(() -> getOrCreateProfile(authUserId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional(readOnly = true)
    public Mono<WorkspacePreferences> getPreferences(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = getOrCreateProfile(authUserId);
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
    @Transactional(readOnly = true)
    public Mono<OnboardingState> getOnboardingState(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = getOrCreateProfile(authUserId);
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
