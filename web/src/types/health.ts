export type ComponentStatus = "healthy" | "unhealthy";

export interface HealthResponse {
  status: ComponentStatus;
  database: ComponentStatus;
  engine: ComponentStatus;
  storage: ComponentStatus;
}
