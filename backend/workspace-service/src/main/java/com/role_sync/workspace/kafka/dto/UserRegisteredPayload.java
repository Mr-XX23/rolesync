package com.role_sync.workspace.kafka.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserRegisteredPayload {
    private UUID authUserId;
    private String username;
    private String email;
    private String phoneNumber;
    private String role;
    private String status;
    private String firstName;
    private String lastName;
}
