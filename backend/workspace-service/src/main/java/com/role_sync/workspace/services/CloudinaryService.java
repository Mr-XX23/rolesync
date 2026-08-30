package com.role_sync.workspace.services;

import org.springframework.http.codec.multipart.FilePart;
import reactor.core.publisher.Mono;

public interface CloudinaryService {

    /**
     * Uploads an avatar image FilePart to Cloudinary securely with format and size validation.
     * @param filePart Reactive FilePart from multipart request
     * @param userId Associated user ID for folder partitioning/tagging
     * @return Mono containing the HTTPS secure URL of the uploaded image
     */
    Mono<String> uploadAvatar(FilePart filePart, String userId);

    /**
     * Uploads a raw byte array image to Cloudinary.
     * @param bytes Image byte array
     * @param filename Filename or identifier
     * @param contentType MIME type of the image
     * @return Mono containing the HTTPS secure URL of the uploaded image
     */
    Mono<String> uploadImageBytes(byte[] bytes, String filename, String contentType);

    /**
     * Downloads an image from a remote URL, hosts it in Cloudinary, and returns the permanent Cloudinary HTTPS URL.
     * @param imageUrl Remote image URL
     * @param userId Associated user ID
     * @return Mono containing the permanent Cloudinary HTTPS URL
     */
    Mono<String> uploadImageUrl(String imageUrl, String userId);
}
