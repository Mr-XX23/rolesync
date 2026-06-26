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
@Table(name = "saved_dashboard_layouts")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SavedDashboardLayout {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "layout_id")
    private UUID layoutId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "profile_id", nullable = false)
    private WorkspaceProfile profile;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "workspace_id", nullable = false)
    private Workspace workspace;

    @Column(name = "layout_name", length = 100, nullable = false)
    private String layoutName;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "layout_config", columnDefinition = "jsonb")
    private Map<String, Object> layoutConfig;

    @Column(name = "is_default", nullable = false)
    @Builder.Default
    private Boolean isDefault = false;

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
