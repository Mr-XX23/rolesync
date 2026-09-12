package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.DealResponse;
import com.role_sync.workspace.dto.DealUpsertRequest;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceDealService {

    /** The workspace's deals, newest first, optionally narrowed by stage, text (company or title) and owner. */
    Flux<DealResponse> listDeals(UUID workspaceId, UUID authUserId, String stage, String query, boolean mineOnly, int limit);

    Mono<DealResponse> getDeal(UUID workspaceId, UUID dealId, UUID authUserId);

    /** Creates the deal with this id, or replaces it (optionally only if still at {@code expected_version}). */
    Mono<DealResponse> upsertDeal(UUID workspaceId, UUID dealId, UUID authUserId, DealUpsertRequest request);

    /** Deletes the deal (its owner or an OWNER/ADMIN), optionally only if still at {@code expectedVersion}. */
    Mono<Void> deleteDeal(UUID workspaceId, UUID dealId, UUID authUserId, Long expectedVersion);
}
