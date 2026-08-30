package com.role_sync.workspace.services;

import com.cloudinary.Cloudinary;
import com.cloudinary.utils.ObjectUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class CloudinaryServiceImpl implements CloudinaryService {

    private static final long MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB
    private static final List<String> ALLOWED_EXTENSIONS = Arrays.asList(
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".jfif", ".pjpeg", ".pjp"
    );

    private final Cloudinary cloudinary;

    @Value("${CLOUDINARY_FOLDER_NAME:${cloudinary.folder-name:rolesync}}")
    private String folderName;

    @Override
    public Mono<String> uploadAvatar(FilePart filePart, String userId) {
        if (filePart == null) {
            return Mono.error(new ResponseStatusException(HttpStatus.BAD_REQUEST, "File is required"));
        }

        String filename = filePart.filename();
        validateFileExtension(filename);

        MediaType mediaType = filePart.headers().getContentType();
        if (mediaType != null && !isAllowedImageContentType(mediaType)) {
            return Mono.error(new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Invalid file type. Supported types: JPEG, PNG, WebP, GIF"
            ));
        }

        return DataBufferUtils.join(filePart.content())
                .flatMap(dataBuffer -> {
                    try {
                        int byteCount = dataBuffer.readableByteCount();
                        if (byteCount <= 0) {
                            return Mono.error(new ResponseStatusException(HttpStatus.BAD_REQUEST, "Uploaded file is empty"));
                        }
                        if (byteCount > MAX_FILE_SIZE) {
                            return Mono.error(new ResponseStatusException(
                                    HttpStatus.BAD_REQUEST,
                                    "File size exceeds the 5MB maximum limit"
                            ));
                        }

                        byte[] bytes = new byte[byteCount];
                        dataBuffer.read(bytes);
                        return uploadImageBytes(bytes, filename, mediaType != null ? mediaType.toString() : "image/jpeg");
                    } finally {
                        DataBufferUtils.release(dataBuffer);
                    }
                });
    }

    @Override
    public Mono<String> uploadImageBytes(byte[] bytes, String filename, String contentType) {
        return Mono.fromCallable(() -> {
            if (bytes == null || bytes.length == 0) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "File content is empty");
            }
            if (bytes.length > MAX_FILE_SIZE) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "File size exceeds the 5MB maximum limit");
            }

            try {
                @SuppressWarnings("unchecked")
                Map<String, Object> uploadResult = (Map<String, Object>) cloudinary.uploader().upload(
                        bytes,
                        ObjectUtils.asMap(
                                "folder", folderName + "/avatars",
                                "resource_type", "image",
                                "overwrite", true,
                                "unique_filename", true
                        )
                );

                String secureUrl = (String) uploadResult.get("secure_url");
                if (secureUrl == null || secureUrl.isBlank()) {
                    log.error("Cloudinary upload did not return a secure_url: {}", uploadResult);
                    throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Cloudinary upload failed: No secure URL returned");
                }
                log.info("Cloud storage upload successful. Secure URL: {}", secureUrl);
                return secureUrl;
            } catch (IOException e) {
                log.error("Cloud storage upload IO exception: {}", e.getMessage(), e);
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Image upload failed. Please try again.");
            } catch (Exception e) {
                log.error("Unexpected error during cloud image upload: {}", e.getMessage(), e);
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Image upload failed. Please try again.");
            }
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<String> uploadImageUrl(String imageUrl, String userId) {
        return Mono.fromCallable(() -> {
            if (imageUrl == null || imageUrl.isBlank()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Image URL cannot be empty");
            }

            String trimmedUrl = imageUrl.trim();
            // If already hosted on Cloudinary in our folder, return as-is
            if (trimmedUrl.contains("cloudinary.com") && trimmedUrl.contains(folderName)) {
                return trimmedUrl;
            }

            if (!trimmedUrl.startsWith("http://") && !trimmedUrl.startsWith("https://")) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Image URL must start with http:// or https://");
            }

            // Attempt 1: Direct Cloudinary URL fetch and host
            try {
                @SuppressWarnings("unchecked")
                Map<String, Object> uploadResult = (Map<String, Object>) cloudinary.uploader().upload(
                        trimmedUrl,
                        ObjectUtils.asMap(
                                "folder", folderName + "/avatars",
                                "resource_type", "image",
                                "overwrite", true,
                                "unique_filename", true
                        )
                );

                String secureUrl = (String) uploadResult.get("secure_url");
                if (secureUrl != null && !secureUrl.isBlank()) {
                    log.info("Cloudinary direct remote URL upload successful: {}", secureUrl);
                    return secureUrl;
                }
            } catch (Exception directEx) {
                log.warn("Direct Cloudinary URL fetch failed for {}: {}. Attempting HTTP client fallback download...", trimmedUrl, directEx.getMessage());
            }

            // Attempt 2: Fallback download with standard browser headers (handles Instagram/Facebook/CDN bot blocks)
            try {
                HttpClient httpClient = HttpClient.newBuilder()
                        .followRedirects(HttpClient.Redirect.ALWAYS)
                        .connectTimeout(Duration.ofSeconds(10))
                        .build();

                HttpRequest httpRequest = HttpRequest.newBuilder()
                        .uri(URI.create(trimmedUrl))
                        .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                        .header("Accept", "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8")
                        .timeout(Duration.ofSeconds(15))
                        .GET()
                        .build();

                HttpResponse<byte[]> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofByteArray());
                if (response.statusCode() >= 200 && response.statusCode() < 300) {
                    byte[] downloadedBytes = response.body();
                    if (downloadedBytes != null && downloadedBytes.length > 0) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> uploadResult = (Map<String, Object>) cloudinary.uploader().upload(
                                downloadedBytes,
                                ObjectUtils.asMap(
                                        "folder", folderName + "/avatars",
                                        "resource_type", "image",
                                        "overwrite", true,
                                        "unique_filename", true
                                )
                        );

                        String secureUrl = (String) uploadResult.get("secure_url");
                        if (secureUrl != null && !secureUrl.isBlank()) {
                            log.info("Cloudinary fallback download & upload successful. Secure URL: {}", secureUrl);
                            return secureUrl;
                        }
                    }
                }
                log.warn("HTTP download returned non-2xx status code: {}", response.statusCode());
            } catch (Exception fallbackEx) {
                log.error("HTTP fallback download and upload failed for {}: {}", trimmedUrl, fallbackEx.getMessage());
            }

            // If remote hosting fails, throw a clear 400 bad request error
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Could not fetch or host image from the provided URL. Please check the link or upload the file directly.");
        }).subscribeOn(Schedulers.boundedElastic());
    }

    private boolean isAllowedImageContentType(MediaType mediaType) {
        if (mediaType == null) return true;
        if ("image".equalsIgnoreCase(mediaType.getType())) {
            return true;
        }
        String fullType = mediaType.toString().toLowerCase();
        return fullType.contains("jpeg") || fullType.contains("jpg") || 
               fullType.contains("png") || fullType.contains("webp") || 
               fullType.contains("gif");
    }

    private void validateFileExtension(String filename) {
        if (filename == null || filename.isBlank()) {
            return; // Allow if content-type is checked
        }
        String lower = filename.toLowerCase();
        // If extension is present, validate it
        if (lower.contains(".")) {
            boolean validExt = ALLOWED_EXTENSIONS.stream().anyMatch(lower::endsWith);
            if (!validExt) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "Invalid file extension. Allowed extensions: .jpg, .jpeg, .png, .webp, .gif"
                );
            }
        }
    }
}
