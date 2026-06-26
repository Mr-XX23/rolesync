package com.rolesync.authservice.services;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.*;

@Service
@Slf4j
public class SseNotificationService {

    private final Map<UUID, SseEmitter> emitters = new ConcurrentHashMap<>();
    private final ScheduledExecutorService heartbeatScheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "sse-heartbeat-thread");
        thread.setDaemon(true);
        return thread;
    });

    public SseNotificationService() {
        // Start heartbeat pinging every 15 seconds
        heartbeatScheduler.scheduleAtFixedRate(this::sendHeartbeats, 15, 15, TimeUnit.SECONDS);
    }

    /**
     * Subscribe a user to verification events.
     *
     * @param userId The UUID of the user.
     * @return The SseEmitter stream.
     */
    public SseEmitter subscribe(UUID userId) {
        log.info("SSE subscription request received for user: {}", userId);
        
        // Timeout of 5 minutes (300,000 milliseconds)
        SseEmitter emitter = new SseEmitter(300000L);
        
        emitters.put(userId, emitter);
        
        emitter.onCompletion(() -> {
            log.debug("SSE completion for user: {}", userId);
            emitters.remove(userId);
        });
        
        emitter.onTimeout(() -> {
            log.debug("SSE timeout for user: {}", userId);
            emitters.remove(userId);
        });
        
        emitter.onError((e) -> {
            log.debug("SSE error for user: {}: {}", userId, e.getMessage());
            emitters.remove(userId);
        });
        
        // Send initial connected event to client
        try {
            emitter.send(SseEmitter.event()
                    .name("connected")
                    .data("Connection established"));
        } catch (IOException e) {
            log.error("Failed to send initial SSE connection event for user: {}", userId, e);
            emitters.remove(userId);
            emitter.completeWithError(e);
        }
        
        return emitter;
    }

    /**
     * Notify client that email is verified and close the stream.
     *
     * @param userId   The UUID of the user.
     * @param hasPhone Whether the user has a phone number associated.
     */
    public void notifyEmailVerified(UUID userId, boolean hasPhone) {
        SseEmitter emitter = emitters.get(userId);
        if (emitter != null) {
            log.info("Notifying SSE client that email is verified for user: {}, hasPhone: {}", userId, hasPhone);
            try {
                Map<String, Object> payload = new HashMap<>();
                payload.put("userId", userId.toString());
                payload.put("emailVerified", true);
                payload.put("hasPhone", hasPhone);
                
                emitter.send(SseEmitter.event()
                        .name("email-verified")
                        .data(payload));
                emitter.complete();
            } catch (IOException e) {
                log.error("Failed to push email verification success event for user: {}", userId, e);
                emitter.completeWithError(e);
            } finally {
                emitters.remove(userId);
            }
        } else {
            log.debug("No active SSE client subscription found for user: {}", userId);
        }
    }

    /**
     * Ping all active emitters with a heartbeat comment to keep the connection alive.
     */
    private void sendHeartbeats() {
        if (emitters.isEmpty()) {
            return;
        }
        log.debug("Sending SSE heartbeat to {} active subscriber(s)...", emitters.size());
        emitters.forEach((userId, emitter) -> {
            try {
                // Send an empty comment to keep connection alive
                emitter.send(SseEmitter.event().comment("keep-alive"));
            } catch (Exception e) {
                log.debug("Removing failed emitter during heartbeat for user: {}", userId);
                emitters.remove(userId);
            }
        });
    }

    @PreDestroy
    public void shutdown() {
        log.info("Shutting down SSE heartbeat scheduler...");
        heartbeatScheduler.shutdown();
        try {
            if (!heartbeatScheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                heartbeatScheduler.shutdownNow();
            }
        } catch (InterruptedException e) {
            heartbeatScheduler.shutdownNow();
            Thread.currentThread().interrupt();
        }
        emitters.clear();
    }
}
