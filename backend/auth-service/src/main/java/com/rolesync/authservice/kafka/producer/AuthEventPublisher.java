package com.rolesync.authservice.kafka.producer;

import com.rolesync.authservice.kafka.dto.EventEnvelope;
import com.rolesync.authservice.kafka.dto.UserRegisteredPayload;
import com.rolesync.authservice.models.AuthUserCredentials;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
@Slf4j
public class AuthEventPublisher {

    private final KafkaTemplate<String, Object> kafkaTemplate;

    public void publishUserRegistered(AuthUserCredentials user) {
        try {
            // Split username (representing full name) into first and last name
            String fullName = user.getUsername();
            String firstName = "";
            String lastName = "";
            
            if (fullName != null && !fullName.isBlank()) {
                String[] parts = fullName.trim().split("\\s+");
                if (parts.length > 0) {
                    firstName = parts[0];
                }
                if (parts.length > 1) {
                    StringBuilder sb = new StringBuilder();
                    for (int i = 1; i < parts.length; i++) {
                        sb.append(parts[i]).append(" ");
                    }
                    lastName = sb.toString().trim();
                }
            }

            // Create payload
            UserRegisteredPayload payload = UserRegisteredPayload.builder()
                    .authUserId(user.getAuthUserId())
                    .username(user.getUsername())
                    .email(user.getEmail())
                    .phoneNumber(user.getPhoneNumber())
                    .role(user.getRole() != null ? user.getRole().name() : null)
                    .status(user.getStatus() != null ? user.getStatus().name() : null)
                    .firstName(firstName)
                    .lastName(lastName)
                    .build();

            // Create envelope
            EventEnvelope<UserRegisteredPayload> envelope = EventEnvelope.<UserRegisteredPayload>builder()
                    .eventType("USER_REGISTERED")
                    .originService("auth-service")
                    .payload(payload)
                    .build();

            log.info("Publishing USER_REGISTERED event for user ID: {} with event ID: {}",
                    user.getAuthUserId(), envelope.getEventId());

            // Publish message
            kafkaTemplate.send("auth-user-events", user.getAuthUserId().toString(), envelope);

        } catch (Exception e) {
            log.error("Failed to publish USER_REGISTERED event for user ID: {}. Error: {}",
                    user.getAuthUserId(), e.getMessage(), e);
        }
    }
}
