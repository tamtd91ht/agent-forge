---
name: laravel-security
description: Laravel security best practices — authentication, authorization, Eloquent safety, CSRF, XSS prevention, API security, and secure deployment configurations. Use when reviewing Laravel auth, Eloquent safety, CSRF, XSS, API security, or deployment configuration.
metadata:
  origin: ECC
---

# Laravel Security Best Practices

Comprehensive security guidelines for Laravel applications to protect against common vulnerabilities.

## When to Activate

- Setting up Laravel authentication and authorization (Sanctum, Passport, Jetstream, Breeze)
- Implementing user roles, permissions, and policies
- Configuring production security settings and environment variables
- Reviewing Laravel applications for security vulnerabilities
- Deploying Laravel applications to production
- Writing secure Eloquent queries and migrations

## Production Configuration

### Essential Production Settings

```php
// config/app.php
'env' => env('APP_ENV', 'production'),
'debug' => (bool) env('APP_DEBUG', false), // CRITICAL: Never true in production
'key' => env('APP_KEY'), // Must be set: php artisan key:generate

// config/session.php
'secure' => env('SESSION_SECURE_COOKIE', true),
'http_only' => true,
'same_site' => 'lax',

// Verify APP_KEY is set at boot
// bootstrap/app.php or a service provider
if (empty(config('app.key'))) {
    throw new RuntimeException('APP_KEY is not set. Run: php artisan key:generate');
}
```

### Environment File Security

```bash
# NEVER commit .env to version control
# .gitignore already includes .env by default

# Use .env.example with placeholders instead
DB_PASSWORD=
APP_KEY=
SANCTUM_TOKEN_PREFIX=

# Validate required variables at boot
// In AppServiceProvider::boot()
$requiredKeys = ['app.key', 'database.connections.mysql.database', 'database.connections.mysql.username'];
foreach ($requiredKeys as $key) {
    if (empty(config($key))) {
        throw new RuntimeException("Missing required config key: {$key}");
    }
}
```

### HTTPS Enforcement

```php
// AppServiceProvider::boot() or middleware
if (app()->environment('production')) {
    URL::forceScheme('https');
    request()->server->set('HTTPS', 'on');
}

// config/app.php for trusted proxies (load balancers)
// Use specific IP ranges — * trusts all, allowing X-Forwarded-* spoofing
// AWS: '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'
'trusted_proxies' => ['10.0.0.0/8', '172.16.0.0/12'],

// Force HTTPS in production via middleware
// app/Http/Middleware/ForceHttps.php
public function handle($request, Closure $next)
{
    if (!$request->secure() && app()->environment('production')) {
        return redirect()->secure($request->getRequestUri());
    }
    return $next($request);
}
```

## Authentication

Read [references/authentication.md](references/authentication.md) when working on login, Sanctum tokens, password handling or sessions.

## Authorization

### Gates

```php
// App\Providers\AuthServiceProvider
use App\Models\Post;
use App\Models\User;
use Illuminate\Support\Facades\Gate;

public function boot(): void
{
    Gate::define('update-post', function (User $user, Post $post): bool {
        return $user->id === $post->user_id;
    });

    Gate::define('publish-post', function (User $user): bool {
        return $user->role === 'editor' || $user->role === 'admin';
    });

    // Using before() for super-admin override
    Gate::before(function (User $user, string $ability): ?bool {
        if ($user->role === 'super-admin') {
            return true; // Grants all abilities
        }
        return null; // Fall through to normal checks
    });
}

// Usage in controllers
public function update(Request $request, Post $post): RedirectResponse
{
    Gate::authorize('update-post', $post);
    // Or: $this->authorize('update-post', $post);
    // Or: abort_unless(Auth::user()->can('update-post', $post), 403);
    // ...
}
```

### Policies

