package com.d5data.hellosecurity.controller;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The secured endpoint required by the task.
 *
 * <p>There is no {@code permitAll()} for this path in {@code SecurityConfig}, so the request must
 * carry a valid bearer token; otherwise it is rejected with 401 before reaching this method.</p>
 */
@RestController
@RequestMapping("/api")
public class HelloController {

    /**
     * @return the literal string {@code Hello World}, served as {@code text/plain}.
     */
    @GetMapping(value = "/hello", produces = MediaType.TEXT_PLAIN_VALUE)
    public String hello() {
        return "Hello World";
    }
}
