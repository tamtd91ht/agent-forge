### Kotest Spec Styles

#### StringSpec (Simplest)

```kotlin
class CalculatorTest : StringSpec({
    "add two positive numbers" {
        Calculator.add(2, 3) shouldBe 5
    }

    "add negative numbers" {
        Calculator.add(-1, -2) shouldBe -3
    }

    "add zero" {
        Calculator.add(0, 5) shouldBe 5
    }
})
```

#### FunSpec (JUnit-like)

```kotlin
class UserServiceTest : FunSpec({
    val repository = mockk<UserRepository>()
    val service = UserService(repository)

    test("getUser returns user when found") {
        val expected = User(id = "1", name = "Alice")
        coEvery { repository.findById("1") } returns expected

        val result = service.getUser("1")

        result shouldBe expected
    }

    test("getUser throws when not found") {
        coEvery { repository.findById("999") } returns null

        shouldThrow<UserNotFoundException> {
            service.getUser("999")
        }
    }
})
```

#### BehaviorSpec (BDD Style)

```kotlin
class OrderServiceTest : BehaviorSpec({
    val repository = mockk<OrderRepository>()
    val paymentService = mockk<PaymentService>()
    val service = OrderService(repository, paymentService)

    Given("a valid order request") {
        val request = CreateOrderRequest(
            userId = "user-1",
            items = listOf(OrderItem("product-1", quantity = 2)),
        )

        When("the order is placed") {
            coEvery { paymentService.charge(any()) } returns PaymentResult.Success
            coEvery { repository.save(any()) } answers { firstArg() }

            val result = service.placeOrder(request)

            Then("it should return a confirmed order") {
                result.status shouldBe OrderStatus.CONFIRMED
            }

            Then("it should charge payment") {
                coVerify(exactly = 1) { paymentService.charge(any()) }
            }
        }

        When("payment fails") {
            coEvery { paymentService.charge(any()) } returns PaymentResult.Declined

            Then("it should throw PaymentException") {
                shouldThrow<PaymentException> {
                    service.placeOrder(request)
                }
            }
        }
    }
})
```

#### DescribeSpec (RSpec Style)

```kotlin
class UserValidatorTest : DescribeSpec({
    describe("validateUser") {
        val validator = UserValidator()

        context("with valid input") {
            it("accepts a normal user") {
                val user = CreateUserRequest("Alice", "alice@example.com")
                validator.validate(user).shouldBeValid()
            }
        }

        context("with invalid name") {
            it("rejects blank name") {
                val user = CreateUserRequest("", "alice@example.com")
                validator.validate(user).shouldBeInvalid()
            }

            it("rejects name exceeding max length") {
                val user = CreateUserRequest("A".repeat(256), "alice@example.com")
                validator.validate(user).shouldBeInvalid()
            }
        }
    }
})
```
