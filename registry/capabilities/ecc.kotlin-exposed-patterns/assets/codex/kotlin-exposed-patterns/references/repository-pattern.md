## Repository Pattern

### Interface Definition

```kotlin
interface UserRepository {
    suspend fun findById(id: UUID): User?
    suspend fun findByEmail(email: String): User?
    suspend fun findAll(page: Int, limit: Int): Page<User>
    suspend fun search(query: String): List<User>
    suspend fun create(request: CreateUserRequest): User
    suspend fun update(id: UUID, request: UpdateUserRequest): User?
    suspend fun delete(id: UUID): Boolean
    suspend fun count(): Long
}
```

### Exposed Implementation

```kotlin
class ExposedUserRepository(
    private val database: Database,
) : UserRepository {

    override suspend fun findById(id: UUID): User? =
        newSuspendedTransaction(db = database) {
            UsersTable.selectAll()
                .where { UsersTable.id eq id }
                .map { it.toUser() }
                .singleOrNull()
        }

    override suspend fun findByEmail(email: String): User? =
        newSuspendedTransaction(db = database) {
            UsersTable.selectAll()
                .where { UsersTable.email eq email }
                .map { it.toUser() }
                .singleOrNull()
        }

    override suspend fun findAll(page: Int, limit: Int): Page<User> =
        newSuspendedTransaction(db = database) {
            val total = UsersTable.selectAll().count()
            val data = UsersTable.selectAll()
                .orderBy(UsersTable.createdAt, SortOrder.DESC)
                .limit(limit)
                .offset(((page - 1) * limit).toLong())
                .map { it.toUser() }
            Page(data = data, total = total, page = page, limit = limit)
        }

    override suspend fun search(query: String): List<User> =
        newSuspendedTransaction(db = database) {
            val sanitized = escapeLikePattern(query.lowercase())
            UsersTable.selectAll()
                .where {
                    (UsersTable.name.lowerCase() like "%${sanitized}%") or
                        (UsersTable.email.lowerCase() like "%${sanitized}%")
                }
                .orderBy(UsersTable.name)
                .map { it.toUser() }
        }

    override suspend fun create(request: CreateUserRequest): User =
        newSuspendedTransaction(db = database) {
            UsersTable.insert {
                it[name] = request.name
                it[email] = request.email
                it[role] = request.role
            }.resultedValues!!.first().toUser()
        }

    override suspend fun update(id: UUID, request: UpdateUserRequest): User? =
        newSuspendedTransaction(db = database) {
            val updated = UsersTable.update({ UsersTable.id eq id }) {
                request.name?.let { name -> it[UsersTable.name] = name }
                request.email?.let { email -> it[UsersTable.email] = email }
                it[updatedAt] = CurrentTimestampWithTimeZone
            }
            if (updated > 0) findById(id) else null
        }

    override suspend fun delete(id: UUID): Boolean =
        newSuspendedTransaction(db = database) {
            UsersTable.deleteWhere { UsersTable.id eq id } > 0
        }

    override suspend fun count(): Long =
        newSuspendedTransaction(db = database) {
            UsersTable.selectAll().count()
        }

    private fun ResultRow.toUser() = User(
        id = this[UsersTable.id].value,
        name = this[UsersTable.name],
        email = this[UsersTable.email],
        role = this[UsersTable.role],
        metadata = this[UsersTable.metadata],
        createdAt = this[UsersTable.createdAt],
        updatedAt = this[UsersTable.updatedAt],
    )
}
```
