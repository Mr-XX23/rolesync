package com.medisecure.authservice.repository;

import com.medisecure.authservice.models.OtpEventLog;
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
public interface OtpEventLogRepository extends JpaRepository<OtpEventLog, UUID> {

    Optional<OtpEventLog> findFirstByOtpTypeAndOtpCodeAndVerifiedAndExpiresAtAfter(
            String otpType,
            String otpCode,
            Boolean verified,
            LocalDateTime expiresAt
    );

    Optional<OtpEventLog> findFirstByAuthUser_AuthUserIdAndOtpTypeAndVerifiedFalseAndExpiresAtAfter(
            UUID authUserId,
            String otpType,
            LocalDateTime now
    );

    List<OtpEventLog> findAllByAuthUser_AuthUserIdAndOtpTypeAndVerifiedFalseAndExpiresAtAfter(
            UUID authUserId,
            String otpType,
            LocalDateTime expiresAt
    );

    long countByAuthUser_AuthUserIdAndOtpTypeAndCreatedAtAfter(
            UUID authUserId,
            String otpType,
            LocalDateTime createdAt
    );

    // Pessimistic locking for OTP verification (prevents race conditions)
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT o FROM OtpEventLog o WHERE o.authUser.authUserId = :userId " +
           "AND o.otpType = :type AND o.verified = false AND o.expiresAt > :now " +
           "ORDER BY o.createdAt DESC")
    Optional<OtpEventLog> findFirstByUserAndTypeForUpdate(
        @Param("userId") UUID userId,
        @Param("type") String type,
        @Param("now") LocalDateTime now);

    // Cleanup expired OTPs
    @Modifying
    @Query("DELETE FROM OtpEventLog o WHERE o.expiresAt < :now")
    int deleteAllByExpiresAtBefore(@Param("now") LocalDateTime now);
}
