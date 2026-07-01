package com.role_sync.workspace.kafka.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EventEnvelope<T> {
    private String eventId;
    private String eventType;
    private String timestamp;
    private String originService;
    private T payload;
}
