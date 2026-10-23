## Logging Security Events

```php
// config/logging.php
'channels' => [
    'security' => [
        'driver' => 'single',
        'path' => storage_path('logs/security.log'),
        'level' => 'warning',
    ],
],

// Audit log helper
final class SecurityLogger
{
    public static function log(string $event, array $context = []): void
    {
        Log::channel('security')->warning($event, array_merge([
            'user_id' => Auth::id(),
            'ip' => request()->ip(),
            'user_agent' => request()->userAgent(),
            'url' => request()->fullUrl(),
            'timestamp' => now()->toIso8601String(),
        ], $context));
    }
}

// Usage
SecurityLogger::log('failed_login_attempt', ['email' => $email]);
SecurityLogger::log('password_change');
SecurityLogger::log('role_change', ['target_user' => $targetId, 'new_role' => 'admin']);
SecurityLogger::log('suspicious_activity', ['reason' => 'multiple_attempts_from_different_ips']);
```
