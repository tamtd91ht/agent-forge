## Templates & Generic Programming (T.*)

### Key Rules

| Rule | Summary |
|------|---------|
| **T.1** | Use templates to raise the level of abstraction |
| **T.2** | Use templates to express algorithms for many argument types |
| **T.10** | Specify concepts for all template arguments |
| **T.11** | Use standard concepts whenever possible |
| **T.13** | Prefer shorthand notation for simple concepts |
| **T.43** | Prefer `using` over `typedef` |
| **T.120** | Use template metaprogramming only when you really need to |
| **T.144** | Don't specialize function templates (overload instead) |

### Concepts (C++20)

```cpp
#include <concepts>

// T.10 + T.11: Constrain templates with standard concepts
template<std::integral T>
T gcd(T a, T b) {
    while (b != 0) {
        a = std::exchange(b, a % b);
    }
    return a;
}

// T.13: Shorthand concept syntax
void sort(std::ranges::random_access_range auto& range) {
    std::ranges::sort(range);
}

// Custom concept for domain-specific constraints
template<typename T>
concept Serializable = requires(const T& t) {
    { t.serialize() } -> std::convertible_to<std::string>;
};

template<Serializable T>
void save(const T& obj, const std::string& path);
```

### Anti-Patterns

- Unconstrained templates in visible namespaces (T.47)
- Specializing function templates instead of overloading (T.144)
- Template metaprogramming where `constexpr` suffices (T.120)
- `typedef` instead of `using` (T.43)
