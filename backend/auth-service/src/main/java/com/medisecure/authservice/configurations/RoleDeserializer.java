package com.medisecure.authservice.configurations;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import com.medisecure.authservice.models.Role;

import java.io.IOException;

/**
 * Custom deserializer for Role enum to handle legacy/alternative role names
 * Maps "HEALTH_PROVIDER" to "HEALTHCARE_PROVIDER" for backwards compatibility
 */
public class RoleDeserializer extends JsonDeserializer<Role> {

    @Override
    public Role deserialize(JsonParser parser, DeserializationContext context) throws IOException {
        String value = parser.getText().toUpperCase().trim();

        // Map legacy/alternative role names
        switch (value) {
            case "HEALTH_PROVIDER":
            case "HEALTHCARE_PROVIDER":
                return Role.HEALTHCARE_PROVIDER;
            case "ADMIN":
                return Role.ADMIN;
            case "SUPER_ADMIN":
            case "SUPERADMIN":
                return Role.SUPER_ADMIN;
            case "USER":
                return Role.USER;
            default:
                throw new IllegalArgumentException(
                    String.format("Invalid role: '%s'. Valid roles are: USER, ADMIN, HEALTHCARE_PROVIDER (or HEALTH_PROVIDER), SUPER_ADMIN", value)
                );
        }
    }
}

