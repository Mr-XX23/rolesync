package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.OnboardingState;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface OnboardingStateRepository extends JpaRepository<OnboardingState, UUID> {
    Optional<OnboardingState> findByProfileProfileId(UUID profileId);
}
