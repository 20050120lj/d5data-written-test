# Secured Hello World API — Spring Boot 3.2.0

A minimal but complete Spring Boot service that exposes a `Hello World` endpoint protected by
Spring Security, plus a username/password login endpoint that issues a signed bearer token.

The point of the exercise is the security wiring: the greeting is **not** public, and an
unauthenticated request is answered with **401 Unauthorized** — not a 302 redirect to a login page
and not a 403.

---

## 1. Tech stack

| Item | Version / choice |
| --- | --- |
| Framework | Spring Boot **3.2.0** (`spring-boot-starter-parent`) |
| Language | Java **17** |
| Security | Spring Security **6.1.5** (transitively managed by Boot 3.2.0), `SecurityFilterChain` bean API |
| Token | JJWT **0.12.3**, HMAC-SHA512 signed JWT |
| Password storage | BCrypt (`BCryptPasswordEncoder`) |
| Build | Maven, via the bundled Maven Wrapper (`./mvnw`) — no local Maven installation required |
| Test | JUnit 5 + `@SpringBootTest` + MockMvc |

## 2. Requirements

* JDK 17 or newer (`JAVA_HOME` set, or `java` on `PATH`)
* Network access on the first build only (the wrapper downloads Maven 3.9.9 and Maven Central resolves
  the dependencies)

## 3. Build and run

```bash
# Build (compiles, runs the 5 integration tests, produces an executable jar)
./mvnw clean package

# Run
java -jar target/hello-security-1.0.0.jar
# or: ./mvnw spring-boot:run
```

The service listens on `http://localhost:8080` (`server.port` in
`src/main/resources/application.yml`). To use another port:

```bash
java -jar target/hello-security-1.0.0.jar --server.port=9090
```

> Note: a `SERVER_PORT` environment variable takes precedence over `application.yml`, so if the port
> looks unexpected, pass `--server.port=8080` explicitly.

Demo credentials (single in-memory account, see `UserDetailsConfig`):

```
username: test
password: 123456
```

## 4. API

| Method | Path | Auth required | Success | Failure |
| --- | --- | --- | --- | --- |
| `POST` | `/api/login` | no | `200` + JSON body with `token` | `401` on bad credentials, `400` on blank fields |
| `GET` | `/api/hello` | **yes** — `Authorization: Bearer <token>` | `200`, `text/plain`, body `Hello World` | `401` when the header is missing, malformed, expired or tampered with |

### Login response body

```json
{
  "token": "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0ZXN0IiwiaWF0IjoxNzk0Mzk3MjAyLCJleHAiOjE3OTQ0MDA4MDJ9.0kTOZktu2yJz-tnjFEIRmVWm1N_e7...",
  "tokenType": "Bearer",
  "expiresInMs": 3600000
}
```

## 5. curl walkthrough (real output)

The transcripts below are copied from [`verify.log`](verify.log), produced against the running jar.

### 5.1 `GET /api/hello` without credentials — expect `401`

```bash
curl -i http://localhost:8080/api/hello
```

```http
HTTP/1.1 401 
Content-Type: application/json;charset=UTF-8
Content-Length: 194

{"timestamp":"2026-11-11T11:40:02.118506100Z","status":401,"error":"Unauthorized","message":"Authentication required: provide a valid 'Authorization: Bearer <token>' header","path":"/api/hello"}
```

### 5.2 `POST /api/login` with the correct credentials — expect `200`

```bash
curl -i -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"123456"}'
```

```http
HTTP/1.1 200 
Content-Type: application/json

{"token":"eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0ZXN0IiwiaWF0IjoxNzk0Mzk3MjAyLCJleHAiOjE3OTQ0MDA4MDJ9.0kTOZktu2yJz-tnjFEIRmVWm1N_e7tmVibpxdH4aYiIeYL4lo24VKbiBYOl2SCOFRmw3k3DVyzbFDqW_nQJQUQ","tokenType":"Bearer","expiresInMs":3600000}
```

### 5.3 `GET /api/hello` with that token — expect `200` and `Hello World`

```bash
curl -i http://localhost:8080/api/hello -H "Authorization: Bearer $TOKEN"
```

```http
HTTP/1.1 200 
Content-Type: text/plain;charset=UTF-8
Content-Length: 11

Hello World
```

### 5.4 `POST /api/login` with a wrong password — expect `401`

```bash
curl -i -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"wrong"}'
```

```http
HTTP/1.1 401 
Content-Type: application/json

{"status":401,"error":"Unauthorized","message":"Invalid username or password"}
```

### 5.5 `GET /api/hello` with a tampered token — expect `401`

```http
HTTP/1.1 401 
Content-Type: application/json;charset=UTF-8

{"timestamp":"2026-11-11T11:40:03.025125400Z","status":401,"error":"Unauthorized","message":"Authentication required: provide a valid 'Authorization: Bearer <token>' header","path":"/api/hello"}
```

## 6. Design notes

### Why 401 and not 302 / 403

This is the part of the task that is easy to get wrong, and it is handled explicitly in
`SecurityConfig.securityFilterChain`:

