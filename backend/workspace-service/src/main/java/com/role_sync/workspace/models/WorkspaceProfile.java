package com.role_sync.workspace.models;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import lombok.AllArgsConstructor;
import lombok.Builder;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "workspace_profiles")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@com.fasterxml.jackson.annotation.JsonIgnoreProperties({"hibernateLazyInitializer", "handler"})
public class WorkspaceProfile {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "profile_id")
    private UUID profileId;

    @Column(name = "auth_user_id", nullable = false, unique = true)
    private UUID authUserId;

    @Column(name = "first_name", length = 50)
    private String firstName;

    @Column(name = "last_name", length = 50)
    private String lastName;

    @Column(name = "display_name", length = 100)
    private String displayName;

    @Column(name = "avatar_url", columnDefinition = "TEXT")
    private String avatarUrl;

    @Column(name = "job_title", length = 100)
    private String jobTitle;

    @Column(name = "department", length = 100)
    private String department;

    @Column(name = "organization", length = 100)
    private String organization;

    @Column(name = "location", length = 100)
    private String location;

    @Column(name = "secondary_email", length = 100)
    private String secondaryEmail;

    @Column(name = "phone_number", length = 50)
    private String phoneNumber;

    @Column(name = "education", columnDefinition = "TEXT")
    private String education;

    @Column(name = "expertise", columnDefinition = "TEXT")
    private String expertise;

    @Column(name = "skills", columnDefinition = "TEXT")
    private String skills;

    @Column(name = "interests", columnDefinition = "TEXT")
    private String interests;

    @Column(name = "hobbies", columnDefinition = "TEXT")
    private String hobbies;

    @Column(name = "ai_persona_context", columnDefinition = "TEXT")
    private String aiPersonaContext;

    @Column(name = "communication_style", length = 100)
    private String communicationStyle;

    @Column(name = "linkedin_url", length = 500)
    private String linkedinUrl;

    @Column(name = "github_url", length = 500)
    private String githubUrl;

    @Column(name = "website_url", length = 500)
    private String websiteUrl;

    @Column(name = "facebook_url", length = 500)
    private String facebookUrl;

    @Column(name = "x_url", length = 500)
    private String xUrl;

    @Column(name = "instagram_url", length = 500)
    private String instagramUrl;

    @Column(name = "bio", columnDefinition = "TEXT")
    private String bio;

    @Column(name = "daily_update_count")
    @Builder.Default
    private Integer dailyUpdateCount = 0;

    @Column(name = "update_window_start")
    private LocalDateTime updateWindowStart;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
