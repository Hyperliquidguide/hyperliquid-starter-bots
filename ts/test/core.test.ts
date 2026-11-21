// Offline tests: no network, no keys.
import { test } from "node:test";
import assert from "node:assert/strict";
import { RiskGuard, roundPrice, roundSize } from "../src/lib.ts";
import { quotes } from "../src/marketMaker.ts";

test("roundSize rounds down to the lot", () => {
  assert.equal(roundSize(0.000499, 5), "0.00049");
  assert.equal(roundSize(1.999, 0), "1");
});

test("roundPrice: 5 significant figures and 6 - szDecimals decimals", () => {
  assert.equal(roundPrice(60955.37, 5), "60955");
  assert.equal(roundPrice(3123.456, 4), "3123.5");
  assert.equal(roundPrice(0.0123456, 0), "0.012346");
  assert.equal(roundPrice(1.23456789, 2), "1.2346");
  assert.equal(roundPrice(123456, 5), "123456"); // integers are always valid
});

test("quotes straddle the mid and lean against inventory", () => {
  const flat = quotes(100, 10, 2, 0, 15);
  assert.ok(flat.bid < 100 && flat.ask > 100);
  assert.ok(Math.abs(flat.ask - flat.bid - 0.1) < 1e-9);
  const long = quotes(100, 10, 2, 30, 15); // long two order sizes: both quotes move down
  assert.ok(long.bid < flat.bid && long.ask < flat.ask);
});

test("RiskGuard blocks oversize orders, caps the position and halts on loss", () => {
  const g = new RiskGuard(20, 50, 10);
  assert.equal(g.allowOrder(true, 25, 0), false);
  assert.equal(g.allowOrder(true, 15, 40), false);
  assert.equal(g.allowOrder(false, 15, 40), true); // reducing is always allowed
  assert.equal(g.checkEquity(100), true);
  assert.equal(g.checkEquity(89), false);
  assert.equal(g.allowOrder(false, 15, 40), false);
});