* `formLogin()` is **disabled**. With form login enabled, Spring Security installs
  `LoginUrlAuthenticationEntryPoint`, which answers `302` to `/login` — for a REST client that is a
  broken response, not an error.
* `httpBasic()` is **disabled** too, so no `WWW-Authenticate` browser prompt is involved.
* Once every interactive mechanism is disabled, the default entry point degenerates to
  `Http403ForbiddenEntryPoint`, which would answer **403**. To avoid that, the chain installs a custom
  `AuthenticationEntryPoint` (`RestAuthenticationEntryPoint`) that always writes
  `401 Unauthorized` with a JSON body. `ExceptionTranslationFilter` delegates to it whenever an
  anonymous request reaches a protected matcher, and `AuthController` reuses the same 401 semantics for
  bad credentials.

### Why stateless + CSRF disabled

Authentication travels in the `Authorization` header, never in a cookie, and
`SessionCreationPolicy.STATELESS` means Spring Security neither creates nor reads an `HttpSession`.
CSRF attacks rely on the browser attaching ambient credentials (cookies) to a cross-site request; with
no cookie there is nothing to forge, so `csrf().disable()` is correct here rather than a shortcut.
Disabling it also keeps the API usable by non-browser clients, which cannot fetch a CSRF token.

### Token handling

`JwtService` signs a JWT (`sub` = username, `iat`, `exp` = now + 1h) with HMAC-SHA512, using the
64-byte secret from `app.jwt.secret`. `JwtAuthenticationFilter` (a `OncePerRequestFilter`, placed
before `UsernamePasswordAuthenticationFilter`) verifies the signature and expiry, loads the user and
populates the `SecurityContext`. A missing or invalid token does **not** cause the filter to write a
response: it simply stays anonymous, so all unauthenticated outcomes flow through the single 401 entry
point and stay consistent.

Because the token is signed and self-contained, no server-side session or token table is needed — the
service can be scaled horizontally without shared state.

### Password handling

`123456` is hashed with BCrypt at startup (`UserDetailsConfig.userDetailsService`) and the plaintext
never leaves that line of source. `POST /api/login` delegates the comparison to
`AuthenticationManager` → `DaoAuthenticationProvider`, which uses `PasswordEncoder.matches`, so the
check is a salted-hash comparison, not `String.equals`. Failures return one generic message to avoid
user enumeration.

### Endpoint protection

`authorizeHttpRequests` permits only `POST /api/login` (and the internal `/error` dispatch);
`anyRequest().authenticated()` covers `/api/hello`. There is deliberately **no** `permitAll()` on
`/api/hello`.

## 7. Project structure

```
02-backend/
├── pom.xml                      # Spring Boot 3.2.0 parent, Java 17, web/security/validation/jjwt
├── mvnw / mvnw.cmd / .mvn/      # Maven Wrapper 3.3.4 -> Maven 3.9.9 (reproducible build)
├── build.log                    # real `./mvnw clean package` output (BUILD SUCCESS, 5 tests green)
├── verify.log                   # real curl transcripts against the running jar
├── src/main/java/com/d5data/hellosecurity/
│   ├── HelloSecurityApplication.java
│   ├── config/
│   │   ├── SecurityConfig.java         # SecurityFilterChain, 401 entry point, stateless, csrf off
│   │   └── UserDetailsConfig.java      # BCrypt PasswordEncoder, in-memory user, AuthenticationManager
│   ├── controller/
│   │   ├── AuthController.java         # POST /api/login
│   │   └── HelloController.java        # GET /api/hello -> "Hello World"
│   ├── dto/
│   │   ├── LoginRequest.java
│   │   └── LoginResponse.java
│   └── security/
│       ├── JwtService.java             # sign / verify JWT
│       ├── JwtAuthenticationFilter.java# Bearer token -> SecurityContext
│       └── RestAuthenticationEntryPoint.java # 401 + JSON body
├── src/main/resources/application.yml
└── src/test/java/com/d5data/hellosecurity/HelloSecurityApplicationTests.java
```

## 8. Tests

```bash
./mvnw test
```

`HelloSecurityApplicationTests` boots the real application context and exercises the whole filter
chain through MockMvc:

| Test | Asserts |
| --- | --- |
| `helloWithoutTokenIsRejectedWith401` | `GET /api/hello` → 401 |
| `helloWithInvalidTokenIsRejectedWith401` | garbage bearer token → 401 |
| `loginWithValidCredentialsReturnsToken` | `test`/`123456` → 200 + non-empty `token` |
| `loginWithWrongPasswordReturns401` | `wrong` password → 401 |
| `helloWithTokenReturnsHelloWorld` | valid token → 200, `text/plain`, body exactly `Hello World` |

Latest run (from `build.log`):

```
[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS
```

## 9. Production caveats

This is a demo, and three things would change for real deployment: the JWT secret would come from a
secret manager instead of `application.yml`, the user store would be a database/LDAP instead of
`InMemoryUserDetailsManager`, and refresh tokens plus revocation would be added (a stateless JWT
cannot be revoked before it expires).
