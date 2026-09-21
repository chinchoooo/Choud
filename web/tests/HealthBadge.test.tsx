import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthBadge } from "../src/components/HealthBadge";

describe("HealthBadge", () => {
  it("renders the label and a healthy status", () => {
    render(<HealthBadge label="Database" status="healthy" />);

    expect(screen.getByText("Database")).toBeInTheDocument();
    expect(screen.getByText("healthy")).toBeInTheDocument();
  });

  it("renders an unhealthy status", () => {
    render(<HealthBadge label="Engine" status="unhealthy" />);

    expect(screen.getByText("unhealthy")).toBeInTheDocument();
  });
});
