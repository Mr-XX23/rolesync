package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.DealResponse;
import com.role_sync.workspace.dto.DealUpsertRequest;
import com.role_sync.workspace.models.DealContact;
import com.role_sync.workspace.models.DealQuote;
import com.role_sync.workspace.models.WorkspaceDeal;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.repository.WorkspaceDealRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import com.role_sync.workspace.repository.WorkspaceRepository;
import com.role_sync.workspace.services.WorkspaceAuthorizationService.CallerContext;
import com.role_sync.workspace.utils.SanitizationUtils;
import jakarta.persistence.OptimisticLockException;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class WorkspaceDealServiceImpl implements WorkspaceDealService {

    private static final int MAX_LIMIT = 500;

    private final WorkspaceDealRepository dealRepository;
    private final WorkspaceRepository workspaceRepository;
    private final WorkspaceProfileRepository profileRepository;
    private final WorkspaceAuthorizationService authorizationService;
    private final PlatformTransactionManager transactionManager;

    @Override
    public Flux<DealResponse> listDeals(UUID workspaceId, UUID authUserId, String stage, String query,
                                        boolean mineOnly, int limit) {
        return Mono.fromCallable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            String wantedStage = stage == null || stage.isBlank() ? null : DealAccess.normalizeStage(stage);
            String needle = query == null || query.isBlank() ? null : query.trim().toLowerCase(Locale.ROOT);
            int max = Math.max(1, Math.min(limit, MAX_LIMIT));
            return dealRepository.findByWorkspaceWithOwner(workspaceId).stream()
                    .filter(deal -> wantedStage == null || wantedStage.equals(deal.getStage()))
                    .filter(deal -> needle == null || contains(deal.getCompany(), needle) || contains(deal.getTitle(), needle))
                    .filter(deal -> !mineOnly || deal.getOwner().getProfileId().equals(caller.profileId()))
                    .limit(max)
                    .map(deal -> toResponse(deal, workspaceId, caller))
                    .toList();
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    public Mono<DealResponse> getDeal(UUID workspaceId, UUID dealId, UUID authUserId) {
        return Mono.fromCallable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            return inTransaction(() -> toResponse(requireDealInWorkspace(dealId, workspaceId), workspaceId, caller));
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<DealResponse> upsertDeal(UUID workspaceId, UUID dealId, UUID authUserId, DealUpsertRequest request) {
        return Mono.fromCallable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            AgentContextAccess.requireWriter(caller.roleName());
            String stage = DealAccess.normalizeStage(request.getStage());
            try {
                return inTransaction(() -> {
                    WorkspaceDeal deal = dealRepository.findWithOwner(dealId).orElse(null);
                    boolean created = deal == null;
                    if (created) {
                        if (request.getExpectedVersion() != null) {
                            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Deal not found");
                        }
                        deal = WorkspaceDeal.builder()
                                .dealId(dealId)
                                .workspace(workspaceRepository.getReferenceById(workspaceId))
                                .owner(profileRepository.getReferenceById(caller.profileId()))
                                .build();
                    } else {
                        if (!deal.getWorkspace().getWorkspaceId().equals(workspaceId)) {
                            throw new ResponseStatusException(HttpStatus.CONFLICT, "This deal id belongs to another workspace");
                        }
                        DealAccess.requireExpectedVersion(request.getExpectedVersion(), deal.getVersion());
                    }
                    String previousStage = deal.getStage();
                    deal.setTitle(SanitizationUtils.sanitizeText(request.getTitle()));
                    deal.setCompany(SanitizationUtils.sanitizeText(request.getCompany()));
                    deal.setStage(stage);
                    deal.setAmount(request.getAmount());
                    deal.setCurrency(request.getCurrency() == null ? "USD" : request.getCurrency());
                    deal.setExpectedCloseDate(request.getExpectedCloseDate());
                    deal.setNextStep(SanitizationUtils.sanitizeText(request.getNextStep()));
                    deal.setNotes(SanitizationUtils.sanitizeText(request.getNotes()));
                    deal.setContacts(sanitizeContacts(request.getContacts()));
                    deal.setQuotes(sanitizeQuotes(request.getQuotes()));
                    if (created) {
                        // Who created the deal; later saves, by people or the agent, don't change it.
                        deal.setSource(request.getSource() == null ? "MANUAL" : request.getSource().toUpperCase(Locale.ROOT));
                    }
                    deal.setClosedAt(DealAccess.closedAt(previousStage, stage, deal.getClosedAt(), LocalDateTime.now()));
                    if (deal.getTitle().isBlank() || deal.getCompany().isBlank()) {
                        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "title and company cannot be blank");
                    }
                    return toResponse(dealRepository.saveAndFlush(deal), workspaceId, caller);
                });
            } catch (ObjectOptimisticLockingFailureException | OptimisticLockException exc) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "This deal was changed by someone else at the same time; reload it and try again");
            } catch (DataIntegrityViolationException exc) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "This deal was created by someone else at the same time; reload it and try again");
            }
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<Void> deleteDeal(UUID workspaceId, UUID dealId, UUID authUserId, Long expectedVersion) {
        return Mono.fromRunnable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            inTransaction(() -> {
                WorkspaceDeal deal = requireDealInWorkspace(dealId, workspaceId);
                DealAccess.requireCanDelete(deal.getOwner().getProfileId(), caller.profileId(), caller.roleName());
                DealAccess.requireExpectedVersion(expectedVersion, deal.getVersion());
                dealRepository.delete(deal);
                return null;
            });
        }).subscribeOn(Schedulers.boundedElastic()).then();
    }

    private WorkspaceDeal requireDealInWorkspace(UUID dealId, UUID workspaceId) {
        return dealRepository.findWithOwner(dealId)
                .filter(deal -> deal.getWorkspace().getWorkspaceId().equals(workspaceId))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Deal not found"));
    }

    private <T> T inTransaction(java.util.function.Supplier<T> work) {
        return new TransactionTemplate(transactionManager).execute(status -> work.get());
    }

    private static DealResponse toResponse(WorkspaceDeal deal, UUID workspaceId, CallerContext caller) {
        WorkspaceProfile owner = deal.getOwner();
        return DealResponse.builder()
                .dealId(deal.getDealId())
                .workspaceId(workspaceId)
                .title(deal.getTitle())
                .company(deal.getCompany())
                .stage(deal.getStage())
                .amount(deal.getAmount())
                .currency(deal.getCurrency())
                .expectedCloseDate(deal.getExpectedCloseDate())
                .nextStep(deal.getNextStep())
                .notes(deal.getNotes())
                .contacts(deal.getContacts() == null ? List.of() : deal.getContacts())
                .quotes(deal.getQuotes() == null ? List.of() : deal.getQuotes())
                .source(deal.getSource())
                .ownerProfileId(owner.getProfileId())
                .ownerName(displayName(owner))
                .canDelete(DealAccess.canDelete(owner.getProfileId(), caller.profileId(), caller.roleName()))
                .closedAt(deal.getClosedAt())
                .version(deal.getVersion())
                .createdAt(deal.getCreatedAt())
                .updatedAt(deal.getUpdatedAt())
                .build();
    }

    static String displayName(WorkspaceProfile profile) {
        if (profile.getDisplayName() != null && !profile.getDisplayName().isBlank()) {
            return profile.getDisplayName().trim();
        }
        String full = ((profile.getFirstName() == null ? "" : profile.getFirstName()) + " "
                + (profile.getLastName() == null ? "" : profile.getLastName())).trim();
        return full.isEmpty() ? "Workspace member" : full;
    }

    private static boolean contains(String value, String needle) {
        return value != null && value.toLowerCase(Locale.ROOT).contains(needle);
    }

    private static List<DealContact> sanitizeContacts(List<DealContact> contacts) {
        if (contacts == null) {
            return List.of();
        }
        return contacts.stream()
                .map(contact -> DealContact.builder()
                        .name(SanitizationUtils.sanitizeText(contact.getName()))
                        .email(contact.getEmail() == null ? null : contact.getEmail().trim())
                        .role(SanitizationUtils.sanitizeText(contact.getRole()))
                        .phone(SanitizationUtils.sanitizePhoneNumber(contact.getPhone()))
                        .build())
                .toList();
    }

    private static List<DealQuote> sanitizeQuotes(List<DealQuote> quotes) {
        if (quotes == null) {
            return List.of();
        }
        return quotes.stream()
                .map(quote -> DealQuote.builder()
                        .number(SanitizationUtils.sanitizeText(quote.getNumber()))
                        .total(quote.getTotal())
                        .currency(quote.getCurrency())
                        .link(sanitizeLink(quote.getLink()))
                        .createdAt(SanitizationUtils.sanitizeText(quote.getCreatedAt()))
                        .build())
                .toList();
    }

    /** Web links and app paths only (a quote saved to the knowledge vault links to an app page). */
    private static String sanitizeLink(String link) {
        String clean = SanitizationUtils.sanitizeUrl(link);
        if (clean == null) {
            return null;
        }
        String lower = clean.toLowerCase(Locale.ROOT);
        return lower.startsWith("https://") || lower.startsWith("http://") || clean.startsWith("/") ? clean : null;
    }
}
