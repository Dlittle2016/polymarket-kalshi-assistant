
353
354
355
356
357
358
359
360
361
362
363
364
365
366
367
368
369
370
371
372
373
374
375
376
377
378
379
380
381
382
383
384
385
386
387
388
389
390
391
392
393
394
395
396
397
398
399
400
401
402
403
404
405
406
407
408
409
410
411
412
413
414
415
416
417
418
419
420
421
422
423
424
425
426
427
428
429
430
431
432
433
434
435
436
437
438
439
440
441
442
443
444
445
446
447
448
449
450
451
452
453
454
455
456
457
458
459
460
461
462
463
464
465
466
467
468
469
470
471
472
473
474
475
476
477
478
479
480

                def render_group(group):
                    with st.container(border=True):
                        label = "ACTIVE MARKET" if group["active"] else "ARCHIVED / ENDED MARKET"
                        st.markdown(f"**{group['title']}**")
                        st.caption(f"{label} · {group['position_count']} token position(s) · End date: {group['end_date'] or 'not supplied'}")
                        if group["has_both_sides"]:
                            st.warning("OPPOSITE-SIDE HOLDING: both YES and NO are held in this same condition.")
                        a1, a2, a3, a4 = st.columns(4)
                        a1.metric("YES shares", f"{group['yes_shares']:,.4f}")
                        a2.metric("NO shares", f"{group['no_shares']:,.4f}")
                        a3.metric("Net direction", f"{'YES' if group['net_yes_shares'] > 0 else 'NO' if group['net_yes_shares'] < 0 else 'Neutral'} · {abs(group['net_yes_shares']):,.4f}")
                        a4.metric("Combined P&L", money(group["total_pnl"]))
                        b1, b2, b3 = st.columns(3)
                        b1.metric("Combined cost", money(group["total_cost"]))
                        b2.metric("Combined value", money(group["total_value"]))
                        b3.metric("Combined return", f"{(group['total_pnl'] / group['total_cost'] * 100):.2f}%" if group["total_cost"] else "—")
                        for pos in group["positions"]:
                            st.caption(f"{str(pos.get('outcome', 'Unknown')).upper()}: {number(pos.get('current_size')):,.4f} shares · Entry {number(pos.get('avg_price')):.4f} · Current {number(pos.get('current_price')):.4f} · P&L {money(pos.get('unrealized_pnl'))} · Archived={bool(pos.get('archived'))}")
                        st.caption(f"Condition ID: {group['condition']}")

                st.markdown("#### Active-market holdings — candidates for further review")
                if active_groups:
                    for group in active_groups:
                        render_group(group)
                else:
                    st.info("No currently active-market holdings were identified. This trader's returned positions may all be archived or ended.")
                st.markdown("#### Archived / ended holdings — not copy-trading candidates")
                if archived_groups:
                    for group in archived_groups:
                        render_group(group)
                else:
                    st.success("No archived/ended holdings in the returned open-position list.")

                st.markdown("#### Combo positions")
                if combo_positions:
                    for combo in combo_positions:
                        with st.container(border=True):
                            st.markdown(f"**{combo.get('title') or combo.get('name') or 'Combo position'}**")
                            st.write(f"Status: {combo.get('status', '—')} · Value: {money(combo.get('current_value'))} · P&L: {money(combo.get('total_pnl', combo.get('unrealized_pnl')))}")
                            st.caption("Combo positions can span multiple conditions. They are intentionally not folded into single-market YES/NO exposure calculations.")
                            st.json(combo)
                else:
                    st.info("No open combo positions returned for this wallet.")

                with st.expander("Recent activity"):
                    if not activity:
                        st.info("No recent activity returned.")
                    for item in activity[:30]:
                        ts = item.get("timestamp")
                        when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if isinstance(ts, (int, float)) else str(ts or "Time unavailable")
                        title = item.get("title") or item.get("name") or item.get("eventSlug") or "Untitled market"
                        st.write(f"**{when} · {item.get('side') or item.get('type') or 'Activity'} · {title}**")
                        st.caption(f"Outcome: {item.get('outcome', '—')} · Price: {item.get('price', '—')} · Size: {item.get('size', '—')}")

                with st.expander("Recently closed positions"):
                    if not closed_positions:
                        st.info("No closed positions returned.")
                    for pos in closed_positions[:40]:
                        st.write(f"**{pos.get('title') or 'Untitled'}** · {pos.get('outcome', '—')} · Realized P&L {money(pos.get('realized_pnl'))} · Last activity {pos.get('last_event_at', '—')}")

                with st.expander("P&L history"):
                    points = pnl_data.get("points", []) if isinstance(pnl_data, dict) else []
                    if points:
                        import pandas as pd
                        rows = []
                        for point in points:
                            stamp = point.get("timestamp")
                            if stamp is not None:
                                rows.append({"Date": datetime.fromtimestamp(stamp, timezone.utc), "Realized P&L": point.get("realized_pnl"), "Unrealized P&L": point.get("unrealized_pnl")})
                        if rows:
                            frame = pd.DataFrame(rows).set_index("Date").sort_index()
                            st.line_chart(frame)
                            st.dataframe(frame.tail(30), use_container_width=True)
                    else:
                        st.info("No P&L history returned.")

                with st.expander("API diagnostics — HTTP status, trace IDs, and raw responses"):
                    for name, result in bundle.items():
                        st.markdown(f"**{name.upper()}**")
                        if result["error"]:
                            st.error(result["error"])
                        else:
                            st.caption(f"HTTP {result['status']} · Trace ID: {result['trace'] or 'not supplied'}")
                            st.json(result["payload"])
                st.warning("Research caution: an OPEN position can belong to an archived or ended market. The app labels market availability separately from position status. Position data can be delayed or incomplete. Never copy without verifying current executable prices, depth, fees, settlement rules, and whether the trader has since changed the position.")
            except Exception as exc:
                st.error(f"Wallet analysis failed: {exc}")
                st.caption("Copy the full error text if this happens again.")

