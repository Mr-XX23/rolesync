package com.medisecure.authservice.controllers;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.sql.DataSource;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryMXBean;
import java.lang.management.OperatingSystemMXBean;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/auth/health")
public class HealthCheckController {

    @Autowired
    private DataSource dataSource;

    @GetMapping
    public ResponseEntity<Map<String, Object>> healthCheck() {
        Map<String, Object> health = new HashMap<>();

        health.put("status", "UP");
        health.put("timestamp", Instant.now().toString());
        health.put("service", "auth-service");
        health.put("system", getSystemInfo());
        health.put("memory", getMemoryInfo());
        health.put("database", getDatabaseStatus());
        health.put("activeSessions", getActiveSessionsCount());
        health.put("uptime", getUptime());

        return ResponseEntity.ok(health);
    }

    private Map<String, Object> getSystemInfo() {
        Map<String, Object> systemInfo = new HashMap<>();
        OperatingSystemMXBean osBean = ManagementFactory.getOperatingSystemMXBean();

        systemInfo.put("osName", osBean.getName());
        systemInfo.put("osVersion", osBean.getVersion());
        systemInfo.put("osArch", osBean.getArch());
        systemInfo.put("availableProcessors", osBean.getAvailableProcessors());
        systemInfo.put("systemLoadAverage", osBean.getSystemLoadAverage());

        return systemInfo;
    }

    private Map<String, Object> getMemoryInfo() {
        Map<String, Object> memoryInfo = new HashMap<>();
        MemoryMXBean memoryBean = ManagementFactory.getMemoryMXBean();
        Runtime runtime = Runtime.getRuntime();

        long heapUsed = memoryBean.getHeapMemoryUsage().getUsed();
        long heapMax = memoryBean.getHeapMemoryUsage().getMax();
        long heapCommitted = memoryBean.getHeapMemoryUsage().getCommitted();

        Map<String, Object> heap = new HashMap<>();
        heap.put("used", formatBytes(heapUsed));
        heap.put("max", formatBytes(heapMax));
        heap.put("committed", formatBytes(heapCommitted));
        heap.put("usagePercent", String.format("%.2f%%", (heapUsed * 100.0 / heapMax)));

        long nonHeapUsed = memoryBean.getNonHeapMemoryUsage().getUsed();
        long nonHeapMax = memoryBean.getNonHeapMemoryUsage().getMax();

        Map<String, Object> nonHeap = new HashMap<>();
        nonHeap.put("used", formatBytes(nonHeapUsed));
        nonHeap.put("max", nonHeapMax > 0 ? formatBytes(nonHeapMax) : "undefined");

        memoryInfo.put("heap", heap);
        memoryInfo.put("nonHeap", nonHeap);
        memoryInfo.put("totalMemory", formatBytes(runtime.totalMemory()));
        memoryInfo.put("freeMemory", formatBytes(runtime.freeMemory()));
        memoryInfo.put("maxMemory", formatBytes(runtime.maxMemory()));

        return memoryInfo;
    }

    private Map<String, Object> getDatabaseStatus() {
        Map<String, Object> dbStatus = new HashMap<>();
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {

            ResultSet rs = statement.executeQuery("SELECT version()");
            if (rs.next()) {
                dbStatus.put("status", "UP");
                dbStatus.put("version", rs.getString(1));
                dbStatus.put("database", connection.getCatalog());
            }

            rs = statement.executeQuery("SELECT pg_database_size(current_database())");
            if (rs.next()) {
                dbStatus.put("size", formatBytes(rs.getLong(1)));
            }

            rs = statement.executeQuery("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'");
            if (rs.next()) {
                dbStatus.put("activeConnections", rs.getInt(1));
            }

        } catch (Exception e) {
            dbStatus.put("status", "DOWN");
            dbStatus.put("error", e.getMessage());
        }
        return dbStatus;
    }

    private Map<String, Object> getActiveSessionsCount() {
        Map<String, Object> sessionInfo = new HashMap<>();
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {

            ResultSet rs = statement.executeQuery(
                    "SELECT COUNT(*) FROM auth_user_credentials WHERE status = 'ACTIVE'"
            );

            if (rs.next()) {
                sessionInfo.put("count", rs.getInt(1));
                sessionInfo.put("description", "Active user accounts");
            }
        } catch (Exception e) {
            sessionInfo.put("count", 0);
            sessionInfo.put("error", e.getMessage());
        }
        return sessionInfo;
    }

    private Map<String, Object> getUptime() {
        Map<String, Object> uptimeInfo = new HashMap<>();
        long uptimeMillis = ManagementFactory.getRuntimeMXBean().getUptime();

        long seconds = uptimeMillis / 1000;
        long minutes = seconds / 60;
        long hours = minutes / 60;
        long days = hours / 24;

        uptimeInfo.put("milliseconds", uptimeMillis);
        uptimeInfo.put("formatted", String.format("%d days, %d hours, %d minutes, %d seconds",
                days, hours % 24, minutes % 60, seconds % 60));

        return uptimeInfo;
    }

    private String formatBytes(long bytes) {
        if (bytes < 1024) return bytes + " B";
        int exp = (int) (Math.log(bytes) / Math.log(1024));
        String pre = "KMGTPE".charAt(exp - 1) + "";
        return String.format("%.2f %sB", bytes / Math.pow(1024, exp), pre);
    }

    @GetMapping("/live")
    public ResponseEntity<Map<String, String>> liveness() {
        Map<String, String> response = new HashMap<>();
        response.put("status", "UP");
        response.put("check", "liveness");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> readiness() {
        Map<String, Object> response = new HashMap<>();
        boolean isReady = true;

        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {
            statement.executeQuery("SELECT 1");
            response.put("database", "UP");
        } catch (Exception e) {
            response.put("database", "DOWN");
            response.put("error", e.getMessage());
            isReady = false;
        }

        response.put("status", isReady ? "READY" : "NOT_READY");
        response.put("check", "readiness");

        return ResponseEntity.ok(response);
    }
}
