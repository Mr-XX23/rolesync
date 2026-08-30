package com.role_sync.workspace.utils;

import java.util.regex.Pattern;

public final class SanitizationUtils {

    private static final Pattern SCRIPT_PATTERN = Pattern.compile("(?i)<script[\\s\\S]*?>[\\s\\S]*?</script>");
    private static final Pattern HTML_TAG_PATTERN = Pattern.compile("<[^>]+>");
    private static final Pattern JAVASCRIPT_SCHEME_PATTERN = Pattern.compile("(?i)javascript:");
    private static final Pattern DATA_SCHEME_MALICIOUS_PATTERN = Pattern.compile("(?i)data:(?!image/(png|jpeg|jpg|webp|gif)).*");

    private SanitizationUtils() {
    }

    /**
     * Sanitizes general text by stripping dangerous HTML tags and script elements.
     */
    public static String sanitizeText(String input) {
        if (input == null) {
            return null;
        }
        String clean = SCRIPT_PATTERN.matcher(input).replaceAll("");
        clean = HTML_TAG_PATTERN.matcher(clean).replaceAll("");
        clean = JAVASCRIPT_SCHEME_PATTERN.matcher(clean).replaceAll("");
        return clean.trim();
    }

    /**
     * Sanitizes and validates URLs to prevent javascript: or malicious protocol execution.
     */
    public static String sanitizeUrl(String url) {
        if (url == null || url.isBlank()) {
            return null;
        }
        String clean = url.trim();
        if (JAVASCRIPT_SCHEME_PATTERN.matcher(clean).find() || DATA_SCHEME_MALICIOUS_PATTERN.matcher(clean).find()) {
            return null;
        }
        return clean;
    }

    /**
     * Sanitizes phone numbers, keeping only allowed characters (+, digits, spaces, parentheses, hyphens, dots).
     */
    public static String sanitizePhoneNumber(String phone) {
        if (phone == null || phone.isBlank()) {
            return null;
        }
        String clean = phone.trim();
        // Remove all non-phone characters
        clean = clean.replaceAll("[^0-9+\\-\\(\\)\\.\\s]", "");
        return clean;
    }
}
