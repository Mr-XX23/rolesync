package com.medisecure.authservice.repository;

import com.medisecure.authservice.models.PasswordResetToken;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface PasswordResetTokenRepository extends JpaRepository<PasswordResetToken, UUID> {
    Optional<PasswordResetToken> findByToken(String token);

    // Find all non-expired tokens (for hashed token verification)
    List<PasswordResetToken> findAllByExpiryDateAfter(LocalDateTime expiryDate);

    long countByAuthUser_AuthUserIdAndExpiryDateAfter(UUID userId, LocalDateTime expiryDate);

    @Modifying
    @Query("DELETE FROM PasswordResetToken p WHERE p.authUser.authUserId = :userId")
    void deleteAllByAuthUser_AuthUserId(@Param("userId") UUID userId);

    // Pessimistic locking for concurrent request protection
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT p FROM PasswordResetToken p WHERE p.authUser.authUserId = :userId")
    List<PasswordResetToken> findByUserIdForUpdate(@Param("userId") UUID userId);

    @Modifying
    @Query("DELETE FROM PasswordResetToken p WHERE p.authUser.authUserId = :userId")
    void deleteAllByUserIdForUpdate(@Param("userId") UUID userId);

    // Cleanup expired tokens
    @Modifying
    @Query("DELETE FROM PasswordResetToken p WHERE p.expiryDate < :now")
    int deleteAllByExpiryDateBefore(@Param("now") LocalDateTime now);
}
