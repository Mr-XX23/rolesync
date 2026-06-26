package com.medisecure.authservice.repository;

import com.medisecure.authservice.models.SmsEventLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface SmsEventLogRepository extends JpaRepository<SmsEventLog, UUID> {

    long countByRecipientAndCreatedAtAfter(String recipient, LocalDateTime since);

    List<SmsEventLog> findByRecipientAndStatusOrderByCreatedAtDesc(
            String recipient, SmsEventLog.SmsStatus status);

    Optional<SmsEventLog> findByMessageSid(String messageSid);

    @Query("SELECT s FROM SmsEventLog s WHERE s.status IN :statuses " +
            "AND s.retryAttempts < :maxRetries " +
            "AND s.createdAt > :since")
    List<SmsEventLog> findFailedSmsForRetry(
            @Param("statuses") List<SmsEventLog.SmsStatus> statuses,
            @Param("maxRetries") int maxRetries,
            @Param("since") LocalDateTime since
    );

    @Query("SELECT COUNT(s) FROM SmsEventLog s WHERE s.authUserId = :authUserId " +
            "AND s.smsType = :smsType AND s.createdAt > :since")
    long countByAuthUserIdAndTypeAndCreatedAtAfter(
            @Param("authUserId") Long authUserId,
            @Param("smsType") SmsEventLog.SmsType smsType,
            @Param("since") LocalDateTime since
    );
}