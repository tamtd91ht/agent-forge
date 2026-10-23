## File Upload Security

### Validation

```php
public function rules(): array
{
    return [
        'document' => [
            'required',
            'file',
            'mimes:pdf,doc,docx,xls,xlsx', // Whitelist specific MIME types
            'max:10240', // 10MB
            'extensions:pdf,doc,docx,xls,xlsx', // Verify extension matches MIME
        ],
        'avatar' => [
            'nullable',
            'image', // Ensures it's a valid image
            'mimes:jpg,jpeg,png,webp',
            'max:2048',
            'dimensions:min_width=100,min_height=100,max_width=2000,max_height=2000',
        ],
    ];
}
```

### Secure Storage

```php
// Store sensitive files on the same private disk used to create temporary URLs.
$path = $request->file('document')->store('documents', 's3');
// Never use the 'public' disk for sensitive documents.

// Use signed URLs for temporary file access
use Illuminate\Support\Facades\Storage;

public function download(Document $document)
{
    // Requires route-model binding for Document, a persisted $document->path,
    // and a DocumentPolicy::download rule registered with Laravel.
    // Authorize against the model that owns the file, never a path taken from the request
    $this->authorize('download', $document);

    // Generate the temporary signed URL (expires in 15 minutes) only after authorization
    $url = Storage::disk('s3')->temporaryUrl($document->path, now()->addMinutes(15));

    return redirect($url);
}

// Storage configuration for cloud with encryption
// config/filesystems.php
's3' => [
    'driver' => 's3',
    'key' => env('AWS_ACCESS_KEY_ID'),
    'secret' => env('AWS_SECRET_ACCESS_KEY'),
    'region' => env('AWS_DEFAULT_REGION'),
    'bucket' => env('AWS_BUCKET'),
    'url' => env('AWS_URL'),
    'endpoint' => env('AWS_ENDPOINT'),
    'use_path_style_endpoint' => env('AWS_USE_PATH_STYLE_ENDPOINT', false),
    'throw' => false,
    'server_side_encryption' => 'AES256', // Encrypt at rest
],
```
