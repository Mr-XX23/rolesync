package com.medisecure.authservice.repository;

import com.medisecure.authservice.models.AuthUserCredentials;
import jakarta.validation.constraints.NotBlank;
import org.springframework.stereotype.Repository;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import java.util.Optional;

import java.util.UUID;

@Repository
public interface UserRepository extends JpaRepository<AuthUserCredentials, UUID> {

    boolean existsByEmail(String email);

    boolean existsByPhoneNumber(String phoneNumber);

    boolean existsByUsername(String username);

    boolean existsByEmailOrPhoneNumber(String email, String phoneNumber);

    Optional<AuthUserCredentials> findByEmailOrPhoneNumber(@NotBlank(message = "Email is needed") String email, @NotBlank(message = "Phone number is needed") String phoneNumber);

    Optional<AuthUserCredentials> findByEmail(String email);

    Optional<AuthUserCredentials> findByPhoneNumber(String phoneNumber);

    Optional<AuthUserCredentials> findByUsername(String username);

    Optional<AuthUserCredentials> findByUsernameId(String usernameId);

    @Query("SELECT u FROM AuthUserCredentials u WHERE u.authUserId = :userId AND u.status != 'DELETED'")
    Optional<AuthUserCredentials> findActiveUserById(@Param("userId") UUID userId);
}
