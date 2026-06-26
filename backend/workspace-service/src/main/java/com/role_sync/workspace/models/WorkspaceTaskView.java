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
@Table(name = "workspace_task_views")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceTaskView {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "view_id")
    private UUID viewId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "workspace_id", nullable = false)
    private Workspace workspace;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "context_id", nullable = false)
    private WorkspaceContext context;

    @Column(name = "task_name", length = 150, nullable = false)
    private String taskName;

    @Column(name = "agent_name", length = 100)
    private String agentName;

    @Column(name = "output_type", length = 50)
    private String outputType;

    @Column(name = "task_status", length = 30)
    private String taskStatus;

    @Column(name = "sort_order")
    private Integer sortOrder;

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
