package com.d5data.hellosecurity.dto;

/**
 * Successful login response: the bearer token plus the metadata a client needs to use it.
 */
public record LoginResponse(String token, String tokenType, long expiresInMs) {
}
