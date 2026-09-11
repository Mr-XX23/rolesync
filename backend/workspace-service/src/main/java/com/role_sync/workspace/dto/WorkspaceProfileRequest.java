package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;
import lombok.Builder;

import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceProfileRequest {

    // Server-derived from the gateway-verified X-User-Id; any value sent by the
    // client is ignored (kept for backward-compatible request bodies).
    @JsonProperty("auth_user_id")
    private UUID authUserId;

    @Size(max = 50, message = "First name must not exceed 50 characters")
    @JsonProperty("first_name")
    private String firstName;

    @Size(max = 50, message = "Last name must not exceed 50 characters")
    @JsonProperty("last_name")
    private String lastName;

    @Size(max = 100, message = "Display name must not exceed 100 characters")
    @JsonProperty("display_name")
    private String displayName;

    @Size(max = 1000, message = "Avatar URL must not exceed 1000 characters")
    @JsonProperty("avatar_url")
    private String avatarUrl;

    @Size(max = 100, message = "Job title must not exceed 100 characters")
    @JsonProperty("job_title")
    private String jobTitle;

    @Size(max = 100, message = "Department must not exceed 100 characters")
    @JsonProperty("department")
    private String department;

    @Size(max = 100, message = "Organization must not exceed 100 characters")
    @JsonProperty("organization")
    private String organization;

    @Size(max = 100, message = "Location must not exceed 100 characters")
    @JsonProperty("location")
    private String location;

    @Size(max = 100, message = "Secondary email must not exceed 100 characters")
    @Pattern(regexp = "^$|^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", message = "Invalid email format for secondary email")
    @JsonProperty("secondary_email")
    private String secondaryEmail;

    @Size(max = 25, message = "Phone number must not exceed 25 characters")
    @Pattern(regexp = "^$|^\\+?[0-9\\s\\-\\(\\)]{7,25}$", message = "Invalid phone number format. Allowed characters: digits, +, -, (, ), and spaces")
    @JsonProperty("phone_number")
    private String phoneNumber;

    @Size(max = 3000, message = "Education details must not exceed 3000 characters")
    @JsonProperty("education")
    private String education;

    @Size(max = 3000, message = "Expertise must not exceed 3000 characters")
    @JsonProperty("expertise")
    private String expertise;

    @Size(max = 3000, message = "Skills must not exceed 3000 characters")
    @JsonProperty("skills")
    private String skills;

    @Size(max = 3000, message = "Interests must not exceed 3000 characters")
    @JsonProperty("interests")
    private String interests;

    @Size(max = 3000, message = "Hobbies must not exceed 3000 characters")
    @JsonProperty("hobbies")
    private String hobbies;

    @Size(max = 5000, message = "AI Persona context must not exceed 5000 characters")
    @JsonProperty("ai_persona_context")
    private String aiPersonaContext;

    @Size(max = 100, message = "Communication style must not exceed 100 characters")
    @JsonProperty("communication_style")
    private String communicationStyle;

    @Size(max = 500, message = "LinkedIn URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "LinkedIn URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("linkedin_url")
    private String linkedinUrl;

    @Size(max = 500, message = "GitHub URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "GitHub URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("github_url")
    private String githubUrl;

    @Size(max = 500, message = "Website URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "Website URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("website_url")
    private String websiteUrl;

    @Size(max = 500, message = "Facebook URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "Facebook URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("facebook_url")
    private String facebookUrl;

    @Size(max = 500, message = "X URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "X URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("x_url")
    private String xUrl;

    @Size(max = 500, message = "Instagram URL must not exceed 500 characters")
    @Pattern(regexp = "^$|^https?://.*", message = "Instagram URL must be a valid HTTP/HTTPS URL")
    @JsonProperty("instagram_url")
    private String instagramUrl;

    @Size(max = 3000, message = "Bio must not exceed 3000 characters")
    @JsonProperty("bio")
    private String bio;

    public WorkspaceProfileRequest(UUID authUserId, String firstName, String lastName, String jobTitle) {
        this.authUserId = authUserId;
        this.firstName = firstName;
        this.lastName = lastName;
        this.jobTitle = jobTitle;
    }
}