```php
// App\Policies\PostPolicy
class PostPolicy
{
    use HandlesAuthorization;

    public function viewAny(?User $user): bool
    {
        return true; // Public listing
    }

    public function view(?User $user, Post $post): bool
    {
        return $post->is_published || ($user && $user->id === $post->user_id);
    }

    public function create(User $user): bool
    {
        return $user->hasVerifiedEmail(); // Must verify email first
    }

    public function update(User $user, Post $post): bool
    {
        return $user->id === $post->user_id;
    }

    public function delete(User $user, Post $post): bool
    {
        return $user->id === $post->user_id && $post->created_at->diffInDays(now()) <= 30;
    }

    public function restore(User $user, Post $post): bool
    {
        return $user->role === 'admin';
    }

    public function forceDelete(User $user, Post $post): bool
    {
        return $user->role === 'super-admin';
    }
}

// Register in AuthServiceProvider
protected $policies = [
    Post::class => PostPolicy::class,
];

// Controller usage
public function show(Post $post): View
{
    $this->authorize('view', $post);
    return view('posts.show', compact('post'));
}

// Blade usage
@can('update', $post)
    <a href="{{ route('posts.edit', $post) }}">Edit</a>
@endcan

@cannot('update', $post)
    <span>You cannot edit this post</span>
@endcannot
```

### Middleware Authorization

```php
// Using middleware in routes
Route::put('/posts/{post}', [PostController::class, 'update'])
    ->middleware('can:update,post');

Route::get('/posts/create', [PostController::class, 'create'])
    ->middleware('can:create,App\Models\Post');

// Custom authorization middleware
// app/Http/Middleware/CheckRole.php
class CheckRole
{
    public function handle(Request $request, Closure $next, string $role): mixed
    {
        if (!$request->user() || $request->user()->role !== $role) {
            abort(403, 'Unauthorized. This area requires role: ' . $role);
        }
        return $next($request);
    }
}

// Register in Kernel
protected $routeMiddleware = [
    'role' => \App\Http\Middleware\CheckRole::class,
];

// Route usage
Route::middleware(['auth', 'role:admin'])->group(function () {
    Route::get('/admin', [AdminController::class, 'index']);
});
```

## Eloquent Security

### Mass Assignment Protection

```php
// BAD: $guarded = [] allows ALL columns to be mass-assigned
// NEVER use $guarded = [] in production

// GOOD: Whitelist fillable attributes
final class User extends Authenticatable
{
    protected $fillable = [
        'name',
        'email',
        'phone',
        'avatar',
    ];
    // NEVER add 'role', 'is_admin', 'is_verified' here
}

// GOOD: Explicitly control which fields can be filled in requests
public function store(StoreUserRequest $request): RedirectResponse
{
    $user = User::create($request->safe()->only([
        'name', 'email', 'phone', 'avatar'
    ]));
    // $request->safe() uses validated data only
    // $request->only() is NOT safe on its own without validation rules
}

// BAD: Creating a user with request data directly
User::create($request->all()); // VULNERABLE to mass assignment!

// BETTER: Use DTOs for creation
$user = User::create($request->validated()); // Only validated fields
```

### SQL Injection Prevention

```php
// GOOD: Eloquent automatically parameterizes queries
User::where('email', $userInput)->first();
User::whereRaw('email = ?', [$userInput])->first();

// GOOD: Query Builder also parameterizes
DB::table('users')->where('email', $userInput)->first();
DB::select('SELECT * FROM users WHERE email = ?', [$userInput]);

// BAD: Raw string interpolation
DB::select("SELECT * FROM users WHERE email = '{$userInput}'"); // VULNERABLE!
User::whereRaw("email = '{$userInput}'")->first(); // VULNERABLE!

// BAD: whereRaw/orderByRaw with unescaped input
User::orderByRaw($userInput); // VULNERABLE!
User::groupByRaw($userInput); // VULNERABLE!

// BAD: DB::statement with concatenation
DB::statement("INSERT INTO users (email) VALUES ('{$userInput}')"); // VULNERABLE!
```

### Attribute Casting

```php
final class User extends Authenticatable
{
    protected $casts = [
        'email_verified_at' => 'datetime',
        'is_admin' => 'boolean', // Cast to boolean prevents string injection
        'settings' => 'array', // Automatically json_encode/json_decode
        'metadata' => 'encrypted:array', // Laravel 11+ encrypted casting
        'password' => 'hashed', // Laravel 10+ auto-hashes on set
    ];
}
```

