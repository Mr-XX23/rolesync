package com.role_sync.workspace.models;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * A sales opportunity, shared by the members of its workspace.
 *
 * <p>The id is chosen by the caller, so creating a deal is an idempotent PUT (the sales agent
 * engine retries safely). {@link #version} gives optimistic locking: an update that names a
 * version someone else has already changed is refused instead of silently overwriting it.
 */
@Entity
@Table(name = "workspace_deals", indexes = {
        @Index(name = "ix_workspace_deals_workspace_updated", columnList = "workspace_id, updated_at")
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceDeal {

    @Id
    @Column(name = "deal_id")
    private UUID dealId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "workspace_id", nullable = false)
    private Workspace workspace;

    /** The member responsible for the deal: whoever created it. */
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "owner_profile_id", nullable = false)
    private WorkspaceProfile owner;

    @Column(name = "title", length = 200, nullable = false)
    private String title;

    /** The customer company. */
    @Column(name = "company", length = 200, nullable = false)
    private String company;

    /** PROSPECTING, QUALIFIED, PROPOSAL, NEGOTIATION, WON or LOST. */
    @Column(name = "stage", length = 30, nullable = false)
    private String stage;

    @Column(name = "amount", precision = 15, scale = 2)
    private BigDecimal amount;

    @Column(name = "currency", length = 3)
    private String currency;

    @Column(name = "expected_close_date")
    private LocalDate expectedCloseDate;

    @Column(name = "next_step", length = 500)
    private String nextStep;

    @Column(name = "notes", columnDefinition = "TEXT")
    private String notes;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "contacts", columnDefinition = "jsonb")
    private List<DealContact> contacts;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "quotes", columnDefinition = "jsonb")
    private List<DealQuote> quotes;

    /** Who last wrote it: MANUAL (the app) or AGENT (the sales agent engine). */
    @Column(name = "source", length = 30)
    private String source;

    /** When the deal reached WON or LOST; cleared if it is reopened. */
    @Column(name = "closed_at")
    private LocalDateTime closedAt;

    @Version
    @Column(name = "version", nullable = false)
    private Long version;

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
