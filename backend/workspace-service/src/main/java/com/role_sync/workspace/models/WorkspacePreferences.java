package com.role_sync.workspace.models;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import lombok.AllArgsConstructor;
import lombok.Builder;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

@Entity
@Table(name = "workspace_preferences")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspacePreferences {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "preference_id")
    private UUID preferenceId;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "profile_id", unique = true, nullable = false)
    private WorkspaceProfile profile;

    @Column(name = "theme", length = 20)
    private String theme;

    @Column(name = "language", length = 10)
    private String language;

    @Column(name = "timezone", length = 50)
    private String timezone;

    @Column(name = "notification_email", nullable = false)
    @Builder.Default
    private Boolean notificationEmail = true;

    @Column(name = "notification_sms", nullable = false)
    @Builder.Default
    private Boolean notificationSms = true;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "dashboard_layout", columnDefinition = "jsonb")
    private Map<String, Object> dashboardLayout;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
