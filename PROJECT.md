# Project: Role-Sync Google OAuth2 Integration

## Architecture
Role-Sync is a microservices architecture with a Spring Boot backend (Gateway, Auth-Service, Config-Service, etc.) and a React Vite frontend.

[Eraser IO ] Overvall Core HLD - Chnage to mermaid

title Full System HLD

// 1. Client Layer
Client Layer [icon: monitor] {
  React Dashboard [icon: react]
}

// 2. Spring Cloud Ecosystem
Spring Cloud Ecosystem [direction: right, color: blue] {
  Config Server [icon: settings]
  Eureka Server [icon: list]
  API Gateway [icon: server]
}

// 3. Core Business Services
Business Services [direction: down] {
  Auth Service [icon: shield]
  Workspace Service [icon: user]
  Billing Service [icon: credit-card]
  Task Orchestration Service [icon: settings]
  Notification Service [icon: mail]
}

// 4. Databases
Databases [direction: down] {
  Auth DB [icon: postgres]
  Workspace DB [icon: database]
  Billing DB [icon: database]
  Tasks DB [icon: database]
  Vector DB (pgvector) [icon: database]
  Notification Store (Redis Logs) [icon: database]
}

// 5. Event Infrastructure
Event Bus [icon: share-2] {
  Message Broker (Kafka) [icon: activity]
}

// 6. AI Engine
AI Engine [direction: down] {
  Knowledge & RAG Service [icon: file-text]
  AI Agent Service (LangGraph) [icon: cpu]
}

// 7. External Integrations
External Integrations [direction: down] {
  Payment Gateway (Stripe eSewa) [icon: globe]
  Email Provider (SMTP) [icon: send]
  External LLMs (OpenAI Anthropic) [icon: cloud]
}

// --- CONNECTIONS ---

// Client Ingress
React Dashboard > API Gateway : HTTPS

// Spring Cloud Governance
API Gateway > Eureka Server : Fetch Routes
Business Services > Eureka Server : Register Service
Business Services > Config Server : Fetch application.yml
API Gateway > Config Server : Load Gateway Config

// Gateway Routing
API Gateway > Auth Service : /api/v1/auth
API Gateway > Workspace Service : /api/v1/workspace
API Gateway > Billing Service : /api/v1/billing
API Gateway > Task Orchestration Service : /api/v1/tasks
API Gateway > Knowledge & RAG Service : /api/v1/documents

// DB Connections
Auth Service > Auth DB
Workspace Service > Workspace DB
Billing Service > Billing DB
Task Orchestration Service > Tasks DB
Notification Service > Notification Store (Redis Logs)
Knowledge & RAG Service > Vector DB (pgvector)


// Internal Sync Calls
Task Orchestration Service > Billing Service : Check Credits
AI Agent Service (LangGraph) > Knowledge & RAG Service : Get Context

// Async Event Flow
Task Orchestration Service > Message Broker (Kafka) : Publish Task
Message Broker (Kafka) > AI Agent Service (LangGraph) : Consume Task
AI Agent Service (LangGraph) > Message Broker (Kafka) : Publish Result
Message Broker (Kafka) > Task Orchestration Service : Save Artifact
Message Broker (Kafka) > Notification Service : Consume TaskCompleted


// Notification Flow
Notification Service > Email Provider (SMTP) : Send Alert
Notification Service > React Dashboard : WebSocket Push (Optional)

// External Outbound
Billing Service > Payment Gateway (Stripe eSewa) : Verify
AI Agent Service (LangGraph) > External LLMs (OpenAI Anthropic) : Generate


