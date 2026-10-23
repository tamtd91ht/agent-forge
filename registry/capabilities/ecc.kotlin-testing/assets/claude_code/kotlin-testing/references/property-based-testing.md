### Property-Based Testing

#### Kotest Property Testing

```kotlin
import io.kotest.core.spec.style.FunSpec
import io.kotest.property.Arb
import io.kotest.property.arbitrary.*
import io.kotest.property.forAll
import io.kotest.property.checkAll
import kotlinx.serialization.json.Json
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString

// Note: The serialization roundtrip test below requires the User data class
// to be annotated with @Serializable (from kotlinx.serialization).

class PropertyTest : FunSpec({
    test("string reverse is involutory") {
        forAll<String> { s ->
            s.reversed().reversed() == s
        }
    }

    test("list sort is idempotent") {
        forAll(Arb.list(Arb.int())) { list ->
            list.sorted() == list.sorted().sorted()
        }
    }

    test("serialization roundtrip preserves data") {
        checkAll(Arb.bind(Arb.string(1..50), Arb.string(5..100)) { name, email ->
            User(name = name, email = "$email@test.com")
        }) { user ->
            val json = Json.encodeToString(user)
            val decoded = Json.decodeFromString<User>(json)
            decoded shouldBe user
        }
    }
})
```

#### Custom Generators

```kotlin
val userArb: Arb<User> = Arb.bind(
    Arb.string(minSize = 1, maxSize = 50),
    Arb.email(),
    Arb.enum<Role>(),
) { name, email, role ->
    User(
        id = UserId(UUID.randomUUID().toString()),
        name = name,
        email = Email(email),
        role = role,
    )
}

val moneyArb: Arb<Money> = Arb.bind(
    Arb.long(1L..1_000_000L),
    Arb.enum<Currency>(),
) { amount, currency ->
    Money(amount, currency)
}
```
