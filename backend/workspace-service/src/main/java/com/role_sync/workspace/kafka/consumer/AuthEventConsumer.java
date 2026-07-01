package com.role_sync.workspace.kafka.consumer;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.role_sync.workspace.dto.WorkspaceProfileRequest;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.kafka.dto.EventEnvelope;
import com.role_sync.workspace.kafka.dto.UserRegisteredPayload;
import com.role_sync.workspace.services.WorkspaceProfileService;
import com.role_sync.workspace.services.WorkspaceService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
@Slf4j
public class AuthEventConsumer {

    private final WorkspaceProfileService workspaceProfileService;
    private final WorkspaceService workspaceService;
    private final ObjectMapper objectMapper;

    @KafkaListener(topics = "auth-user-events", groupId = "workspace-service-group")
    public void consumeAuthEvent(EventEnvelope envelope) {
        try {
            log.info("Received event envelope. Event ID: {}, Type: {}",
                    envelope.getEventId(), envelope.getEventType());

            if ("USER_REGISTERED".equals(envelope.getEventType())) {
                UserRegisteredPayload payload = objectMapper.convertValue(
                        envelope.getPayload(),
                        UserRegisteredPayload.class
                );

                log.info("Processing USER_REGISTERED event for user ID: {}, Name: {} {}",
                        payload.getAuthUserId(), payload.getFirstName(), payload.getLastName());

                WorkspaceProfileRequest request = new WorkspaceProfileRequest(
                        payload.getAuthUserId(),
                        payload.getFirstName(),
                        payload.getLastName(),
                        "Member"
                );

                workspaceProfileService.createOrUpdateProfile(request)
                        .flatMap(profile -> {
                            log.info("Successfully provisioned WorkspaceProfile for user: {}. Creating default personal workspace...", profile.getAuthUserId());
                            
                            String workspaceName = profile.getFirstName() != null && !profile.getFirstName().isBlank()
                                    ? profile.getFirstName() + "'s Workspace"
                                    : "Personal Workspace";

                            WorkspaceRequest wsRequest = new WorkspaceRequest(
                                    workspaceName,
                                    "Default workspace created automatically during account activation."
                            );

                            return workspaceService.createWorkspace(payload.getAuthUserId(), wsRequest);
                        })
                        .doOnSuccess(workspace -> log.info("Successfully provisioned default Workspace: {} for user ID: {}", 
                                workspace.getName(), payload.getAuthUserId()))
                        .doOnError(err -> log.error("Failed to provision default Workspace or Profile: {}", err.getMessage()))
                        .block();
            } else {
                log.warn("Ignored unsupported event type: {}", envelope.getEventType());
            }

        } catch (Exception e) {
            log.error("Error processing auth event: {}", e.getMessage(), e);
        }
    }
}
