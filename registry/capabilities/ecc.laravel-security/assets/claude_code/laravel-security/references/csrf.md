## CSRF Protection

### Default Protection

```php
// Laravel CSRF is enabled by default via VerifyCsrfToken middleware
// app/Http/Kernel.php (protected $middlewareGroups['web'])

// All POST/PUT/PATCH/DELETE forms must include @csrf
<form method="POST" action="/posts">
    @csrf
    <input type="text" name="title">
    <button type="submit">Create</button>
</form>
```

### Excluding Routes (Carefully)

```php
// app/Http/Middleware/VerifyCsrfToken.php
class VerifyCsrfToken extends Middleware
{
    // Only exclude routes that have external CSRF protection (webhooks, etc.)
    protected $except = [
        'stripe/*', // Stripe webhooks use their own signature verification
        // Avoid blanket 'api/*' — stateful Sanctum routes need CSRF.
        // Exclude only specific stateless webhook/endpoint routes.
    ];
}
```

### CSRF with JavaScript

```html
<meta name="csrf-token" content="{{ csrf_token() }}">

<script>
// Axios example (Laravel ships with Axios)
axios.defaults.headers.common['X-CSRF-TOKEN'] = document.querySelector(
    'meta[name="csrf-token"]'
).getAttribute('content');

// Fetch example
fetch('/posts', {
    method: 'POST',
    headers: {
        'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').getAttribute('content'),
        'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
});
</script>
```