### Model Security

```php
final class User extends Authenticatable
{
    // Hide sensitive attributes from JSON/API responses
    protected $hidden = [
        'password',
        'remember_token',
        'two_factor_secret',
        'two_factor_recovery_codes',
    ];

    // Append only safe computed attributes
    protected $appends = ['full_name']; // safe
    // NEVER append sensitive computed data
}

final class Post extends Model
{
    // Global scope to filter soft deleted records
    use SoftDeletes;

    // Prevent N+1 by restricting lazy loading (optional strict mode)
    // AppServiceProvider::boot()
    // Model::preventLazyLoading(!app()->isProduction());
}
```

## CSRF Protection

Read [references/csrf.md](references/csrf.md) when handling CSRF for forms, excluded routes or JavaScript requests.

## XSS Prevention

### Blade Templating Security

```blade
{{-- SAFE: Auto-escaped by Blade --}}
{{ $userInput }}

{{-- DANGEROUS: Raw output — NEVER use with user input --}}
{!! $userInput !!}

{{-- SAFE: Only use {!! !!} with trusted content you control --}}
{!! $trustedHtmlFromYourServer !!}

{{-- GOOD: Use specific escaping directives --}}
@js($data) {{-- JSON encode for JavaScript --}}
@json($data) {{-- JSON encode in templates --}}

{{-- BAD: Direct user input in raw HTML --}}
<div>{!! $user->bio !!}</div> {{-- VULNERABLE if user provides bio --}}
```

### Safe HTML Handling

```php
// When you must allow some HTML, use a whitelist approach
use HTMLPurifier; // Requires: composer require ezyang/htmlpurifier

public function sanitizeHtml(string $dirty): string
{
    $config = \HTMLPurifier_Config::createDefault();
    $config->set('HTML.Allowed', 'p,b,i,a[href],ul,ol,li,br');
    $config->set('URI.AllowedSchemes', ['http', 'https', 'mailto']);
    $purifier = new \HTMLPurifier($config);
    return $purifier->purify($dirty);
}

// In blade:
<div>{!! $sanitizedContent !!}</div> {{-- Safe after purification --}}
```

### JavaScript Context Escaping

```blade
{{-- SAFE: Blade @js escapes for JavaScript context --}}
<script>
    const user = @js($user); // JSON + escaped for JS context
    const settings = @json($settings); // Direct JSON encode
</script>

{{-- DANGEROUS: Manual JSON in JS context --}}
<script>
    const user = {{ json_encode($user) }}; // NOT escaped for JS!
</script>
```

### HTTP Headers for XSS Protection

```php
// App\Http\Middleware\SecurityHeaders.php
class SecurityHeaders
{
    public function handle(Request $request, Closure $next): mixed
    {
        $response = $next($request);

        $response->headers->set('X-Content-Type-Options', 'nosniff');
        $response->headers->set('X-Frame-Options', 'DENY');
        $response->headers->set('X-XSS-Protection', '1; mode=block');
        $response->headers->set('Referrer-Policy', 'strict-origin-when-cross-origin');
        $response->headers->set(
            'Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        );

        return $response;
    }
}

// Register in kernel
protected $middleware = [
    \App\Http\Middleware\SecurityHeaders::class,
];
```

## Input Validation

### Form Request Validation

```php
final class StorePostRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()?->can('create', Post::class) ?? false;
    }

    public function rules(): array
    {
        return [
            'title' => ['required', 'string', 'max:255', 'sanitize_html'],
            'content' => ['required', 'string', 'max:10000'],
            'image' => [
                'required',
                'image',
                'mimes:jpg,jpeg,png,gif,webp', // Whitelist specific types
                'max:2048', // 2MB max
            ],
            'tags' => ['array'],
            'tags.*' => ['integer', 'exists:tags,id'],
        ];
    }

    public function messages(): array
    {
        return [
            'title.max' => 'Post title must not exceed 255 characters.',
            'image.max' => 'Image must be under 2MB.',
        ];
    }

    // Sanitize input after validation
    public function validated($key = null, $default = null): mixed
    {
        $validated = parent::validated();
        $validated['title'] = strip_tags($validated['title']);
        return $key ? ($validated[$key] ?? $default) : $validated;
    }
}
```

