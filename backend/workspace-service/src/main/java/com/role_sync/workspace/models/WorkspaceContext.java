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
@Table(name = "workspace_contexts")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceContext {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "context_id")
    private UUID contextId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "workspace_id", nullable = false)
    private Workspace workspace;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "created_by_profile_id", nullable = false)
    private WorkspaceProfile createdBy;

    @Column(name = "title", length = 150, nullable = false)
    private String title;

    @Column(name = "context_type", length = 50)
    private String contextType;

    @Column(name = "summary", columnDefinition = "TEXT")
    private String summary;

    @Column(name = "status", length = 30)
    private String status;

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
