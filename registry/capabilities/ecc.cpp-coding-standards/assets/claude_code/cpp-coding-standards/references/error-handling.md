## Error Handling (E.*)

### Key Rules

| Rule | Summary |
|------|---------|
| **E.1** | Develop an error-handling strategy early in a design |
| **E.2** | Throw an exception to signal that a function can't perform its assigned task |
| **E.6** | Use RAII to prevent leaks |
| **E.12** | Use `noexcept` when throwing is impossible or unacceptable |
| **E.14** | Use purpose-designed user-defined types as exceptions |
| **E.15** | Throw by value, catch by reference |
| **E.16** | Destructors, deallocation, and swap must never fail |
| **E.17** | Don't try to catch every exception in every function |

### Exception Hierarchy

```cpp
// E.14 + E.15: Custom exception types, throw by value, catch by reference
class AppError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class NetworkError : public AppError {
public:
    NetworkError(const std::string& msg, int code)
        : AppError(msg), status_code(code) {}
    int status_code;
};

void fetch_data(const std::string& url) {
    // E.2: Throw to signal failure
    throw NetworkError("connection refused", 503);
}

void run() {
    try {
        fetch_data("https://api.example.com");
    } catch (const NetworkError& e) {
        log_error(e.what(), e.status_code);
    } catch (const AppError& e) {
        log_error(e.what());
    }
    // E.17: Don't catch everything here -- let unexpected errors propagate
}
```

### Anti-Patterns

- Throwing built-in types like `int` or string literals (E.14)
- Catching by value (slicing risk) (E.15)
- Empty catch blocks that silently swallow errors
- Using exceptions for flow control (E.3)
- Error handling based on global state like `errno` (E.28)
