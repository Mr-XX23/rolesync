package com.medisecure.authservice.repository;


import com.medisecure.authservice.models.EmailEventLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

@Repository
public interface EmailEventLogRepository extends JpaRepository<EmailEventLog, UUID> {

    List<EmailEventLog> findByRecipientAndStatusOrderByCreatedAtDesc(
            String recipient, EmailEventLog.EmailStatus status);

    @Query("SELECT e FROM EmailEventLog e WHERE e.status = :status " +
            "AND e.retryAttempts < :maxRetries " +
            "AND e.createdAt > :since")
    List<EmailEventLog> findFailedEmailsForRetry(
            @Param("status") EmailEventLog.EmailStatus status,
            @Param("maxRetries") int maxRetries,
            @Param("since") LocalDateTime since
    );

    long countByRecipientAndCreatedAtAfter(String recipient, LocalDateTime since);
}
