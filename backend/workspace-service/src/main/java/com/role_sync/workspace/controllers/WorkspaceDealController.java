package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.DealResponse;
import com.role_sync.workspace.dto.DealUpsertRequest;
import com.role_sync.workspace.services.WorkspaceDealService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

/**
 * Deals shared by a workspace. Created and changed from the app or by the sales agent engine
 * (which chooses deal ids, so its creates are safe to retry).
 */
@RestController
@RequestMapping("/api/v1/workspaces")
@RequiredArgsConstructor
public class WorkspaceDealController {

    private final WorkspaceDealService dealService;

    @GetMapping("/{workspaceId}/deals")
    public Flux<DealResponse> listDeals(
            @PathVariable UUID workspaceId,
            @RequestParam(value = "stage", required = false) String stage,
            @RequestParam(value = "q", required = false) String query,
            @RequestParam(value = "mine", defaultValue = "false") boolean mineOnly,
            @RequestParam(value = "limit", defaultValue = "200") int limit,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return dealService.listDeals(workspaceId, authUserId, stage, query, mineOnly, limit);
    }

    @GetMapping("/{workspaceId}/deals/{dealId}")
    public Mono<DealResponse> getDeal(
            @PathVariable UUID workspaceId,
            @PathVariable UUID dealId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return dealService.getDeal(workspaceId, dealId, authUserId);
    }

    @PutMapping("/{workspaceId}/deals/{dealId}")
    public Mono<DealResponse> upsertDeal(
            @PathVariable UUID workspaceId,
            @PathVariable UUID dealId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody DealUpsertRequest request) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return dealService.upsertDeal(workspaceId, dealId, authUserId, request);
    }

    @DeleteMapping("/{workspaceId}/deals/{dealId}")
    public Mono<ResponseEntity<Void>> deleteDeal(
            @PathVariable UUID workspaceId,
            @PathVariable UUID dealId,
            @RequestParam(value = "expected_version", required = false) Long expectedVersion,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return dealService.deleteDeal(workspaceId, dealId, authUserId, expectedVersion)
                .then(Mono.just(ResponseEntity.noContent().<Void>build()));
    }

    private UUID resolveAuthUserId(String userIdHeader, String authUserIdHeader) {
        String idStr = userIdHeader != null ? userIdHeader : authUserIdHeader;
        if (idStr == null || idStr.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                    "Missing user identification header (X-User-Id or X-Auth-User-Id)");
        }
        try {
            return UUID.fromString(idStr);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Invalid UUID format in user identification header");
        }
    }
}