### Custom Validation Rules

```php
// app/Rules/StrongPassword.php
class StrongPassword implements Rule
{
    public function passes($attribute, $value): bool
    {
        return preg_match('/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&#^()_\-+=])[A-Za-z\d@$!%*?&#^()_\-+=]{12,}$/', $value);
    }

    public function message(): string
    {
        return 'The :attribute must be at least 12 characters with uppercase, lowercase, number, and symbol.';
    }
}

// app/Rules/NotBlacklistedDomain.php
class NotBlacklistedDomain implements Rule
{
    private array $blacklisted = ['mailinator.com', 'guerrillamail.com'];

    public function passes($attribute, $value): bool
    {
        $domain = substr(strrchr($value, '@'), 1);
        return !in_array(strtolower($domain), $this->blacklisted);
    }

    public function message(): string
    {
        return 'Email from disposable domains is not allowed.';
    }
}
```

## API Security

Read [references/api-security.md](references/api-security.md) when building or securing an API (rate limiting, Sanctum vs Passport, CORS).

## File Upload Security

Read [references/file-uploads.md](references/file-uploads.md) when accepting or storing uploaded files.

## Dependencies and Secrets

### Composer Security

```bash
# Always audit dependencies in CI
composer audit

# Pin major versions in composer.json
"laravel/framework": "^11.0",
"spatie/laravel-permission": "^6.0"

# Check for abandoned packages
composer why-not

# Keep lock file in version control (it pins exact versions)
# Run `composer update` deliberately, never in CI/CD
```

### Secret Management

```bash
# .env file (NEVER commit)
# .gitignore includes .env by default

APP_KEY=base64:abc123...
DB_PASSWORD=secure_password
STRIPE_KEY=sk_live_...
SANCTUM_TOKEN_PREFIX=myapp_

# For production: Use a secret manager
# Deploy with: env $(aws secretsmanager get-secret-value --secret-id prod/db | jq ...) php artisan serve

# Validate secrets at boot (AppServiceProvider::boot)
$secrets = ['services.stripe.key', 'services.stripe.webhook_secret'];
foreach ($secrets as $key) {
    if (empty(config($key))) {
        Log::critical("Missing secret: {$key}");
    }
}
```

## Queue Security

Read [references/queues.md](references/queues.md) when dispatching or handling queued jobs.

## Logging Security Events

Read [references/security-logging.md](references/security-logging.md) when adding audit or security-event logging.

## Quick Security Checklist

| Check | Description |
|-------|-------------|
| `APP_DEBUG=false` | Never run with debug enabled in production |
| `APP_KEY` set | Always run `php artisan key:generate` |
| HTTPS enforced | Force HTTPS in production via middleware or proxy |
| `$fillable` whitelisted | Never use `$guarded = []` |
| CSRF active | `@csrf` on all state-changing forms |
| Sanctum/Passport configured | API authentication with token abilities/scopes |
| Rate limiting applied | Throttle API and auth endpoints |
| Input validation | FormRequest with specific rules, never `$request->all()` |
| File upload restrictions | Validate MIME types, size, dimensions |
| `composer audit` in CI | Check dependencies for known vulnerabilities |
| `password_hash` / `password_verify` | Use Laravel's built-in hashing (bcrypt/Argon2) |
| Session regeneration on login | Call `$request->session()->regenerate()` |
| Security headers middleware | CSP, X-Frame-Options, X-Content-Type-Options |
| Logged security events | Audit log for auth failures, role changes, suspicious activity |
| `.env` not committed | Verify `.gitignore` includes `.env` |

## Related Skills

- `laravel-patterns` — Laravel architecture, routing, Eloquent, and API patterns
- `backend-patterns` — General backend API and database patterns
- `laravel-tdd` — Laravel testing with PHPUnit and Pest

---
Adapted by Agent Forge from ECC skills/laravel-security/SKILL.md (MIT License, Copyright (c) 2026 Affaan Mustafa): the sections that say "Read references/..." were moved there verbatim, so the skill stays under Claude Code's post-compaction limit.
