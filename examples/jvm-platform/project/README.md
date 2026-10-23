# Example platform (JVM services + Next.js web)

Two JVM services and a web app, deployed to Kubernetes.

- `services/orders`: Spring Boot, MongoDB (Spring Data), Kafka producer.
- `services/search`: Vert.x, Elasticsearch Java client, MongoDB driver, Kafka consumer.
- `apps/web`: Next.js, Playwright tests.
- `deploy/k8s`: manifests; `infra`: Terraform for the cluster.

Notes for reviewers: we evaluated Hibernate / JPA for `orders` and decided against it
(documents, not rows); Redis and Terraform Cloud are mentioned in the ADRs but not used.
These words appear here only as documentation and must not count as dependencies.
