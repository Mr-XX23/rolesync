package com.rolesync.authservice.kafka.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.time.LocalDateTime;
import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EventEnvelope<T> {
    @Builder.Default
    private String eventId = UUID.randomUUID().toString();
    private String eventType;
    @Builder.Default
    private String timestamp = LocalDateTime.now().toString();
    private String originService;
    private T payload;
}
