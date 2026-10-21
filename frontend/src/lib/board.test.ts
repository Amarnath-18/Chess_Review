import { describe, expect, it } from "vitest";
import { badgePosition, squareOrigin } from "./board";

describe("squareOrigin", () => {
  it("places squares for White's orientation (a8 top-left, h1 bottom-right)", () => {
    expect(squareOrigin("a8", "white", 800)).toEqual({ x: 0, y: 0 });
    expect(squareOrigin("h1", "white", 800)).toEqual({ x: 700, y: 700 });
    expect(squareOrigin("e4", "white", 800)).toEqual({ x: 400, y: 400 });
    expect(squareOrigin("a1", "white", 800)).toEqual({ x: 0, y: 700 });
  });

  it("mirrors both axes when the board is flipped", () => {
    expect(squareOrigin("a8", "black", 800)).toEqual({ x: 700, y: 700 });
    expect(squareOrigin("h1", "black", 800)).toEqual({ x: 0, y: 0 });
    expect(squareOrigin("e4", "black", 800)).toEqual({ x: 300, y: 300 });
  });
});

describe("badgePosition", () => {
  it("sits at the top-right of the destination square", () => {
    const sq = 100;
    const { left, top, diameter } = badgePosition("e4", "white", 800);
    const { x, y } = squareOrigin("e4", "white", 800);
    expect(left).toBeGreaterThan(x + sq / 2);
    expect(left + diameter).toBeLessThanOrEqual(x + sq + diameter * 0.3);
    expect(top).toBeLessThan(y + sq / 2);
  });

  it("is kept inside the board at every edge and corner, in both orientations", () => {
    for (const orientation of ["white", "black"] as const) {
      for (const square of ["a1", "a8", "h1", "h8", "d1", "h4"]) {
        const { left, top, diameter } = badgePosition(square, orientation, 480);
        expect(left).toBeGreaterThanOrEqual(0);
        expect(top).toBeGreaterThanOrEqual(0);
        expect(left + diameter).toBeLessThanOrEqual(480);
        expect(top + diameter).toBeLessThanOrEqual(480);
      }
    }
  });

  it("scales with the board but never gets tiny", () => {
    expect(badgePosition("e4", "white", 160).diameter).toBeGreaterThanOrEqual(18);
    expect(badgePosition("e4", "white", 640).diameter).toBeGreaterThan(badgePosition("e4", "white", 320).diameter);
  });
});