with calculator_tab:
    st.subheader("Binary contract payoff calculator")
    st.caption("Use an executable ask, not the midpoint or last-traded price.")
    x, y, z = st.columns(3)
    with x:
        stake = st.number_input("Maximum stake ($)", min_value=1.0, value=float(min(bankroll, 55.0)), step=1.0)
    with y:
        ask_cents = st.number_input("Executable ask (cents)", min_value=1.0, max_value=99.0, value=50.0, step=1.0)
    with z:
        fee_per_contract = st.number_input("Estimated fee per contract ($)", min_value=0.0, value=0.01, step=0.01, format="%.3f")
    estimated_probability = st.slider("Your estimated probability of winning", min_value=1, max_value=99, value=55)
    price = ask_cents / 100.0
    cost_each = price + fee_per_contract
    contracts = int(stake // cost_each) if cost_each > 0 else 0
    total_cost = contracts * cost_each
    profit_if_win = contracts * (1.0 - price) - contracts * fee_per_contract
    ev = contracts * (estimated_probability / 100.0 * (1.0 - price) - (1.0 - estimated_probability / 100.0) * price - fee_per_contract)
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Contracts", f"{contracts:,}")
    q2.metric("Total cost", money(total_cost))
    q3.metric("Profit if win", money(profit_if_win))
    q4.metric("Estimated EV", money(ev))
    st.write(f"Maximum loss if it loses: **{money(total_cost)}** · Remaining bankroll: **{money(max(0, bankroll - total_cost))}**")
    st.caption("Estimate excludes unentered fees, spread changes, partial fills, slippage, and settlement risk. EV depends entirely on the probability estimate.")

st.divider()
st.subheader("Before approving any trade")
checks = [
    "The Polymarket and Kalshi contracts resolve on the same real-world event.",
    "The outcome, threshold, measurement period, deadline, and timezone match exactly.",
    "The settlement sources and exception rules are compatible.",
    "The Polymarket position is current and the trader has not exited or reversed it.",
    "The Kalshi price is an executable ask with enough order-book depth.",
    "Fees, spread, slippage, and full-stake loss are included.",
    "The stake is within the bankroll limit and affordable to lose completely.",
]
for idx, item in enumerate(checks):
    st.checkbox(item, key=f"approval_check_{idx}")
