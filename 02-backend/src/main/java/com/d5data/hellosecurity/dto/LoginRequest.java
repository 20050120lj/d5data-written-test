package com.d5data.hellosecurity.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * Payload of {@code POST /api/login}.
 */
public record LoginRequest(
        @NotBlank(message = "username must not be blank") String username,
        @NotBlank(message = "password must not be blank") String password) {
}
